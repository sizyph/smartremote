---
id: 01-annotate-bootstrap-yolo
title: Bootstrap a tiny landmark detector + active-learning loop
type: train
agent: cloud
gpu: required
priority: 10
needs_human: true
deploy_target: jetson
notify: {on_done: email, on_question: whatsapp, on_fail: email}
budget: {wallclock_hours: 6}
---
# Goal
Train a small, deliberately-imperfect single-class landmark detector from ~50-100
hand-annotated images (plus negatives), then use it to pre-label frames extracted
from my videos/photos so I can grow a supervised dataset with far less manual work.

# Approach (proposed — challenge it)
- Annotate the seed set in **labelme** (rectangles), export, convert to YOLO txt.
- Train **Ultralytics YOLO11n** (not darknet YOLOv4-tiny): better small-data
  augmentation, one-line ONNX/TensorRT export later (feeds jobs 02/03).
- Active-learning loop: infer on extracted frames -> import predictions as
  pre-labels into CVAT/Label Studio -> I correct -> retrain. Surface only
  low-confidence / disagreement frames for my review.

# Acceptance criteria
- A trained `best.pt` + a held-out mAP number (honest, even if low).
- A repeatable script: video/photo -> frames -> model pre-labels -> review queue.
- A short note on what to annotate next to most improve the model.

# Human checkpoints (ask me on WhatsApp)
- Confirm the class definition / labeling guidelines before I annotate at scale.
- Approve each batch of auto-labels before they enter the training set.

# Inputs
- Seed images + my video/photo library paths (to be provided in workspace/).
