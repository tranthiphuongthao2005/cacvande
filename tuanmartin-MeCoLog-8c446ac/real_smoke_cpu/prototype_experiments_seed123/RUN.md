# Prototype experiments on HDFS development

Checkpoint BGL 100 episodes, train seed 123. Two CPU threads, window 50, threshold 0. Encode the 40 development support and 200 development query sequences once. Replay all 60 prior single-prototype runs before the experiment. Do not open the final NPZ files.

## Design

- Support seeds 1000–1019. Random support reuses the verified prior support IDs at 5 and 10 shots.
- Length-diverse Normal support sorts the 20 Normal records by length, breaking ties by locked pool order, splits the list into k contiguous strata and samples one per stratum. Anomaly support samples floor(k/2) sessions of length at most 4 and the remainder above 4. All choices sample without replacement and use only support metadata. Length-diverse selections at 5 and 10 shots are made separately.
- The factorial design evaluates single, length-two and KMeans-two prototypes on each selected support set. For length-two, the split is length at most 4 versus above 4. For KMeans-two, cluster normalized Anomaly support embeddings only, use K=2, random_state=123 and n_init=10. If fewer than two distinct embeddings are available, or either cluster has fewer than two points, fall back to one Anomaly prototype.
- Average unit support embeddings in each cluster and normalize the mean. Score equals maximum Anomaly cosine minus Normal cosine. Classify as Anomaly when score is strictly above zero. KMeans is an exploratory procedure on the frozen support vectors.
- Selection-only pairs compare length-diverse with random while using a single prototype. Prototype-only pairs hold support IDs fixed and compare against the corresponding single-prototype result. The 20 seeds reuse the checkpoint and query set.

## PowerShell

Run from the directory containing model.py, with a fresh destination.

```powershell
$env:OMP_NUM_THREADS = '2'
$env:MKL_NUM_THREADS = '2'
.\.venv\Scripts\python.exe -B .\real_smoke_cpu\prototype_experiments.py `
  .\real_smoke_cpu\prototype_experiments_seed123_repeat
```

baseline_replay.json records replay and provenance checks. The CSV files contain selections, cluster membership, 240 experiment runs, 200 paired comparisons and 48,000 query predictions. experiment_summary.json records sample standard deviations, medians, ranges and 5th/95th percentiles. Grouping and scoring timings are small-batch CPU measurements, and scoring includes normalized centroid construction.
