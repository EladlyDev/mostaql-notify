"""Read-only analytics aggregation over Features 1–4 data (Feature 6).

A surface-agnostic, **strictly read-only** package: it aggregates already-collected rows
(projects, scores, snapshots, personal records) into the dashboard analytics section's charts and
rule-based tips. It scrapes nothing, takes no action on Mostaql, and writes nothing back to any
project, score, snapshot, outcome, or personal record (constitution IV/VIII). Every threshold and
the analytics timezone are ``settings`` rows (constitution III); each section is honest about thin
data via an ``enough_data`` flag and tips are withheld below their configured minimum support.
"""
