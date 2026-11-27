import argparse
import csv
import os
import random
import time
import warnings
from datetime import datetime

import numpy as np
import torch
import torch.nn.functional as F
from sklearn.decomposition import PCA
from sklearn.metrics import (
    average_precision_score,
    precision_recall_fscore_support,
    roc_auc_score,
)
from tqdm import tqdm

from config import get_params
from model import Model

EPS = 1e-8
# Small offset for conservative threshold fallback (above max normal support score).
THRESHOLD_EPS = 1e-6

parser = argparse.ArgumentParser()
cfg = get_params()["meta_test"]
parser.add_argument('--pretrained_log_name', type=str,
                    default=cfg["pretrained_log_name"], help='log file name')
parser.add_argument("--load_path", type=str,
                    default=cfg["load_path"], help="latest model path")
parser.add_argument('--log_name', type=str,
                    default=cfg["log_name"], help='log file name')
parser.add_argument('--num_layers', type=int, default=cfg["num_layers"],
                    help='num of encoder layer')
parser.add_argument('--param_dim', type=int, default=cfg["param_dim"],
                    help='max parameters per event')
parser.add_argument('--window_size', type=int,
                    default=cfg["window_size"], help='log sequence length')
parser.add_argument('--support_size', type=int, default=cfg["support_size"],
                    help='number of normal support samples (0 = use all normals)')
parser.add_argument('--support_include_anomaly', action='store_true',
                    help='sample support from both normal and anomaly labels')
parser.add_argument('--episodes', type=int, default=cfg["episodes"],
                    help='number of meta-test episodes')
parser.add_argument('--query_size', type=int, default=cfg["query_size"],
                    help='query samples per episode (0 = use all remaining)')
parser.add_argument('--disable_params', action='store_true',
                    help='disable parameter encoder inputs (template-only)')
parser.add_argument('--disable_rope', action='store_true',
                    help='disable RoPE sequence encoding in transformer layers')
parser.add_argument('--batch_size', type=int, default=cfg["batch_size"])
parser.add_argument('--seed', type=int, default=cfg["seed"])
parser.add_argument('--viz_samples', type=int, default=cfg["viz_samples"],
                    help='number of normal/anomaly query samples to plot')
parser.add_argument('--viz', type=int, default=cfg["viz"],
                    help='1=save embedding plots, 0=skip')
parser.add_argument('--report_cuda_memory', action='store_true',
                    help='print peak CUDA memory allocated/reserved for this run')
parser.add_argument('--csv_path', type=str, default='result/experiments.csv',
                    help='path to append experiment results CSV')
parser.add_argument('--slide_window', type=int, default=0,
                    help='non-overlapping window stride (0 = leave CSV cell empty)')
parser.add_argument('--method', type=str, default='',
                    help='method label for CSV (e.g. MecoLog)')
parser.add_argument(
    '--query_min_abnormal_normal_ratio',
    type=float,
    default=0.0,
    help='If >0, subsample query normals so count(abnormal)/count(normal) >= this '
         'value (reduces extreme normal-heavy query sets for more stable F1).',
)
args = parser.parse_args()
if args.report_cuda_memory and torch.cuda.is_available():
    torch.cuda.reset_peak_memory_stats()

EXPERIMENT_CSV_FIELDS = [
    'name', 'source_domain', 'target_domain', 'num_layers', 'param_dim',
    'window_size', 'slide_window', 'method', 'support_size', 'disable_params',
    'n_support_test', 'n_query_test', 'n_test',
    'support_normal', 'support_abnormal', 'query_normal', 'query_abnormal',
    'train_loss', 'training_time_sec', 'testing_time_sec', 'auc', 'pr_auc', 'f1', 'precision', 'recall',
    'best_threshold', 'load_path',
]


def ensure_experiment_csv_schema(csv_path, fieldnames):
    """Rewrite CSV if header is missing columns so DictWriter rows align."""
    if not os.path.exists(csv_path):
        return
    with open(csv_path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        old_fields = reader.fieldnames
        rows = list(reader)
    if old_fields is None:
        return
    if list(old_fields) == list(fieldnames):
        return
    tmp_path = csv_path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, '') for k in fieldnames})
    os.replace(tmp_path, csv_path)
if args.episodes < 1:
    raise ValueError("episodes must be >= 1")

run_name = datetime.now().strftime("%m%d%H%M")
suffix = f'{args.log_name}_from_{args.pretrained_log_name}'
os.makedirs('result', exist_ok=True)
with open(f'result/test_{suffix}_{run_name}.txt', 'w', encoding='utf-8') as f:
    f.write(str(args)+'\n')

EMBEDDING_DIM = 768
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

warnings.filterwarnings('ignore')
torch.manual_seed(args.seed)
np.random.seed(args.seed)
random.seed(args.seed)
torch.backends.cudnn.deterministic = True

training_data = np.load(
    f'./preprocessed_data/{args.log_name}_training.npz', allow_pickle=True)
testing_data = np.load(
    f'./preprocessed_data/{args.log_name}_testing.npz', allow_pickle=True)
x_train, y_train = training_data['x'], training_data['y']
x_test, y_test = testing_data['x'], testing_data['y']
p_key_train = training_data['p_key'] if 'p_key' in training_data else None
p_type_train = training_data['p_type'] if 'p_type' in training_data else None
p_val_train = training_data['p_val'] if 'p_val' in training_data else None
p_num_train = training_data['p_num'] if 'p_num' in training_data else None
p_key_test = testing_data['p_key'] if 'p_key' in testing_data else None
p_type_test = testing_data['p_type'] if 'p_type' in testing_data else None
p_val_test = testing_data['p_val'] if 'p_val' in testing_data else None
p_num_test = testing_data['p_num'] if 'p_num' in testing_data else None
y_fine_test = testing_data['y_fine'] if 'y_fine' in testing_data else None
key_vocab_size = int(training_data['key_vocab_size']) if 'key_vocab_size' in training_data else 2
char_vocab_size = int(training_data['char_vocab_size']) if 'char_vocab_size' in training_data else 129
max_params = int(training_data['max_params']) if 'max_params' in training_data else args.param_dim
max_chars = int(training_data['max_chars']) if 'max_chars' in training_data else 16
del testing_data
del training_data

y_train = np.argmax(y_train, axis=1)
y_test = np.argmax(y_test, axis=1)
if y_fine_test is not None:
    y_fine_test = np.asarray(y_fine_test).astype(np.int64).ravel()

source_norm = None
source_anom = None
source_path = f'./preprocessed_data/{args.pretrained_log_name}_training.npz'
if os.path.exists(source_path):
    try:
        source_data = np.load(source_path, allow_pickle=True)
        if 'y' in source_data:
            y_source = np.argmax(source_data['y'], axis=1)
            source_norm = int((y_source == 0).sum())
            source_anom = int((y_source == 1).sum())
        del source_data
    except Exception:
        pass

model = Model(num_layers=args.num_layers, max_params=max_params, key_vocab_size=key_vocab_size,
              char_vocab_size=char_vocab_size, max_chars=max_chars, dim=EMBEDDING_DIM,
              window_size=args.window_size, nhead=8, dim_feedforward=4 * EMBEDDING_DIM, dropout=0.1,
              use_rope=not args.disable_rope)
model = model.to(device)
model.eval()

if args.pretrained_log_name != 'random':
    checkpoint = torch.load(args.load_path, map_location=device)
    net = checkpoint['net']
    net.pop('module.fc1.weight', None)
    net.pop('module.fc1.bias', None)
    net.pop('fc1.weight', None)
    net.pop('fc1.bias', None)
    key_weight = net.get('param_encoder.key_emb.weight')
    if key_weight is not None and key_weight.shape != model.param_encoder.key_emb.weight.shape:
        net.pop('param_encoder.key_emb.weight', None)
    key_weight = net.get('module.param_encoder.key_emb.weight')
    if key_weight is not None and key_weight.shape != model.param_encoder.key_emb.weight.shape:
        net.pop('module.param_encoder.key_emb.weight', None)
    r = model.load_state_dict(net, strict=False)
    with open(f'result/test_{suffix}_{run_name}.txt', 'a', encoding='utf-8') as f:
        f.write(f'loading pretrained model {args.load_path}\n')
        f.write(f'loading result: {r}\n')


def encode_batches(model_ref, x, p):
    embeddings = []
    for i in tqdm(range(0, len(x), args.batch_size), desc='encoding'):
        x_slice = x[i:i + args.batch_size]
        def _pad_seq_2d(batch, width, dtype, fill_value=0):
            seqs = list(batch)
            out = np.full((len(seqs), args.window_size, width), fill_value, dtype=dtype)
            for j, s in enumerate(seqs):
                arr = np.asarray(s, dtype=dtype)
                if arr.ndim == 1:
                    arr = arr.reshape(-1, 1)
                arr = arr[:args.window_size, :width]
                out[j, :arr.shape[0], :arr.shape[1]] = arr
            return out

        def _pad_seq_3d(batch, width1, width2, dtype, fill_value=0):
            seqs = list(batch)
            out = np.full((len(seqs), args.window_size, width1, width2), fill_value, dtype=dtype)
            for j, s in enumerate(seqs):
                arr = np.asarray(s, dtype=dtype)
                arr = arr[:args.window_size, :width1, :width2]
                out[j, :arr.shape[0], :arr.shape[1], :arr.shape[2]] = arr
            return out

        if isinstance(x_slice, np.ndarray) and x_slice.dtype == object:
            seqs = list(x_slice)
            if len(seqs) == 0:
                continue
            first = np.asarray(seqs[0])
            embed_dim = first.shape[1] if first.ndim > 1 else 1
            xb_np = _pad_seq_2d(seqs, embed_dim, np.float32, 0.0)
        else:
            xb_np = np.asarray(x_slice, dtype=np.float32)
        xb = torch.tensor(xb_np, device=device, dtype=torch.float32)
        if p is not None:
            p0_slice = p[0][i:i + args.batch_size]
            p1_slice = p[1][i:i + args.batch_size]
            p2_slice = p[2][i:i + args.batch_size]
            p3_slice = p[3][i:i + args.batch_size]

            if isinstance(p0_slice, np.ndarray) and p0_slice.dtype == object:
                p0 = _pad_seq_2d(p0_slice, max_params, np.int64, 0)
                p1 = _pad_seq_2d(p1_slice, max_params, np.int64, 0)
                p3 = _pad_seq_2d(p3_slice, max_params, np.float32, 0.0)
                p2 = _pad_seq_3d(p2_slice, max_params, max_chars, np.int64, 0)
            else:
                p0 = np.asarray(p0_slice, dtype=np.int64)
                p1 = np.asarray(p1_slice, dtype=np.int64)
                p2 = np.asarray(p2_slice, dtype=np.int64)
                p3 = np.asarray(p3_slice, dtype=np.float32)
            pb = (torch.tensor(p0, device=device, dtype=torch.long),
                  torch.tensor(p1, device=device, dtype=torch.long),
                  torch.tensor(p2, device=device, dtype=torch.long),
                  torch.tensor(p3, device=device, dtype=torch.float32))
        else:
            pb = None
        with torch.no_grad():
            zb = model_ref.encode(xb, pb)
        embeddings.append(zb.cpu())
    return torch.cat(embeddings, dim=0)

def balance_query_by_anomaly_ratio(query_idx, y_all, rng, min_abnormal_per_normal):
    """
    Subsample normal query indices so n_anom / n_norm >= min_abnormal_per_normal
    (when both classes are present). Anomalies are kept; normals are capped.
    """
    if min_abnormal_per_normal <= 0.0 or len(query_idx) == 0:
        return query_idx
    yq = y_all[query_idx]
    n_idx = query_idx[yq == 0]
    a_idx = query_idx[yq == 1]
    if len(a_idx) == 0 or len(n_idx) == 0:
        return query_idx
    max_norm = int(np.floor(len(a_idx) / min_abnormal_per_normal))
    max_norm = max(max_norm, 1)
    if len(n_idx) > max_norm:
        n_idx = rng.choice(n_idx, size=max_norm, replace=False)
    return np.sort(np.concatenate([n_idx, a_idx]))


def sample_query_indices(y, max_samples, seed):
    rng = np.random.RandomState(seed)
    normal_idx = np.where(y == 0)[0]
    anom_idx = np.where(y == 1)[0]
    n_norm = min(len(normal_idx), max_samples)
    n_anom = min(len(anom_idx), max_samples)
    s_norm = rng.choice(normal_idx, size=n_norm, replace=False) if n_norm > 0 else np.array([], dtype=int)
    s_anom = rng.choice(anom_idx, size=n_anom, replace=False) if n_anom > 0 else np.array([], dtype=int)
    return s_norm, s_anom

def _load_attack_label_map(log_name):
    import json

    path = os.path.join('preprocessed_data', f'{log_name}_attack_label_map.json')
    if not os.path.isfile(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    raw = data.get('id_to_label') or {}
    out = {}
    for k, v in raw.items():
        try:
            out[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    return out


def _fine_class_colors(class_ids):
    import matplotlib.colors as mcolors

    ids = sorted(set(int(i) for i in class_ids))
    color_of = {0: np.array(mcolors.to_rgb('tab:blue'))}
    palette = list(mcolors.TABLEAU_COLORS.values()) + list(mcolors.CSS4_COLORS.values())
    k = 0
    for cid in ids:
        if cid == 0:
            continue
        color_of[cid] = np.array(mcolors.to_rgb(palette[k % len(palette)]))
        k += 1
    return color_of


def plot_embeddings(
    z_support,
    z_query,
    y_query,
    title,
    out_path,
    y_fine_support=None,
    y_fine_query=None,
    id_to_label=None,
):
    import matplotlib.pyplot as plt

    z_all = torch.cat([z_support, z_query], dim=0).cpu().numpy()
    pca = PCA(n_components=2)
    z_2d = pca.fit_transform(z_all)
    s_len = z_support.size(0)
    z_support_2d = z_2d[:s_len]
    z_query_2d = z_2d[s_len:]

    plt.figure(figsize=(8, 6.5))
    use_fine = y_fine_query is not None and len(y_fine_query) == len(y_query)
    if use_fine:
        yfs = np.asarray(y_fine_support).astype(np.int64).ravel() if y_fine_support is not None else None
        yfq = np.asarray(y_fine_query).astype(np.int64).ravel()
        if yfs is None or len(yfs) != s_len:
            yfs = np.zeros(s_len, dtype=np.int64)
        all_ids = list(np.unique(np.concatenate([yfs, yfq]))) if len(yfq) else list(np.unique(yfs))
        color_of = _fine_class_colors(all_ids)
        plotted = set()

        def scatter_group(pts_2d, fine_ids, prefix, marker='o', s=14):
            for cid in sorted(set(int(x) for x in fine_ids)):
                mask = fine_ids == cid
                if not np.any(mask):
                    continue
                lab = id_to_label.get(cid, f'class_{cid}') if id_to_label else f'class_{cid}'
                key = (prefix, cid)
                if key in plotted:
                    label = None
                else:
                    label = f'{prefix}: {lab}'
                    plotted.add(key)
                c = color_of.get(cid, (0.5, 0.5, 0.5))
                plt.scatter(
                    pts_2d[mask, 0], pts_2d[mask, 1],
                    c=[c], s=s, alpha=0.65, marker=marker, label=label,
                    edgecolors='none',
                )

        scatter_group(z_support_2d, yfs, 'support', marker='^', s=36)
        scatter_group(z_query_2d, yfq, 'query', marker='o', s=14)
    else:
        plt.scatter(z_support_2d[:, 0], z_support_2d[:, 1],
                    c='green', s=6, alpha=0.5, label='support')
        if z_query_2d.size > 0:
            q_norm = z_query_2d[y_query == 0]
            q_anom = z_query_2d[y_query == 1]
            if q_norm.size > 0:
                plt.scatter(q_norm[:, 0], q_norm[:, 1],
                            c='blue', s=6, alpha=0.5, label='query (normal)')
            if q_anom.size > 0:
                plt.scatter(q_anom[:, 0], q_anom[:, 1],
                            c='red', s=6, alpha=0.5, label='query (anomaly)')
    plt.title(title)
    plt.legend(loc='best', frameon=False, fontsize=7, ncol=1)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()


def compute_prototypes(z_support, y_support):
    y_sup = torch.tensor(y_support, device=z_support.device, dtype=torch.long)
    norm_mask = (y_sup == 0)
    anom_mask = (y_sup == 1)
    if not norm_mask.any() or not anom_mask.any():
        return None, None
    mu_norm = F.normalize(z_support[norm_mask].mean(dim=0, keepdim=True), dim=1)
    mu_anom = F.normalize(z_support[anom_mask].mean(dim=0, keepdim=True), dim=1)
    return mu_norm, mu_anom

def prototype_scores(z_query, mu_norm, mu_anom):
    """
    Anomaly score = sim(z, mu_anom) - sim(z, mu_norm).
    Positive = more similar to anomaly prototype than normal prototype.
    Prediction: score > 0 means anomaly (argmax of two prototype sims).
    """
    sim_norm = torch.matmul(z_query, mu_norm.t()).squeeze(-1)
    sim_anom = torch.matmul(z_query, mu_anom.t()).squeeze(-1)
    return sim_anom - sim_norm  # > 0 → anomaly, < 0 → normal



if args.disable_params:
    test_params = None
    train_params = None
else:
    test_params = None if p_key_test is None else (p_key_test, p_type_test, p_val_test, p_num_test)
    train_params = None if p_key_train is None else (p_key_train, p_type_train, p_val_train, p_num_train)

normal_idx_test = np.where(y_test == 0)[0]
anom_idx_test = np.where(y_test == 1)[0]
if not args.support_include_anomaly and normal_idx_test.size == 0:
    raise RuntimeError("No normal samples available for support set.")
if args.support_include_anomaly and len(y_test) == 0:
    raise RuntimeError("No target samples available for support set.")

score_sum = np.zeros(len(x_test), dtype=np.float64)
score_count = np.zeros(len(x_test), dtype=np.int64)


global_support_mask = np.zeros(len(x_test), dtype=bool)

last_support_idx = None
last_query_idx = None
last_z_support = None
last_support_norm = 0
last_support_anom = 0
last_query_norm = 0
last_query_anom = 0
testing_start = time.perf_counter()

for ep in range(args.episodes):
    rng = np.random.RandomState(args.seed + ep)
    if args.support_include_anomaly:
        norm_pool = normal_idx_test[~global_support_mask[normal_idx_test]]
        anom_pool = anom_idx_test[~global_support_mask[anom_idx_test]]
        if norm_pool.size == 0:
            norm_pool = normal_idx_test
        if anom_pool.size == 0:
            anom_pool = anom_idx_test
        if args.support_size > 0:
            half = args.support_size // 2
            n_norm = min(len(norm_pool), half + (args.support_size % 2))
            max_anom_support = len(anom_pool)
            # Keep at least one anomaly for query metrics when possible.
            if args.query_size == 0 and len(anom_pool) > 1:
                max_anom_support = len(anom_pool) - 1
            n_anom = min(max_anom_support, half)
            chosen_norm = rng.choice(norm_pool, size=n_norm, replace=False) if n_norm > 0 else np.array([], dtype=int)
            chosen_anom = rng.choice(anom_pool, size=n_anom, replace=False) if n_anom > 0 else np.array([], dtype=int)
            support_idx = np.concatenate([chosen_norm, chosen_anom])
            if support_idx.size < min(args.support_size, len(y_test)):
                chosen_mask = np.zeros(len(y_test), dtype=bool)
                chosen_mask[support_idx] = True
                remaining = np.where(~chosen_mask)[0]
                need = min(args.support_size, len(y_test)) - support_idx.size
                if need > 0 and remaining.size > 0:
                    extra = rng.choice(remaining, size=min(need, remaining.size), replace=False)
                    support_idx = np.concatenate([support_idx, extra])
            if support_idx.size == 0:
                raise RuntimeError("No samples available for support set.")
        else:
            support_idx = np.arange(len(y_test))
    else:
        support_pool = normal_idx_test[~global_support_mask[normal_idx_test]]
        if support_pool.size == 0:
            support_pool = normal_idx_test
        support_idx = support_pool
        if args.support_size > 0:
            support_idx = rng.choice(
                support_pool, size=min(args.support_size, len(support_pool)), replace=False)
    global_support_mask[support_idx] = True

    all_idx = np.arange(len(x_test))
    support_mask = global_support_mask
    query_pool = all_idx[~support_mask]
    if args.query_size > 0:
        q_size = min(args.query_size, len(query_pool))
        query_idx = rng.choice(query_pool, size=q_size, replace=False) if q_size > 0 else np.array([], dtype=int)
    else:
        query_idx = query_pool

    if args.query_min_abnormal_normal_ratio > 0.0:
        query_idx = balance_query_by_anomaly_ratio(
            query_idx, y_test, rng, args.query_min_abnormal_normal_ratio)

    x_support = x_test[support_idx]
    if args.disable_params or p_key_test is None:
        p_support = None
    else:
        p_support = (p_key_test[support_idx], p_type_test[support_idx],
                     p_val_test[support_idx], p_num_test[support_idx])

    x_query = x_test[query_idx]
    if args.disable_params or p_key_test is None:
        p_query = None
    else:
        p_query = (p_key_test[query_idx], p_type_test[query_idx],
                   p_val_test[query_idx], p_num_test[query_idx])

    z_support = encode_batches(model, x_support, p_support)
    z_support = F.normalize(z_support, dim=1)
    y_support = y_test[support_idx] 
    z_query = encode_batches(model, x_query, p_query) if len(query_idx) > 0 else None
    # Build both prototypes from support
    mu_norm, mu_anom = compute_prototypes(z_support, y_support)
    if mu_norm is None or mu_anom is None:
        continue  # skip episode — no both-class support available

    # Score queries: argmax over both prototypes (Eq. 16)
    if z_query is not None:
        z_query = F.normalize(z_query, dim=1)
        ep_scores = prototype_scores(z_query, mu_norm, mu_anom).cpu().numpy()
        score_sum[query_idx] += ep_scores
        score_count[query_idx] += 1



    last_support_idx = support_idx
    last_query_idx = query_idx
    last_z_support = z_support
    last_support_norm = int((y_test[support_idx] == 0).sum())
    last_support_anom = int((y_test[support_idx] == 1).sum())
    last_query_norm = int((y_test[query_idx] == 0).sum()) if len(query_idx) > 0 else 0
    last_query_anom = int((y_test[query_idx] == 1).sum()) if len(query_idx) > 0 else 0
testing_time_sec = float(time.perf_counter() - testing_start)

valid_mask = score_count > 0
if not np.any(valid_mask):
    raise RuntimeError("No query samples scored. Reduce support_size or query_size.")

anomaly_scores = np.full(len(x_test), np.nan, dtype=np.float64)
anomaly_scores[valid_mask] = score_sum[valid_mask] / score_count[valid_mask]
y_scored = y_test[valid_mask]
scores_eval = anomaly_scores[valid_mask]
auc = roc_auc_score(y_scored, scores_eval)
if len(np.unique(y_scored)) < 2:
    pr_auc = float("nan")
else:
    pr_auc = float(average_precision_score(y_scored, scores_eval))

training_start = time.perf_counter()
z_train = encode_batches(model, x_train, train_params)
z_train = F.normalize(z_train, dim=1)

train_loss = 0.0
training_time_sec = float(time.perf_counter() - training_start)

# Threshold is 0 — argmax boundary (Eq. 16), no calibration needed
best_threshold = 0.0
pred = (anomaly_scores[valid_mask] > best_threshold).astype(int)
precision, recall, f1, _ = precision_recall_fscore_support(
    y_test[valid_mask], pred, average='binary', zero_division=0)

y_eval = y_test[valid_mask]
query_normal = int((y_eval == 0).sum())
query_abnormal = int((y_eval == 1).sum())
support_normal = last_support_norm
support_abnormal = last_support_anom

with open(f'result/test_{suffix}_{run_name}.txt', 'a', encoding='utf-8') as f:
    f.write(f'Source train normals/anoms: '
            f'{source_norm if source_norm is not None else "NA"}/'
            f'{source_anom if source_anom is not None else "NA"}\n')
    f.write(f'Target test normals/anoms: {(y_test == 0).sum()}/{(y_test == 1).sum()}\n')
    f.write(f'Support normals/anoms (last episode): {last_support_norm}/{last_support_anom}\n')
    f.write(f'Query normals/anoms (last episode): {last_query_norm}/{last_query_anom}\n')
    f.write(f'Support normal/abnormal (CSV): {support_normal}/{support_abnormal}\n')
    f.write(f'Query normal/abnormal in eval set (CSV): {query_normal}/{query_abnormal}\n')
    f.write(f'Episodes: {args.episodes}\n')
    f.write(f'Number of support samples (last episode): {len(last_support_idx)}\n')
    f.write(f'Number of scored query samples: {int(valid_mask.sum())}\n')
    f.write(f'Train loss (mean score): {train_loss:.6f}\n')
    f.write(f'Best threshold: {best_threshold:.6f}\n')
    f.write(f'Training time (s): {training_time_sec:.6f}\n')
    f.write(f'Testing time (s): {testing_time_sec:.6f}\n')
    f.write(f'Precision: {precision:.6f}\n')
    f.write(f'Recall: {recall:.6f}\n')
    f.write(f'F1: {f1:.6f}\n')
    f.write(f'AUC: {auc:.6f}\n')
    f.write(f'PR-AUC: {pr_auc:.6f}\n')

print(f'Source train normals/anoms: '
      f'{source_norm if source_norm is not None else "NA"}/'
      f'{source_anom if source_anom is not None else "NA"}')
print(f'Target test normals/anoms: {(y_test == 0).sum()}/{(y_test == 1).sum()}')
print(f'Support normals/anoms (last episode): {last_support_norm}/{last_support_anom}')
print(f'Query normals/anoms (last episode): {last_query_norm}/{last_query_anom}')
print(f'Support normal/abnormal (CSV): {support_normal}/{support_abnormal}')
print(f'Query normal/abnormal in eval set (CSV): {query_normal}/{query_abnormal}')
print(f'Episodes: {args.episodes}')
print(f'Number of support samples (last episode): {len(last_support_idx)}')
print(f'Number of scored query samples: {int(valid_mask.sum())}')
print(f'Train loss (mean score): {train_loss:.6f}')
print(f'Best threshold: {best_threshold:.6f}')
print(f'Training time (s): {training_time_sec:.6f}')
print(f'Testing time (s): {testing_time_sec:.6f}')
print(f'Precision: {precision:.6f}')
print(f'Recall: {recall:.6f}')
print(f'F1: {f1:.6f}')
print(f'AUC: {auc:.6f}')
print(f'PR-AUC: {pr_auc:.6f}')
if args.report_cuda_memory and torch.cuda.is_available():
    torch.cuda.synchronize()
    print(f'CUDA_peak_allocated_GB: {torch.cuda.max_memory_allocated() / (1024 ** 3):.4f}')
    print(f'CUDA_peak_reserved_GB: {torch.cuda.max_memory_reserved() / (1024 ** 3):.4f}')

csv_path = args.csv_path
if os.path.exists(csv_path):
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            header_line = f.readline().strip()
        if csv_path == 'result/experiments.csv' and (
                'n_support_train' in header_line or 'n_query_train' in header_line or
                'n_train' in header_line or 'disable_params' not in header_line):
            csv_path = 'result/experiments_v4.csv'
    except OSError:
        pass
ensure_experiment_csv_schema(csv_path, EXPERIMENT_CSV_FIELDS)
csv_exists = os.path.exists(csv_path)
slide_csv = str(args.slide_window) if args.slide_window > 0 else ''
with open(csv_path, 'a', encoding='utf-8', newline='') as csvfile:
    writer = csv.DictWriter(csvfile, fieldnames=EXPERIMENT_CSV_FIELDS)
    if not csv_exists:
        writer.writeheader()
    writer.writerow({
        'name': run_name,
        'source_domain': args.pretrained_log_name,
        'target_domain': args.log_name,
        'num_layers': args.num_layers,
        'param_dim': args.param_dim,
        'window_size': args.window_size,
        'slide_window': slide_csv,
        'method': args.method,
        'support_size': args.support_size,
        'disable_params': int(args.disable_params),
        'n_support_test': len(last_support_idx),
        'n_query_test': int(valid_mask.sum()),
        'n_test': len(x_test),
        'support_normal': support_normal,
        'support_abnormal': support_abnormal,
        'query_normal': query_normal,
        'query_abnormal': query_abnormal,
        'train_loss': f'{train_loss:.6f}',
        'training_time_sec': f'{training_time_sec:.6f}',
        'testing_time_sec': f'{testing_time_sec:.6f}',
        'auc': f'{auc:.6f}',
        'pr_auc': f'{pr_auc:.6f}' if not np.isnan(pr_auc) else '',
        'f1': f'{f1:.6f}',
        'precision': f'{precision:.6f}',
        'recall': f'{recall:.6f}',
        'best_threshold': f'{best_threshold:.6f}',
        'load_path': args.load_path,
    })

if args.viz == 1:
    plot_dir = 'result/plots'
    os.makedirs(plot_dir, exist_ok=True)
    s_norm_idx, s_anom_idx = sample_query_indices(y_test, args.viz_samples, args.seed)
    viz_idx = np.concatenate([s_norm_idx, s_anom_idx])
    y_viz = y_test[viz_idx]
    x_viz = x_test[viz_idx]
    p_viz = None if p_key_test is None else (
        p_key_test[viz_idx], p_type_test[viz_idx], p_val_test[viz_idx], p_num_test[viz_idx])

    model_before = Model(num_layers=args.num_layers, max_params=max_params, key_vocab_size=key_vocab_size,
                         char_vocab_size=char_vocab_size, max_chars=max_chars, dim=EMBEDDING_DIM,
                         window_size=args.window_size, nhead=8, dim_feedforward=4 * EMBEDDING_DIM,
                         dropout=0.1, use_rope=not args.disable_rope)
    model_before = model_before.to(device)
    model_before.eval()
    viz_support_idx = last_support_idx if last_support_idx is not None else normal_idx_test
    x_support_viz = x_test[viz_support_idx]
    if args.disable_params or p_key_test is None:
        p_support_viz = None
    else:
        p_support_viz = (p_key_test[viz_support_idx], p_type_test[viz_support_idx],
                         p_val_test[viz_support_idx], p_num_test[viz_support_idx])

    z_support_before = encode_batches(model_before, x_support_viz, p_support_viz)
    z_query_before = encode_batches(model_before, x_viz, p_viz)
    z_support_before = F.normalize(z_support_before, dim=1)
    z_query_before = F.normalize(z_query_before, dim=1)

    z_support_after = last_z_support if last_z_support is not None else z_support_before
    z_query_after = encode_batches(model, x_viz, p_viz)
    z_support_after = F.normalize(z_support_after, dim=1)
    z_query_after = F.normalize(z_query_after, dim=1)

    attack_lmap = _load_attack_label_map(args.log_name) if y_fine_test is not None else {}
    y_viz_fine = y_fine_test[viz_idx] if y_fine_test is not None else None
    y_sup_fine = (
        y_fine_test[viz_support_idx] if y_fine_test is not None else None
    )
    plot_slug = f'{run_name}_{args.pretrained_log_name}_to_{args.log_name}'
    plot_embeddings(
        z_support_before, z_query_before, y_viz,
        f'Embedding Before ({args.pretrained_log_name}→{args.log_name}) {run_name}',
        os.path.join(plot_dir, f'{plot_slug}_before.png'),
        y_fine_support=y_sup_fine,
        y_fine_query=y_viz_fine,
        id_to_label=attack_lmap,
    )
    plot_embeddings(
        z_support_after, z_query_after, y_viz,
        f'Embedding After ({args.pretrained_log_name}→{args.log_name}) {run_name}',
        os.path.join(plot_dir, f'{plot_slug}_after.png'),
        y_fine_support=y_sup_fine,
        y_fine_query=y_viz_fine,
        id_to_label=attack_lmap,
    )
