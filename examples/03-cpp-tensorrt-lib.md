---
id: 03-cpp-tensorrt-lib
title: Productionize the detector as a C/C++ TensorRT library
type: build
agent: cloud
gpu: required
priority: 30
deploy_target: jetson
depends_on: [02-automl-hpo]
notify: {on_done: email, on_question: whatsapp, on_fail: email}
---
# Goal
Wrap the chosen model in a clean C/C++ inference library for the Jetson target.

# Approach (proposed — challenge it)
- Export the trained model -> **ONNX** -> build a **TensorRT** engine
  (FP16, and INT8 with a calibration set). NCNN as a CPU/Vulkan fallback.
- C API: `detector_create(engine_path) / detector_infer(img) -> boxes / detector_destroy`.
- Own the pre/post-processing in C++: letterbox resize, NMS, class/score decode.
  These are where parity bugs hide — test them against the Python reference.

# Acceptance criteria
- A static/shared lib + minimal C example that loads an image and prints boxes.
- Numerical parity test vs the Python model (same boxes within tolerance).
- Measured latency on the target at FP16 and INT8.

# Constraints
- Build artifacts target the Jetson's TensorRT/CUDA versions; document them.
