#!/usr/bin/env python3
"""
main.py — starts API server + background worker in the same process.
Use this for Railway deployment (single dyno).
"""

import asyncio
import logging
import os
import subprocess
import sys
import threading

logger = logging.getLogger(__name__)


def start_api():
    """Run uvicorn in a subprocess."""
    port = os.getenv("PORT", "8000")
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "api:app",
        "--host", "0.0.0.0",
        "--port", port,
        "--log-level", "info",
        "--app-dir", os.path.join(os.path.dirname(__file__)),
    ])


async def start_worker():
    from worker import main as worker_main
    await worker_main()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # API in background thread
    api_thread = threading.Thread(target=start_api, daemon=True)
    api_thread.start()

    logger.info("API thread started, launching worker...")

    # Worker in main thread (async)
    asyncio.run(start_worker())


if __name__ == "__main__":
    main()
