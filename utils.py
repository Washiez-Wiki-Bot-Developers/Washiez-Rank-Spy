import discord
import asyncio
import logging
import os
from typing import Union, Optional

logger = logging.getLogger(__name__)


async def safe_send(
    message: str,
    channel_id: int,
    bot: Optional[discord.Client] = None,
    silent: bool = False,
    message_critical: bool = True,
):
    """
    Safely send a message to a channel with retries.

    - Retries indefinitely for connection/HTTP issues.
    - Retries up to 3 times for Forbidden errors.
    - Works in both discord.py and Pycord. (silent won't work in discord.py)
    
    :param message: The message content to send.
    :param channel_id: The ID of the channel to send the message to.
    :param bot: The discord.Client instance to use. If None, uses the globally set bot.
    :param silent: Whether to send the message silently (no notification).
    :param message_critical: If False, gives up after several attempts instead of retrying least three times.
    """    
    logging.debug(f"safe_send: Sending message to channel {channel_id}: {message}")
    
    if not bot or not bot.is_ready():
        return False, None

    channel = bot.get_channel(channel_id)
    if channel is None:
        logger.warning(f"safe_send: channel {channel_id} not found")
        return False, None

    try:
        msg = await channel.send(message, silent=silent)
        return True, msg
    except discord.Forbidden:
        logger.error(f"safe_send: forbidden in channel {channel_id}")
        return False, None
    except Exception:
        logger.exception("safe_send crashed")
        return False, None



def set_bot(bot: discord.Client) -> None:
    """Register the bot instance so utils can use it later."""
    global _bot
    _bot = bot


async def safe_publish(
    message_id: int,
    channel_id: Optional[int] = None,
    bot: Optional[discord.Client] = None,
    message_critical: bool = True,
) -> Optional[Union[discord.Message, bool]]:
    """
    Safely publish a message to a channel with retries.

    - Retries indefinitely for connection/HTTP issues.
    - Retries up to 3 times for Forbidden errors.
    - Works in both discord.py and Pycord.
    - Verifies that the message was actually published.
    """

    client = bot or globals().get("_bot")
    if client is None:
        raise RuntimeError("No bot available. Pass one explicitly or call set_bot(bot).")

    if channel_id is None:
        raise ValueError("Must provide channel_id.")

    channel = client.get_channel(channel_id)
    if channel is None:
        raise ValueError(f"Channel with ID {channel_id} not found.")

    forbidden_attempts = 0
    attempts = 0

    while True:
        try:
            message = await channel.fetch_message(message_id)

            if not hasattr(message, "publish"):
                raise ValueError("Provided channel does not support publishing messages.")

            published_message = await message.publish()

            # ✅ Verification step
            refreshed = await channel.fetch_message(message_id)
            if refreshed.flags.crossposted:
                return published_message  # Successfully published
            else:
                # If publish didn't set the flag, retry
                attempts += 1
                if not message_critical and attempts >= 5:
                    return False
                await asyncio.sleep(2)
                continue

        except (discord.Forbidden, ValueError) as e:
            forbidden_attempts += 1
            if str(os.getenv("ENVIRONMENT_MODE")) == "local_debug":
                return True
            if forbidden_attempts >= 3:
                return False
            await asyncio.sleep(2)
        except (discord.HTTPException, discord.ConnectionClosed, OSError):
            attempts += 1
            if not message_critical and attempts >= 5:
                return False
            await asyncio.sleep(2)
        except discord.errors.HTTPException as e:
            # discord.errors.HTTPException: 400 Bad Request (error code: 40033): This message has already been crossposted?
            if "This message has already been crossposted" in str(e):
                logger.info("safe_publish: Message already published. Returning True.")
                return True
            
        except Exception:
            attempts += 1
            if not message_critical and attempts >= 5:
                return False

async def safe_reaction(message: discord.Message, emoji: str, bot: Optional[discord.Client] = None):
    """
    Safely add a reaction to a message with retries.
    - Retries indefinitely for connection/HTTP issues.
    - Retries up to 3 times for Forbidden errors.
    - Works in both discord.py and Pycord.
    
    :param message: The message object to react to.
    :param emoji: The emoji to react with.
    :param bot: The discord.Client instance to use. If None, uses the globally set
    """
    forbidden_attempts = 0
    attempts = 0

    while True:
        try:
            await message.add_reaction(emoji)
            return True

        except discord.Forbidden:
            forbidden_attempts += 1
            if forbidden_attempts >= 3:
                return False
            await asyncio.sleep(2)

        except (discord.HTTPException, discord.ConnectionClosed, OSError) as e:
            # DO NOT retry Unknown Message
            if isinstance(e, discord.NotFound):
                logger.error("safe_reaction: message no longer exists (10008)")
                return False

            attempts += 1
            if attempts >= 5:
                return False
            await asyncio.sleep(2)

async def safe_send_and_pub(
    message: str, channel_id: int, bot: Optional[discord.Client] = None, silent: bool = False
):
    sent_status, message_obj = await safe_send(message=message, channel_id=channel_id, bot=bot, silent=silent)

    if not sent_status or message_obj is None:
        return False, None
    
    await safe_publish(getattr(message_obj, "id", None))

    return message_obj

async def safe_send_pub_react(
    message: str,
    channel_id: int,
    emoji: str,
    bot: Optional[discord.Client] = None,
    silent: bool = False,
):
    # message_obj = await safe_send_and_pub(message=message, channel_id=channel_id, bot=bot, silent=silent)

    # if message_obj is None:
    #     return False, None

    # await safe_reaction(channel=channel_id, message=message_obj, emoji=emoji, bot=bot)
    
    message_obj = await safe_send_react(message=message, channel_id=channel_id, emoji=emoji, bot=bot, silent=silent)
    await safe_publish(getattr(message_obj, "id", None), channel_id=channel_id, bot=bot)
    

    return message_obj

async def safe_send_react(
    message: str,
    channel_id: int,
    emoji: str,
    bot: Optional[discord.Client] = None,
    silent: bool = False,
):
    status, message_obj = await safe_send(message=message, channel_id=channel_id, bot=bot, silent=silent)

    if status is False or message_obj is None:
        return False, None

    await safe_reaction(channel=channel_id, message=(message_obj, channel_id), emoji=emoji, bot=bot)

    return message_obj