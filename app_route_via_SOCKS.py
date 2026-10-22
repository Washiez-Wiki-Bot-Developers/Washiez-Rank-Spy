# Copyright (c) 2023 Rankspy (Washiez Variant) by Washiez Wiki Bot Developers,
# based on original work from MartinAstrea. Made with 🧼🫧 by WW:BD, Martin and MrT!
# Licensed under MIT License until further revision.
# This is a file to execute app.py but injecting custom proxies.
import os
import time
import sys
import asyncio
import aiohttp
import logging
import dotenv
from app import *

from app import TIME_TRACKING_CHANNEL_ID

# Preserve original ClientSession so we can return a real session instance
_original_ClientSession = aiohttp.ClientSession

# Read proxy URL from env var (set e.g. SOCKS_PROXY_URL=socks5://127.0.0.1:9050)
PROXY_URL = os.getenv("SOCKS_PROXY_URL", "").strip() or None

import logging_setup

MAX_EMBED_DESC = 1024  # Discord embed field character limit

# Set up logger
logger_proxy: logging.Logger = logging_setup.setup_logging(
    name=__name__, rankspy_default_level=True, bot=bot, error_channel_id=TIME_TRACKING_CHANNEL_ID
)


def _create_http_session(*args, **kwargs):
    """
    Factory that injects a ProxyConnector when creating a ClientSession.
    Connector creation is done lazily here (not at import time) to avoid
    'no running event loop' errors.
    """
    # If caller supplied a connector explicitly, respect it
    if "connector" in kwargs or not PROXY_URL:
        return _original_ClientSession(*args, **kwargs)

    try:
        # import here so it only runs when we actually create a session
        from aiohttp_socks import ProxyConnector

        # Try to create the connector. This is expected to run inside an event loop
        # in normal usage; if there is no running loop, ProxyConnector.from_url
        # may raise RuntimeError — catch and fallback gracefully.
        try:
            connector = ProxyConnector.from_url(PROXY_URL)
            kwargs["connector"] = connector
            logger_proxy.info("Using SOCKS proxy for HTTP requests: %s", PROXY_URL)
        except RuntimeError:
            # No running loop right now; skip injecting connector and log debug.
            logger_proxy.debug(
                "No running event loop when creating ProxyConnector, "
                "creating session without connector. Connector will be created later when session is built under a running loop."
            )
        except Exception as e:
            logger_proxy.error("Failed to create ProxyConnector from %s: %s", PROXY_URL, e)
    except ImportError:
        logger_proxy.warning("aiohttp_socks not installed; using plain ClientSession.")
    except Exception as e:
        logger_proxy.error("Unexpected error while preparing SOCKS connector: %s", e)

    return _original_ClientSession(*args, **kwargs)


# Monkeypatch aiohttp.ClientSession to return a session with the proxy connector when possible
aiohttp.ClientSession = _create_http_session


CF_TRACE = "https://speed.cloudflare.com/cdn-cgi/trace"
CF_DOWNLOAD = "https://speed.cloudflare.com/__down?bytes=10000000"  # 10 MB


async def run_speed_test():
    logger_proxy.info("Running Cloudflare network speed test...")

    try:
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            # ---- Latency test ----
            start = time.perf_counter()
            async with session.get(CF_TRACE) as resp:
                await resp.text()
            latency_ms = (time.perf_counter() - start) * 1000

            # ---- Download speed test ----
            start = time.perf_counter()
            bytes_downloaded = 0

            async with session.get(CF_DOWNLOAD) as resp:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    bytes_downloaded += len(chunk)

            elapsed = time.perf_counter() - start
            speed_mbps = (bytes_downloaded * 8) / (elapsed * 1_000_000)

            logger_proxy.info(
                "Cloudflare speed test — Latency: %.1f ms | Download: %.2f Mbps",
                latency_ms,
                speed_mbps,
            )

    except Exception as e:
        logger_proxy.warning("Cloudflare speed test failed: %s", e)


TOKEN = os.getenv("DISCORD_BOT_TOKEN")

if __name__ == "__main__":
    # Explicit loop creation (REQUIRED on Windows / Py 3.12+)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    if TOKEN is None:
        logger_proxy.error("DISCORD_BOT_TOKEN not set in .env file.")
        sys.exit(1)

    # Run speed test BEFORE Discord starts
    loop.run_until_complete(run_speed_test())

    try:
        bot.load_extension("commands")  # This loads the commands from commands.py
    except Exception as e:
        logger.error(f"Failed to load commands extension: {e}")
        sys.exit(1)

    try:
        bot.run(TOKEN)
    except KeyboardInterrupt as e:
        logger_proxy.info("Exiting...")
    except Exception as e:
        logger_proxy.error(f"Error running bot: {e}")
