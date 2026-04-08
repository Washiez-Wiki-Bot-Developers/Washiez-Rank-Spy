import discord
import asyncio
import logging
import os
from typing import Union, Optional
from datetime import datetime, timezone

ALL_RANKS: list[str] = []

logger = logging.getLogger(__name__)

async def safe_send(
    message: str,
    channel_id: int,
    bot: Optional[discord.Client] = None,
    silent: bool = False,
    message_critical: bool = True,
) -> Union[tuple[bool, Optional[discord.Message]], tuple[bool, None]]:
    """
    Safely send a message to a channel with retries.

    - Retries indefinitely for connection/HTTP issues.
    - Retries up to 3 times for Forbidden errors.
    - Works in both discord.py and Pycord. (silent won't work in discord.py)

    :param message: The message content to send.
    :param channel_id: The ID of the channel to send the message to.
    :param bot: The discord.Client instance to use. If None, uses the globally set bot.
    :param silent: Whether to send the message silently (no notification).
    :param message_critical: If False, gives up after several attempts instead of retrying indefinitely.
    
    :return: Tuple of (success status, message object or None)
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

    - Retries 3 times for connection/HTTP issues.
    - Retries up to 3 times for Forbidden errors.
    - Works in both discord.py and Pycord.
    - Verifies that the message was actually published via flags.

    :param message_id: The ID of the message to publish (crosspost).
    :param channel_id: The ID of the announcement channel.
    :param bot: The discord.Client instance to use.
    :param message_critical: If False, reduces the number of retry attempts.
    
    :return: The published message object, True if already published/debug mode, or False if failed.
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
            if not message_critical and attempts >= 1:
                return False

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
                await asyncio.sleep(2)
                continue

        except (discord.Forbidden, ValueError) as e:
            forbidden_attempts += 1
            if str(os.getenv("ENVIRONMENT_MODE")) == "local_debug":
                return True
            if forbidden_attempts >= 3:
                return False
            await asyncio.sleep(2)
        except discord.errors.HTTPException as e:
            # discord.errors.HTTPException: 400 Bad Request (error code: 40033): This message has already been crossposted?
            if "This message has already been crossposted" in str(e):
                logger.info("safe_publish: Message already published. Returning True.")
                return True
            attempts += 1.5
            pass
        except (discord.HTTPException, discord.ConnectionClosed, OSError):
            attempts += 1
            if not message_critical and attempts >= 5:
                return False
            await asyncio.sleep(2)
        except Exception:
            attempts += 1
            if not message_critical and attempts >= 5:
                return False


async def safe_reaction(message: discord.Message, emoji: str, bot: Optional[discord.Client] = None):
    """
    Safely add a reaction to a message with retries.
    
    - Retries up to 5 times for connection/HTTP issues.
    - Retries up to 3 times for Forbidden errors.
    - Aborts immediately if the message is not found (404).

    :param message: The discord.Message object to react to.
    :param emoji: The emoji string or object to react with.
    :param bot: The discord.Client instance to use.
    :return: True if successful, False otherwise.
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
) -> Optional[discord.Message]:
    """
    Safely send and then publish (crosspost) a message.

    :param message: The content of the message to send.
    :param channel_id: The ID of the channel to send and publish in.
    :param bot: The discord.Client instance to use. Defaults to None.
    :param silent: If True, sends the message without a notification. Defaults to False.

    :return: The message object if sending was successful, otherwise None.
    """
    sent_status, message_obj = await safe_send(
        message=message, channel_id=channel_id, bot=bot, silent=silent
    )

    if not sent_status or message_obj is None:
        return None

    await safe_publish(getattr(message_obj, "id", None), channel_id=channel_id, bot=bot)

    return message_obj


async def safe_send_pub_react(
    message: str,
    channel_id: int,
    emoji: str,
    bot: Optional[discord.Client] = None,
    silent: bool = False,
) -> Optional[discord.Message]:
    """
    Safely send, react to, and then publish a message.

    :param message: The content of the message to send.
    :param channel_id: The ID of the channel to send the message to.
    :param emoji: The emoji to react with.
    :param bot: The discord.Client instance to use. Defaults to None.
    :param silent: If True, sends the message silently. Defaults to False.

    :return: The message object if successful, otherwise None.
    """
    message_obj = await safe_send_react(
        message=message, channel_id=channel_id, emoji=emoji, bot=bot, silent=silent
    )
    
    if message_obj:
        await safe_publish(getattr(message_obj, "id", None), channel_id=channel_id, bot=bot)

    return message_obj


async def safe_send_react(
    message: str,
    channel_id: int,
    emoji: str,
    bot: Optional[discord.Client] = None,
    silent: bool = False,
) -> Optional[discord.Message]:
    """
    Safely send a message and add a reaction to it.
    
    :param message: The message content to send.
    :param channel_id: The ID of the channel to send the message to.
    :param emoji: The emoji to react with after sending.
    :param bot: The discord.Client instance. Defaults to None.
    :param silent: Whether the message should be silent. Defaults to False.

    :return: The message object if successful, otherwise None.
    """
    status, message_obj = await safe_send(
        message=message, channel_id=channel_id, bot=bot, silent=silent
    )

    if status is False or message_obj is None:
        return None

    await safe_reaction(message=message_obj, emoji=emoji, bot=bot)

    return message_obj


from discord import Embed, Color
from trello import parse_card, BOARD_NAME_MAP

MAX_FIELDS = 25  # Discord hard limit per embed


def build_board_embed(username, board_name, cards, color, icon=None):
    """
    Constructs a Discord Embed based on Trello board card data.

    :param username: The Trello/Roblox username associated with the data.
    :param board_name: The name of the Trello board.
    :param cards: A list of card objects from the Trello API.
    :param color: The discord.Color to use for the embed sidebar.
    :param icon: Optional URL for the author icon.
    
    :return: A discord.Embed object.
    """
    global ALL_RANKS

    try:
        embed = Embed(color=color)
        embed.set_author(name=f"Trello User Information: {board_name}", icon_url=icon)

        used_fields = 0
        leftovers = []

        if not ALL_RANKS:
            from app import ET_RANKS, MID_RANKS, HIGH_RANKS
            ALL_RANKS = ET_RANKS + MID_RANKS + HIGH_RANKS

        for card in cards:
            parsed = parse_card(card)

            for section, content in parsed.items():
                if section in ("Username", "Final Date", "Final Date Parsed"):
                    continue

                if isinstance(content, dict):
                    for rank, info in content.items():
                        if rank not in ALL_RANKS or used_fields >= MAX_FIELDS:
                            leftovers.append(f"{rank}: {info}")
                            continue

                        date = info.get("date", "Unknown")
                        embed.add_field(name=rank, value=date, inline=True)
                        used_fields += 1

                elif isinstance(content, list):
                    leftovers.extend(content)

        if leftovers:
            embed.add_field(
                name="Other Information",
                value="\n".join(f"- {l}" for l in leftovers[:20]),
                inline=False,
            )

        embed.set_footer(
            text=f"Data for {username} from {BOARD_NAME_MAP.get(board_name, board_name)}. Experimental."
        )

        return embed
    except Exception as e:
        logger.exception("Error building embed for board %s: %s", board_name, e)
        return Embed(
            title="Error",
            description=f"An error occurred while building the embed: {str(e)}",
            color=Color.red(),
        )


async def to_roproxy(url: str) -> str:
    """
    Replaces roblox.com addresses with roproxy.com to bypass rate limits/restrictions.

    :param url: The original Roblox URL.
    :return: The converted URL string.
    """
    return url.replace("roblox.com", "roproxy.com")


def iso_to_utc_ts(iso: str) -> int:
    """
    Converts an ISO 8601 timestamp string to a UTC Unix timestamp integer.

    :param iso: ISO format string (e.g., '2023-01-01T00:00:00Z').
    :return: Integer Unix timestamp.
    """
    return int(
        datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    )


def discord_ts(dt: datetime) -> str:
    """
    Converts a datetime object into a Discord markdown timestamp string.

    :param dt: The datetime object to convert.
    :return: A string formatted as <t:timestamp:f> or "Unknown".
    """
    if not dt:
        return "Unknown"
    return f"<t:{int(dt.timestamp())}:f>"

def fetch_git_revision():
    """Safely retrieves the latest git commit hash for app.py."""
    try:
        import get_latest_git_commitid
        return get_latest_git_commitid.get_latest_commit("app.py", short=True)
    except (ImportError, AttributeError, Exception) as e:
        logger.error(f"Failed to get latest git commit: {e}")
        return "N/A"

def can_use_asyncio_run() -> bool:
    """
    Returns True if asyncio.run() can be safely called
    (i.e., no running event loop exists).
    """
    try:
        return asyncio.get_running_loop() is None
    except RuntimeError:
        # No running loop, safe to use asyncio.run()
        return True

# from app import fetch_roles

# async def get_all_ranks():
#     async with aiohttp.ClientSession() as session:
#         return await fetch_roles(session, GROUP_ID)

# all_the_ranks: list = []
# if can_use_asyncio_run():
#     all_the_ranks = asyncio.run(get_all_ranks())

# if all_the_ranks:
#     # print(all_ranks)
#     for rank in all_the_ranks:
#         # print(rank)
#         RANK_ORDER[rank["name"]] = rank["rank"]
#         # print(f"rank added: {rank['name']} → {rank['rank']}")
#         # if rank["name"] not in RANK_ORDER:

# def get_rank_index(rank: str) -> int:
#     # return RANK_ORDER.get(rank, -1)
#     # print(f"{rank}: {RANK_ORDER.get(rank, -1)}")
#     return RANK_ORDER.get(rank, -1)