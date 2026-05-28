import logging
import asyncio
import threading
import discord
import logging
from typing import Union, Optional
# import dotenv
from utils import safe_send

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("DiscordErrorLogger")

# ? Normal Text Log file logging
file_handler = logging.FileHandler("bot.log", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)  # ? Set to DEBUG to capture all logs
logger.addHandler(file_handler)


class DiscordErrorHandler(logging.Handler):
    """Custom logging handler to send error logs to a Discord channel."""

    def __init__(self, bot, channel_id):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id

    async def send_error_to_channel(self, message):
        """This function sends the error message to the specified Discord channel."""

        try:
            await safe_send(message, bot=self.bot, channel_id=self.channel_id)
        except Exception as e:
            logger.warning(f"Failed to send error log to Discord channel: {e}")

    def emit(self, record):
        if record.levelno == logging.ERROR:  # Only handle error logs
            log_entry = self.format(record)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            coro = self.send_error_to_channel(log_entry)

            # If an event loop is running in this thread, schedule the task normally
            if loop is not None and loop.is_running():
                loop.create_task(coro)
                return

            # If the bot exposes its loop and it's running in another thread, use run_coroutine_threadsafe
            bot_loop = getattr(self.bot, "loop", None)
            if bot_loop is not None and getattr(bot_loop, "is_running", lambda: False)():
                try:
                    asyncio.run_coroutine_threadsafe(coro, bot_loop)
                    return
                except Exception:
                    pass

            # Fallback: run the coroutine in a new thread to avoid blocking
            def _run_in_thread():
                try:
                    asyncio.run(coro)
                except Exception:
                    pass

            threading.Thread(target=_run_in_thread, daemon=True).start()
