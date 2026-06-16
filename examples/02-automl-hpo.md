---
id: 02-automl-hpo
title: Select + tune the best small detector for the Jetson target
type: train
agent: cloud
gpu: required
priority: 20
deploy_target: jetson
depends_on: [01-annotate-bootstrap-yolo]
notify: {on_done: email, on_question: whatsapp, on_fail: email}
budget: {wallclock_hours: 24}
---
# Goal
Given the grown dataset from job 01, find the best detector that is accurate AND
cheap enough to run on the Jetson target — not just highest mAP.

# Approach (proposed — challenge it)
- Multi-objective search (**Optuna**, or Ultralytics `model.tune()` as a baseline):
  maximize mAP while minimizing **measured latency** and model size.
- Latency must be measured on the *target* runtime (TensorRT FP16/INT8), not just
  raw PyTorch on the 4090. If no Jetson is reachable, use a documented proxy and
  flag it.
- Optionally layer an autoresearch-style agent loop on top to propose *new* ideas
  (augmentation recipes, backbone tweaks), not only numeric sweeps.

# Acceptance criteria
- A Pareto table: candidate -> (mAP, latency ms, params/MB).
- A single recommended config with justification against the Jetson budget.
- Reproducible training command + locked hyperparameters.

# Constraints
- One RTX 4090 (24 GB) -> runs serialized behind the GPU lock; keep per-trial
  budget small so the search makes progress overnight.
