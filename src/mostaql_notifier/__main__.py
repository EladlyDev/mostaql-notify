"""Entrypoint: `python -m mostaql_notifier` (or the `mostaql-notifier` console script)."""
from __future__ import annotations

import asyncio

from .worker.main import main


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
