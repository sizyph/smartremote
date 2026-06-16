# Job file format

A job is a Markdown file: a YAML **frontmatter** block (the machine-readable
routing contract) followed by the **body** (instructions for the agent).

```markdown
---
id: 02-automl-hpo            # required; [a-z0-9._-], unique. Defaults to filename.
title: Human-readable title  # optional
type: train|research|build|pipeline   # required
agent: cloud|local           # required. cloud = needs internet (Claude/Codex);
                             #           local = offline executor on the 4090.
gpu: required|none           # required. `required` serializes behind the GPU lock.
priority: 10                 # optional, lower runs first (default 100)
needs_human: true            # optional hint that the job may post questions
deploy_target: jetson|server|arm|mcu|none   # drives the productionization runtime
depends_on: [other-job-id]   # optional; job stays `blocked` until deps are `done`
notify:                      # optional; per-event channel
  on_done: email
  on_question: whatsapp
  on_fail: email
budget:                      # optional, advisory
  wallclock_hours: 24
  tokens: 200000
---
# Goal
...
## Acceptance criteria
...
## Constraints / Inputs
...
```

## Routing
- `type: research` or `agent: cloud` → the **cloud** runner (planner / web).
- `agent: local` → the **local** runner (executes an existing `artifacts/plan.md`).
- otherwise → the demo runner.

## Lifecycle
`received → queued` (or `blocked` if it has unmet `depends_on`) `→ running →`
either `done`, `failed`, or `waiting_human`. A `waiting_human` job returns to
`queued` automatically once its pending answer file exists, then resumes.

## Human checkpoints
A runner calls `ctx.ask(qid, prompt, choices)`. If unanswered, the job **parks**
(releases the GPU, notifies via `on_question`). You answer with
`smartremote answer <job-id> <qid> "<text>"` (or via the Hermes inbound webhook),
and the dispatcher resumes the job. Keep work done *before* an `ask()` idempotent —
the runner replays from the top on resume.
