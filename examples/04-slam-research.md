---
id: 04-slam-research
title: Survey SLAM with loop closure for elastic/deformable, landmark-poor settings
type: research
agent: cloud
gpu: none
priority: 5
deploy_target: none
notify: {on_done: email, on_fail: email}
---
# Goal
A cited, structured report on the latest research and best practices for building
SLAM systems that (a) handle an **elastic / deformable (non-rigid)** model and
(b) achieve robust **loop closure** when **landmarks are limited** (feature-poor
scenes).

# Questions to answer
- State of the art in non-rigid / deformable SLAM (ElasticFusion lineage,
  deformation graphs, and what has superseded them).
- Loop-closure / place-recognition techniques that survive few, repetitive, or
  low-texture features; learned descriptors vs classical BoW.
- Practical pipelines, open-source implementations, datasets, and failure modes.
- Concrete recommendations for our case, with trade-offs.

# Acceptance criteria
- Markdown report with inline citations (links) and a short "what I'd do" section.
- This is a research job: no GPU, internet required; route to the cloud agent.

# Notes
This is the job type that needs no server compute — it validates the
research-job path of the system.
