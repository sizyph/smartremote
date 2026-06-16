# Architecture

```
you@Mac ──sftp (staging → rename)──▶ inbox/
                                       │
                          dispatcher (systemd, DUMB & deterministic)
                          parse frontmatter · route · hold GPU lock
                                       │
              jobs/<id>/  request.md · workspace/ · artifacts/ · logs/ · status.json
                                       │
                    runner ── cloud (Claude Code/Codex): writes plan.md ─┐
                           └─ local (4090 LLM): executes the plan  ◀──────┘
                                       │
                    needs a decision?  ┴─ serialize state · release GPU · park
                                       │
        Hermes gateway ◀── question (WhatsApp) · completion (email) ──▶ you
                     └── your reply ──▶ answers/ ──▶ dispatcher unparks & resumes
```

## Principles
1. **The dispatcher is dumb.** It is plumbing: watch, validate, route, supervise.
   No model calls. All intelligence lives inside a *runner*, so failures are
   reproducible and the queue can't "go rogue".
2. **Atomic arrival.** Files are published by upload-to-`.part`-then-`rename`, so
   the watcher never reads a half-transferred job. (Swap SFTP for a git-repo queue
   later if you want history/rollback.)
3. **Cloud plans, local executes.** The handoff artifact is `artifacts/plan.md`.
   Offline, only jobs whose plan already exists can run.
4. **Questions are checkpoints, not blocking calls.** On a decision the runner
   serializes its state, releases the GPU, and parks; your answer resumes it.
   This is the one mechanic everything else depends on — job state must be
   serializable. See `runners/__init__.py::RunContext.ask`.

## Hardware constraints baked in
- **One RTX 4090 / 24 GB** → `gpu: required` jobs serialize behind `gpu.lock`;
  `gpu: none` jobs (research, data prep) run in parallel up to a configured cap.
- The **local agent LLM competes with training for VRAM** → keep it small
  (7–8B ≈ 6 GB) or run it on CPU, and release it before heavy training.
- **CUDA 13.2 is new** → prefer Ultralytics over darknet (keeps up with toolchains).

## Crash recovery
On startup the dispatcher requeues any job left in `running` and releases a stale
GPU lock (`Dispatcher.recover`). Because checkpoints + answers live on disk, a
parked job survives a full restart.

## What's real vs stubbed (v0.1)
| Component | State |
|---|---|
| Job contract, validation | real |
| Dispatcher, scheduling, GPU lock | real |
| Park/resume state machine | real (see `selftest`) |
| Crash recovery | real |
| Console notifier | real |
| Hermes notifier | real HTTP client; **point it at your gateway** |
| Hermes **inbound** (WhatsApp reply → `answers/`) | **TODO**: a small webhook |
| Cloud runner (Claude/Codex) | **stub** with real control flow |
| Local runner (4090 model) | **stub** |
| autoresearch / Optuna inner loop | **not yet** (job 02) |
