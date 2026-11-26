import argparse
import os
import random
import time
import warnings

import numpy as np
import torch
import torch.nn.functional as F
import torch.optim as optim
from sklearn.decomposition import PCA
from tqdm import tqdm

from config import get_params
from losses import (
    asymmetric_prototype_contrastive_loss,
    prototypical_contrastive_loss,
    supervised_contrastive_loss,
)
from model import Model

try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None


def sample_episode(x, y, p, k_norm, k_anom, m_query):
    normal_idx = np.where(y == 0)[0]
    anomaly_idx = np.where(y == 1)[0]

    s_norm = np.random.choice(normal_idx, size=k_norm, replace=len(normal_idx) < k_norm)
    s_anom = np.random.choice(anomaly_idx, size=k_anom, replace=len(anomaly_idx) < k_anom)

    remaining_norm = np.setdiff1d(normal_idx, s_norm)
    remaining_anom = np.setdiff1d(anomaly_idx, s_anom)

    # If support sampling (with replacement) covers all unique items in a class,
    # fall back to sampling query from the full class pool to keep episodes valid.
    query_norm_pool = remaining_norm if len(remaining_norm) > 0 else normal_idx
    query_anom_pool = remaining_anom if len(remaining_anom) > 0 else anomaly_idx
    q_norm = np.random.choice(query_norm_pool, size=m_query, replace=len(query_norm_pool) < m_query)
    q_anom = np.random.choice(query_anom_pool, size=m_query, replace=len(query_anom_pool) < m_query)

    support_idx = np.concatenate([s_norm, s_anom])
    query_idx = np.concatenate([q_norm, q_anom])

    xs = x[support_idx]
    ys = y[support_idx]
    xq = x[query_idx]
    yq = y[query_idx]

    if p is None:
        ps = None
        pq = None
    else:
        ps = (p[0][support_idx], p[1][support_idx], p[2][support_idx], p[3][support_idx])
        pq = (p[0][query_idx], p[1][query_idx], p[2][query_idx], p[3][query_idx])

    return xs, ys, ps, xq, yq, pq


def _pad_seq_2d(batch, window_size, width, dtype, fill_value=0):
    seqs = list(batch)
    out = np.full((len(seqs), window_size, width), fill_value, dtype=dtype)
    for j, s in enumerate(seqs):
        arr = np.asarray(s, dtype=dtype)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        arr = arr[:window_size, :width]
        out[j, :arr.shape[0], :arr.shape[1]] = arr
    return out


def _pad_seq_3d(batch, window_size, width1, width2, dtype, fill_value=0):
    seqs = list(batch)
    out = np.full((len(seqs), window_size, width1, width2), fill_value, dtype=dtype)
    for j, s in enumerate(seqs):
        arr = np.asarray(s, dtype=dtype)
        arr = arr[:window_size, :width1, :width2]
        out[j, :arr.shape[0], :arr.shape[1], :arr.shape[2]] = arr
    return out


def build_episode_embeddings(model, xs, ys, ps, xq, yq, pq, device, window_size, max_params, max_chars):
    if isinstance(xs, np.ndarray) and xs.dtype == object:
        xs_dim = np.asarray(xs[0]).shape[1] if np.asarray(xs[0]).ndim > 1 else 1
        xs_np = _pad_seq_2d(xs, window_size, xs_dim, np.float32, 0.0)
    else:
        xs_np = np.asarray(xs, dtype=np.float32)

    if isinstance(xq, np.ndarray) and xq.dtype == object:
        xq_dim = np.asarray(xq[0]).shape[1] if np.asarray(xq[0]).ndim > 1 else 1
        xq_np = _pad_seq_2d(xq, window_size, xq_dim, np.float32, 0.0)
    else:
        xq_np = np.asarray(xq, dtype=np.float32)

    xs = torch.tensor(xs_np, device=device, dtype=torch.float32)
    xq = torch.tensor(xq_np, device=device, dtype=torch.float32)
    ys = torch.tensor(ys, device=device, dtype=torch.long)
    yq = torch.tensor(yq, device=device, dtype=torch.long)
    if ps is not None:
        if isinstance(ps[0], np.ndarray) and ps[0].dtype == object:
            ps0 = _pad_seq_2d(ps[0], window_size, max_params, np.int64, 0)
            ps1 = _pad_seq_2d(ps[1], window_size, max_params, np.int64, 0)
            ps2 = _pad_seq_3d(ps[2], window_size, max_params, max_chars, np.int64, 0)
            ps3 = _pad_seq_2d(ps[3], window_size, max_params, np.float32, 0.0)
        else:
            ps0 = np.asarray(ps[0], dtype=np.int64)
            ps1 = np.asarray(ps[1], dtype=np.int64)
            ps2 = np.asarray(ps[2], dtype=np.int64)
            ps3 = np.asarray(ps[3], dtype=np.float32)

        if isinstance(pq[0], np.ndarray) and pq[0].dtype == object:
            pq0 = _pad_seq_2d(pq[0], window_size, max_params, np.int64, 0)
            pq1 = _pad_seq_2d(pq[1], window_size, max_params, np.int64, 0)
            pq2 = _pad_seq_3d(pq[2], window_size, max_params, max_chars, np.int64, 0)
            pq3 = _pad_seq_2d(pq[3], window_size, max_params, np.float32, 0.0)
        else:
            pq0 = np.asarray(pq[0], dtype=np.int64)
            pq1 = np.asarray(pq[1], dtype=np.int64)
            pq2 = np.asarray(pq[2], dtype=np.int64)
            pq3 = np.asarray(pq[3], dtype=np.float32)

        ps = (torch.tensor(ps0, device=device, dtype=torch.long),
              torch.tensor(ps1, device=device, dtype=torch.long),
              torch.tensor(ps2, device=device, dtype=torch.long),
              torch.tensor(ps3, device=device, dtype=torch.float32))
        pq = (torch.tensor(pq0, device=device, dtype=torch.long),
              torch.tensor(pq1, device=device, dtype=torch.long),
              torch.tensor(pq2, device=device, dtype=torch.long),
              torch.tensor(pq3, device=device, dtype=torch.float32))

    with torch.no_grad():
        z_s = model.encode(xs, ps)

    z_q = model.encode(xq, pq)

    return z_s, ys, z_q, yq


def encode_batches(model_ref, x, p, device, batch_size, window_size, max_params, max_chars):
    """Batch encoder for visualization (same layout as meta_test.encode_batches, no global args)."""
    embeddings = []
    for i in tqdm(range(0, len(x), batch_size), desc='encoding'):
        x_slice = x[i:i + batch_size]

        def _pad_seq_2d(batch, width, dtype, fill_value=0):
            seqs = list(batch)
            out = np.full((len(seqs), window_size, width), fill_value, dtype=dtype)
            for j, s in enumerate(seqs):
                arr = np.asarray(s, dtype=dtype)
                if arr.ndim == 1:
                    arr = arr.reshape(-1, 1)
                arr = arr[:window_size, :width]
                out[j, :arr.shape[0], :arr.shape[1]] = arr
            return out

        def _pad_seq_3d(batch, width1, width2, dtype, fill_value=0):
            seqs = list(batch)
            out = np.full((len(seqs), window_size, width1, width2), fill_value, dtype=dtype)
            for j, s in enumerate(seqs):
                arr = np.asarray(s, dtype=dtype)
                arr = arr[:window_size, :width1, :width2]
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
            p0_slice = p[0][i:i + batch_size]
            p1_slice = p[1][i:i + batch_size]
            p2_slice = p[2][i:i + batch_size]
            p3_slice = p[3][i:i + batch_size]

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


def sample_query_indices(y, max_samples, seed):
    rng = np.random.RandomState(seed)
    normal_idx = np.where(y == 0)[0]
    anom_idx = np.where(y == 1)[0]
    n_norm = min(len(normal_idx), max_samples)
    n_anom = min(len(anom_idx), max_samples)
    s_norm = rng.choice(normal_idx, size=n_norm, replace=False) if n_norm > 0 else np.array([], dtype=int)
    s_anom = rng.choice(anom_idx, size=n_anom, replace=False) if n_anom > 0 else np.array([], dtype=int)
    return s_norm, s_anom


def plot_normal_abnormal_embeddings(z, y, title, out_path):
    """PCA of CLS embeddings; one scatter: normal vs abnormal (training / source data)."""
    z_np = z.detach().cpu().numpy() if torch.is_tensor(z) else z
    y = np.asarray(y)
    pca = PCA(n_components=2)
    z_2d = pca.fit_transform(z_np)
    n_mask = y == 0
    a_mask = y == 1

    if plt is None:
        return
    plt.figure(figsize=(7, 6))
    if n_mask.any():
        plt.scatter(z_2d[n_mask, 0], z_2d[n_mask, 1],
                    c='tab:blue', s=6, alpha=0.5, label='normal')
    if a_mask.any():
        plt.scatter(z_2d[a_mask, 0], z_2d[a_mask, 1],
                    c='tab:red', s=6, alpha=0.5, label='abnormal')
    plt.title(title)
    plt.legend(loc='best', frameon=False)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
    plt.close()


def run_embedding_viz(
    args, device, run_name, timestamp,
    model_trained,
    train_path, plot_dir,
):
    """PCA scatter before vs after meta-training on a training-set subsample (source system)."""
    if plt is None:
        print('matplotlib not available; skipped embedding plots.')
        return
    data = np.load(train_path, allow_pickle=True)
    x_tr, y_tr = data['x'], data['y']
    p_key = data['p_key'] if 'p_key' in data else None
    p_type = data['p_type'] if 'p_type' in data else None
    p_val = data['p_val'] if 'p_val' in data else None
    p_num = data['p_num'] if 'p_num' in data else None
    key_vocab_size = int(data['key_vocab_size']) if 'key_vocab_size' in data else 2
    char_vocab_size = int(data['char_vocab_size']) if 'char_vocab_size' in data else 129
    max_params = int(data['max_params']) if 'max_params' in data else args.param_dim
    max_chars = int(data['max_chars']) if 'max_chars' in data else 16
    y_tr = np.argmax(y_tr, axis=1)

    s_norm_idx, s_anom_idx = sample_query_indices(y_tr, args.viz_samples, args.seed)
    viz_idx = np.concatenate([s_norm_idx, s_anom_idx])
    y_viz = y_tr[viz_idx]
    x_viz = x_tr[viz_idx]
    p_viz = None if p_key is None else (
        p_key[viz_idx], p_type[viz_idx], p_val[viz_idx], p_num[viz_idx])
    if args.disable_params:
        p_viz = None

    model_before = Model(
        num_layers=args.num_layers, max_params=max_params, key_vocab_size=key_vocab_size,
        char_vocab_size=char_vocab_size, max_chars=max_chars, dim=768,
        window_size=args.window_size, nhead=8, dim_feedforward=4 * 768, dropout=0.1,
        use_rope=not args.disable_rope)
    model_before = model_before.to(device)
    model_before.eval()
    model_trained.eval()

    enc_kw = dict(
        device=device, batch_size=args.batch_size, window_size=args.window_size,
        max_params=max_params, max_chars=max_chars)

    z_before = encode_batches(model_before, x_viz, p_viz, **enc_kw)
    z_after = encode_batches(model_trained, x_viz, p_viz, **enc_kw)
    z_before = F.normalize(z_before, dim=1)
    z_after = F.normalize(z_after, dim=1)

    stem = f'meta_{timestamp}_{args.log_name}_{args.num_layers}_{args.param_dim}_{args.lr}'
    if args.tag:
        stem += f'_{args.tag}'
    plot_normal_abnormal_embeddings(
        z_before, y_viz,
        f'Meta-train (train data) before - {run_name}',
        os.path.join(plot_dir, f'{stem}_before.png'))
    plot_normal_abnormal_embeddings(
        z_after, y_viz,
        f'Meta-train (train data) after - {run_name}',
        os.path.join(plot_dir, f'{stem}_after.png'))
    data.close()


def main():
    cfg = get_params()["meta_train"]
    parser = argparse.ArgumentParser()
    parser.add_argument('--log_name', type=str, default=cfg["log_name"])
    parser.add_argument('--window_size', type=int, default=cfg["window_size"])
    parser.add_argument('--num_layers', type=int, default=cfg["num_layers"])
    parser.add_argument('--param_dim', type=int, default=cfg["param_dim"],
                        help='max parameters per event')
    parser.add_argument('--lr', type=float, default=cfg["lr"])
    parser.add_argument('--episodes', type=int, default=cfg["episodes"])
    parser.add_argument('--k_norm', type=int, default=cfg["k_norm"])
    parser.add_argument('--k_anom', type=int, default=cfg["k_anom"])
    parser.add_argument('--m_query', type=int, default=cfg["m_query"])
    parser.add_argument('--temperature', type=float, default=cfg["temperature"])
    parser.add_argument('--seed', type=int, default=cfg["seed"])
    parser.add_argument('--disable_params', action='store_true',
                        help='disable parameter encoder inputs (template-only)')
    parser.add_argument('--disable_rope', action='store_true',
                        help='disable RoPE sequence encoding in transformer layers')
    parser.add_argument('--loss_type', type=str, default='apcl', choices=['apcl', 'proto', 'supcon'],
                        help='episodic training objective')
    parser.add_argument('--margin_scale', type=float, default=1.0,
                        help='scaling coefficient for APCL asymmetric margin delta')
    parser.add_argument('--margin_mode', type=str, default='adaptive', choices=['adaptive', 'fixed'],
                        help='APCL margin variant: adaptive uses margin_scale * ReLU(sim_norm); fixed uses fixed_margin')
    parser.add_argument('--fixed_margin', type=float, default=0.0,
                        help='constant APCL margin added to normal logit for anomaly queries when margin_mode=fixed')
    parser.add_argument('--tag', type=str, default='',
                        help='optional tag appended to run/checkpoint names')
    parser.add_argument('--preprocessed_dir', type=str, default='./preprocessed_data',
                        help='directory containing {log_name}_training.npz (and optional _testing.npz)')
    parser.add_argument('--viz', type=int, default=1,
                        help='1: PCA plots (normal vs abnormal) on training subsample; 0: skip')
    parser.add_argument('--viz_samples', type=int, default=1000,
                        help='max normal and max abnormal windows to plot per class')
    parser.add_argument('--batch_size', type=int, default=128,
                        help='batch size for embedding encoding')
    args = parser.parse_args()

    warnings.filterwarnings('ignore')
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    random.seed(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print('Using device = ', device)

    train_path = os.path.join(args.preprocessed_dir, f'{args.log_name}_training.npz')
    train_data = np.load(train_path, allow_pickle=True)
    if 'window_size' in train_data.files:
        ws_npz = int(train_data['window_size'])
        if ws_npz != args.window_size:
            warnings.warn(
                f'window_size in npz ({ws_npz}) != --window_size ({args.window_size}); '
                f'using CLI value. Prefer matching the preprocessed data.')
    x_train, y_train = train_data['x'], train_data['y']
    p_key = train_data['p_key'] if 'p_key' in train_data else None
    p_type = train_data['p_type'] if 'p_type' in train_data else None
    p_val = train_data['p_val'] if 'p_val' in train_data else None
    p_num = train_data['p_num'] if 'p_num' in train_data else None
    key_vocab_size = int(train_data['key_vocab_size']) if 'key_vocab_size' in train_data else 2
    char_vocab_size = int(train_data['char_vocab_size']) if 'char_vocab_size' in train_data else 129
    max_params = int(train_data['max_params']) if 'max_params' in train_data else args.param_dim
    max_chars = int(train_data['max_chars']) if 'max_chars' in train_data else 16
    y_train = np.argmax(y_train, axis=1)
    p_train = None if p_key is None else (p_key, p_type, p_val, p_num)

    model = Model(num_layers=args.num_layers, max_params=max_params, key_vocab_size=key_vocab_size,
                  char_vocab_size=char_vocab_size, max_chars=max_chars, dim=768,
                  window_size=args.window_size, nhead=8, dim_feedforward=4 * 768, dropout=0.1,
                  use_rope=not args.disable_rope)
    model = model.to(device)

    optimizer = optim.Adam(model.parameters(), lr=args.lr, weight_decay=0)

    run_name = f"{args.log_name}_meta_{args.num_layers}_{args.param_dim}_{args.lr}"
    if args.tag:
        run_name += f"_{args.tag}"
    timestamp = time.strftime("%m%d%H%M")
    os.makedirs('result', exist_ok=True)
    log_txt_path = f'result/meta_{run_name}.txt'
    loss_csv_path = f'result/meta_{run_name}_loss.csv'
    loss_png_path = f'result/meta_{run_name}_loss.png'
    loss_history = []

    model.train()
    start_time = time.time()
    for step in tqdm(range(1, args.episodes + 1)):
        xs, ys, ps, xq, yq, pq = sample_episode(
            x_train, y_train, p_train, args.k_norm, args.k_anom, args.m_query)
        if args.disable_params:
            ps = None
            pq = None

        z_s, y_s, z_q, y_q = build_episode_embeddings(
            model, xs, ys, ps, xq, yq, pq, device,
            args.window_size, max_params, max_chars)
        if args.loss_type == 'apcl':
            loss = asymmetric_prototype_contrastive_loss(
                z_s, y_s, z_q, y_q,
                temperature=args.temperature,
                margin_scale=args.margin_scale,
                margin_mode=args.margin_mode,
                fixed_margin=args.fixed_margin)
        elif args.loss_type == 'proto':
            loss = prototypical_contrastive_loss(
                z_s, y_s, z_q, y_q, temperature=args.temperature)
        else:
            loss = supervised_contrastive_loss(
                z_s, y_s, z_q, y_q, temperature=args.temperature)

        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
        optimizer.step()
        loss_history.append((step, float(loss.item())))

        if step % 500 == 0:
            with open(log_txt_path, 'a', encoding='utf-8') as f:
                f.write(f'{step}\t{loss.item():.6f}\t{time.time() - start_time:.2f}\n')
            start_time = time.time()

    with open(loss_csv_path, 'w', encoding='utf-8') as f:
        f.write('step,loss\n')
        for step, loss_val in loss_history:
            f.write(f'{step},{loss_val:.8f}\n')

    if plt is not None and loss_history:
        steps = [x[0] for x in loss_history]
        losses = [x[1] for x in loss_history]
        plt.figure(figsize=(8, 4))
        plt.plot(steps, losses, linewidth=1.5, color='tab:blue')
        plt.xlabel('Episode')
        plt.ylabel('APCL loss')
        plt.title('Meta-training loss curve')
        plt.grid(alpha=0.3, linestyle='--')
        plt.tight_layout()
        plt.savefig(loss_png_path, dpi=180)
        plt.close()
    elif plt is None:
        with open(log_txt_path, 'a', encoding='utf-8') as f:
            f.write('matplotlib not available; skipped loss curve PNG export.\n')

    ckpt_path = 'checkpoints/'
    os.makedirs(ckpt_path, exist_ok=True)
    ckpt_name = f"meta_{timestamp}_{args.log_name}_{args.num_layers}_{args.param_dim}_{args.lr}"
    if args.tag:
        ckpt_name += f"_{args.tag}"
    ckpt_name += "-latest.pt"
    torch.save({"net": model.state_dict(), "optimizer": optimizer.state_dict()},
               os.path.join(ckpt_path, ckpt_name))

    if args.viz == 1:
        train_viz_path = os.path.join(args.preprocessed_dir, f'{args.log_name}_training.npz')
        if not os.path.isfile(train_viz_path):
            print(f'Embedding viz skipped: missing {train_viz_path}')
        else:
            plot_dir = 'result/plots'
            os.makedirs(plot_dir, exist_ok=True)
            run_embedding_viz(
                args, device, run_name, timestamp, model, train_viz_path, plot_dir)


if __name__ == '__main__':
    main()
