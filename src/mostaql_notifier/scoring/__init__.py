"""Opportunity scoring (Feature 4).

Surface-agnostic scoring used by the API, the worker re-check loop, and the bot alike. The
constitution-critical seam is the **pure** :mod:`model` (six weighted components → a 0–100 score +
an explainable breakdown, every constant a ``settings`` key) and the **pure** :mod:`freshness`
deriver (green/yellow/red "still good?" signal). :mod:`service` persists the latest score/breakdown,
runs the backfill, answers "Why?"/``/top``, and is the single entry point every surface calls so the
number agrees everywhere.
"""
