# MecoLog

MecoLog is a parameter-aware log anomaly detection pipeline. It parses raw logs with Drain, embeds log templates with Sentence-BERT, encodes extracted parameters, and runs supervised or episodic meta-learning experiments for cross-domain anomaly detection.

## Requirements

- Python 3.8+
- CUDA-capable GPU recommended for preprocessing and training
- Raw log files and labels for the datasets you want to use
- Python packages:
  - `numpy`
  - `pandas`
  - `torch`
  - `scikit-learn`
  - `sentence-transformers`
  - `tqdm`
  - `matplotlib`

## Installation

Create an environment and install the required packages:

```bash
python -m venv .venv
source .venv/bin/activate
pip install numpy pandas torch scikit-learn sentence-transformers tqdm matplotlib
```

Create the expected runtime directories:

```bash
mkdir -p log_data parse_result preprocessed_data checkpoints result
```

Place raw logs in `log_data/`. Some preprocessors also require dataset-specific label files, for example HDFS anomaly labels or OpenStack instance labels.

## Run

1. Parse raw logs with Drain. Edit `parse_log.py` to select the dataset log format, regex rules, and `log_file`, then run:

```bash
python parse_log.py
```

This produces parsed CSV files in `parse_result/`.

2. Preprocess parsed logs into model-ready arrays. Use the dataset-specific script:

```bash
python preprocess/preprocess_hdfs.py
python preprocess/preprocess_openstack.py
python preprocess/preprocess_bgl.py
python preprocess/preprocess_thunderbird.py --parse_result_dir parse_result --preprocessed_dir preprocessed_data
```

Run only the script for the dataset you are preparing. The generated files should be named `<log_name>_training.npz` and `<log_name>_testing.npz` under `preprocessed_data/` for the training and evaluation entrypoints.

3. Meta-train on a source domain:

```bash
python meta_train.py --log_name BGL --episodes 2000 --window_size 20
```

Defaults are defined in `config.py` and can be overridden with CLI arguments.

4. Evaluate or meta-test on a target domain:

```bash
python meta_test.py \
  --pretrained_log_name BGL \
  --load_path checkpoints/<meta-checkpoint>-latest.pt \
  --log_name HDFS \
  --window_size 50 \
  --episodes 1
```

Supervised baseline scripts are available in `baseline/`.

## Input and Output

### Input

- `log_data/<dataset>.log`: raw log file.
- `parse_result/<dataset>.log_structured.csv`: Drain-parsed structured logs.
- `parse_result/<dataset>.log_templates.csv`: Drain template table.
- Dataset labels, where required by the preprocessor.
- `preprocessed_data/<dataset>_training.npz` and `preprocessed_data/<dataset>_testing.npz`: preprocessed arrays consumed by training and evaluation.

Each `.npz` file contains:

- `x`: template embedding sequences.
- `y`: one-hot anomaly labels.
- `p_key`, `p_type`, `p_val`, `p_num`: encoded parameter features.
- `key_vocab_size`, `char_vocab_size`, `max_params`, `max_chars`: metadata used to build the parameter encoder.

### Output

- `parse_result/`: parsed structured logs and template CSVs.
- `preprocessed_data/`: model-ready `.npz` files and parameter vocabulary metadata.
- `checkpoints/`: trained model checkpoints, such as `meta_<run>-latest.pt`.
- `result/`: run logs, loss curves, evaluation metrics, CSV summaries, and optional plots.
