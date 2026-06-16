# SmartRemote

[![ci](https://github.com/sizyph/smartremote/actions/workflows/ci.yml/badge.svg)](https://github.com/sizyph/smartremote/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Send a Markdown **job file** to a GPU server over SFTP; a dumb, deterministic
dispatcher ingests it, runs it in an isolated workspace, serializes GPU work
behind a lock, and bridges human decisions to WhatsApp/email (via a
[Hermes Agent](https://hermes-agent.nousresearch.com) gateway) so jobs **park**
instead of block. Intelligence lives inside *runners* (a cloud planner —
Claude Code / Codex; a local executor on the GPU); the orchestrator makes no
model calls itself.

Reference target box: 1× RTX 4090 (24 GB), i7-13700, 96 GB RAM, Ubuntu, CUDA 13.2
([docs/hardware.txt](docs/hardware.txt)).

```
inbox/ ─▶ dispatcher ─▶ jobs/<id>/{request.md, workspace, artifacts, logs, status.json}
                          │                    │
                          ├─ cloud runner: plan ┘ (Claude/Codex)
                          ├─ local runner: execute plan (offline, GPU)
                          └─ park on a question ─▶ Hermes ─▶ WhatsApp/email ─▶ you
```

See [docs/architecture.md](docs/architecture.md) and [docs/job-format.md](docs/job-format.md).

## Install

```bash
# From source (provides the `smartremote` command):
git clone https://github.com/sizyph/smartremote.git && cd smartremote
pip install -e .
```

### Debian / Ubuntu (APT repo on GitHub Pages)

```bash
echo 'deb [trusted=yes] https://sizyph.github.io/smartremote stable main' \
  | sudo tee /etc/apt/sources.list.d/smartremote.list
sudo apt-get update && sudo apt-get install smartremote
```

> Unsigned for now (hence `[trusted=yes]`); built and published by
> [`publish-apt.yml`](.github/workflows/publish-apt.yml) on every `v*` tag.

## Quickstart (no server needed)

```bash
# Prove the park/resume cycle end to end (runs in a temp dir, cleans up):
smartremote selftest                       # or: python3 -m smartremote.cli selftest

# Drive it by hand against this checkout as the root:
smartremote run &                          # start the dispatcher
smartremote submit examples/04-slam-research.md
smartremote status                         # watch states
# when a job parks with a question:
smartremote status 01-annotate-bootstrap-yolo      # see pending_question
smartremote answer 01-annotate-bootstrap-yolo approve-plan "approve"
```

The default notifier prints to the dispatcher's stdout — no Hermes needed to
develop. Set `hermes.enabled: true` in `config.yaml` (copy `config.example.yaml`)
to send for real.

## Deploy to the server

```bash
rsync -av --exclude jobs/ --exclude inbox/ --exclude .git/ \
  ./ user@host:~/SmartRemote/
ssh user@host 'cd ~/SmartRemote && pip install -e .'
# edit systemd/smartremote.service (User + paths), then:
ssh user@host 'sudo cp ~/SmartRemote/systemd/smartremote.service /etc/systemd/system/ \
  && sudo systemctl enable --now smartremote'
```

Submit jobs from your laptop (atomic upload — the dispatcher never reads a
half-transferred file):

```bash
scripts/submit.sh user@host:~/SmartRemote/inbox examples/04-slam-research.md
```

## Layout

```
smartremote/      dispatcher package (job contract, scheduler, GPU lock, runners)
examples/         the four reference jobs, written to the contract
docs/             architecture.md · job-format.md · hardware.txt
tests/            smoke tests (park/resume + scheduler invariants)
debian/           Debian packaging (dh-python/pybuild) for the .deb
systemd/          example service unit
scripts/          atomic SFTP submit helper
.github/          CI (test + .deb build)
```

## Status — v0.1

The contract, dispatcher, scheduling, GPU lock, park/resume, and crash recovery
are **real and tested**. The cloud/local runners are **stubs** with the real
control flow wired in (replacing them with a Claude Code / Codex call and a local
model is the next step). The Hermes **inbound** path (WhatsApp reply → `answers/`)
is a small webhook still to be written. See the table in
[docs/architecture.md](docs/architecture.md).

## License

[MIT](LICENSE) © 2026 Sizyph
