import logging
import asyncio
import discord

class DiscordErrorHandler(logging.Handler):
    """Custom logging handler to send error logs to a Discord channel."""
    def __init__(self, bot, channel_id):
        super().__init__()
        self.bot = bot
        self.channel_id = channel_id

    async def send_error_to_channel(self, message):
        channel = self.bot.get_channel(self.channel_id)
        if channel:
            try:
                await channel.send(f"⚠️ **Error Log:**\n```{message}```")
            except discord.Forbidden:
                logging.error(f"Missing permissions to send error log to channel {self.channel_id}.")
            except discord.HTTPException as e:
                logging.error(f"Failed to send error log to channel {self.channel_id}: {e}")
            except Exception as e:
                logging.exception(f"Unexpected error while sending error log to channel {self.channel_id}:")

    def emit(self, record):
        if record.levelno == logging.ERROR:  # Only handle error logs
            log_entry = self.format(record)
            asyncio.create_task(self.send_error_to_channel(log_entry))  # Schedule the task