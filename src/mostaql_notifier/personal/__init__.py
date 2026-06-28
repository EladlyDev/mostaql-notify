"""The owner's personal layer (Feature 3) — surface-agnostic.

Both the dashboard API and the inbound Telegram bot mutate the single personal record per project
*only* through :mod:`personal.service`, so "one record, consistent across surfaces" (FR-029,
SC-006) is guaranteed in one place. :mod:`personal.statuses` reads the config-driven status set and
:mod:`personal.stats` computes the shared `/stats` + `/health` + Home figures.
"""
