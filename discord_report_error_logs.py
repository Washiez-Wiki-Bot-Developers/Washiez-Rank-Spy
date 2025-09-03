import logging
import asyncio
import discord
import logging
from typing import Union, Optional

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('DiscordErrorLogger')

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
        channel = self.bot.get_channel(self.channel_id)
        
        message_object = None
        if channel:
            try:
                message_object: Optional[discord.Message] = await channel.send(f"⚠️ **Error Log:**\n```{message}```")
            except discord.Forbidden:
                logging.error(
                    "Missing permissions to send error log to channel %s.",
                    self.channel_id,
                )
            except discord.HTTPException as e:
                logging.error(
                    "Failed to send error log to channel %s: %s", self.channel_id, e
                )
            except Exception as e: # pylint: disable=broad-exception-caught
                logging.exception(
                    "Unexpected error while sending error log to channel %s: %s",
                    self.channel_id,
                    e,
                )
            
            # if message_object:
            #     try:
            #         message_obj_result = await message_object.publish()
            #         if message_obj_result:
            #             logger.info(f"Published message: {message_obj_result.id}")
            #     except discord.Forbidden as e:
            #         logger.error(f"Failed to publish: {e}")
            #     except discord.HTTPException as e:
            #         logger.error(f"HTTP error during publish: {e}")
                

    def emit(self, record):
        if record.levelno == logging.ERROR:  # Only handle error logs
            log_entry = self.format(record)
            asyncio.create_task(
                self.send_error_to_channel(log_entry)
            )  # Schedule the task
