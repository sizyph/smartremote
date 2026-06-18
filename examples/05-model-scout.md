---
id: 05-model-scout
title: Scout + benchmark local models; promote the best executor
type: pipeline
runner: scout
agent: local
gpu: required
priority: 40
needs_human: true
notify: {on_done: email, on_question: whatsapp, on_fail: email}
---
# Goal
Benchmark the current executor (champion) against challenger models that fit the
24 GB GPU, and promote the winner — but only with my approval over WhatsApp.

Run this on a schedule (cron / systemd timer submitting the job) to keep the local
"executor" model current as new releases land. Use `smartremote models scout` to
discover fresh candidates, then paste their Ollama tags below.

## Challengers
- qwen3-coder:32b
- devstral:24b
- qwen3:30b-a3b
