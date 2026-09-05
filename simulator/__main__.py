"""Standalone entry: ``python -m simulator`` (Ctrl+C to stop)."""

import asyncio
import logging
import os

from simulator.runner import run_simulator


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),  # same convention as run.py
        format="%(levelname)s:%(name)s:%(message)s",
    )
    try:
        asyncio.run(run_simulator())
    except KeyboardInterrupt:
        logging.getLogger("app.simulator").info("Simulator stopped")


if __name__ == "__main__":
    main()
