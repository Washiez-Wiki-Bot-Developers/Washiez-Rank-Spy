from libraries import *  # centralized common imports  # noqa: F403 

from typing import Union, Optional

ALL_RANKS: list[str] = []

logger = logging.getLogger(__name__)


async def _resolve_discord_channel(client: discord.Client, channel_id: int):
    """Resolve a channel from cache or by fetching it, with retries for transient client readiness issues."""
    try:
        # bypass cache -> fetch live state
        return await client.fetch_channel(channel_id)
    except Exception:
        # fallback to cache if fetch fails
        return client.get_channel(channel_id)
    
    # channel = client.get_channel(channel_id)
    # if channel:
    #     logger.debug(f"_resolve_discord_channel: Found {channel_id} in cache")
    #     return channel

    # logger.debug(f"_resolve_discord_channel: Cache miss for {channel_id}, attempting fetch (bot.is_ready={client.is_ready()})")
    
    # for attempt in range(3):
    #     try:
    #         logger.debug(f"_resolve_discord_channel: Fetch attempt {attempt + 1}/3 for {channel_id}")
    #         channel = await client.fetch_channel(channel_id)
    #         if channel:
    #             logger.debug(f"_resolve_discord_channel: Successfully fetched {channel_id}")
    #             return channel
    #     except discord.NotFound:
    #         logger.error("_resolve_discord_channel: Channel not found for %s (bot may lack access or channel deleted)", channel_id)
    #         return None
    #     except discord.Forbidden:
    #         logger.error("_resolve_discord_channel: Forbidden accessing channel %s (bot lacks permissions)", channel_id)
    #         return None
    #     except AttributeError as e:
    #         if "_MissingSentinel" in repr(e) or "request" in str(e):
    #             logger.debug(
    #                 "_resolve_discord_channel: HTTP session not ready for %s (attempt %d), retrying",
    #                 channel_id,
    #                 attempt + 1,
    #             )
    #             await asyncio.sleep(1)
    #             continue
    #         logger.exception("_resolve_discord_channel: unexpected AttributeError for %s", channel_id)
    #         return None
    #     except (discord.HTTPException, discord.ConnectionClosed, OSError) as e:
    #         logger.warning(
    #             "_resolve_discord_channel: fetch failed for %s (attempt %d, error=%s), retrying...",
    #             channel_id,
    #             attempt + 1,
    #             type(e).__name__,
    #         )
    #         await asyncio.sleep(1)
    #         continue
    #     except Exception as e:
    #         logger.exception("_resolve_discord_channel: unexpected error resolving %s: %s", channel_id, type(e).__name__)
    #         return None

    # logger.error("_resolve_discord_channel: Unable to resolve channel %s after 3 retries", channel_id)
    # return None


async def safe_send(
    message: str,
    channel_id: int,
    bot: Optional[discord.Client] = None,
    silent: bool = False,
    message_critical: bool = True,
) -> Union[tuple[bool, Optional[discord.Message]], tuple[bool, None]]:
    """
    Safely send a message to a channel with retries.

    :param message: The message content to send.
    :param channel_id: The ID of the channel to send the message to.
    :param bot: The discord.Client instance to use.
    :param silent: Whether to send the message silently.
    :param message_critical: Whether to retry indefinitely.
    :returns: Tuple of (success status, message object or None)
    """
    logger.debug(f"safe_send: Initiating send to channel {channel_id}")
    client = bot or _bot

    if not client:
        logger.error(f"safe_send: No client available for channel {channel_id}")
        return False, None

    channel = await _resolve_discord_channel(client, channel_id)
    if channel is None:
        logger.warning(f"safe_send: channel {channel_id} unavailable")
        return False, None

    try:
        msg = await channel.send(message, silent=silent)
        logger.debug(f"safe_send: Success, sent to {channel_id}")
        return True, msg
    except discord.Forbidden:
        logger.error(f"safe_send: Forbidden in channel {channel_id}")
        return False, None
    except Exception as e:
        logger.exception(f"safe_send: Unexpected crash: {e}")
        return False, None


async def safe_publish(
    message_id: int,
    channel_id: Optional[int] = None,
    bot: Optional[discord.Client] = None,
    message_critical: bool = True,
) -> Optional[Union[discord.Message, bool]]:
    """
    Safely publish (crosspost) a message to an announcement channel.
    """
    client = bot or _bot
    if not client or channel_id is None:
        raise ValueError("Must provide bot and channel_id.")

    channel = await _resolve_discord_channel(client, channel_id)
    if not channel:
        raise ValueError(f"Channel {channel_id} not found.")

    forbidden_attempts = 0
    attempts = 0

    while True:
        try:
            if not message_critical and attempts >= 1:
                return False

            message = await channel.fetch_message(message_id)
            if not hasattr(message, "publish"):
                raise ValueError("Channel does not support publishing.")

            published_message = await message.publish()
            
            # Verification
            refreshed = await channel.fetch_message(message_id)
            if refreshed.flags.crossposted:
                logger.info(f"safe_publish: Successfully published {message_id}")
                return published_message
            
            attempts += 1
            await asyncio.sleep(2)

        except (discord.Forbidden, ValueError) as e:
            forbidden_attempts += 1
            logger.warning(f"safe_publish: Forbidden/ValueError ({forbidden_attempts}/3): {e}")
            if str(os.getenv("ENVIRONMENT_MODE")) == "local_debug": return True
            if forbidden_attempts >= 3: return False
            await asyncio.sleep(2)
        except discord.errors.HTTPException as e:
            if "already been crossposted" in str(e):
                return True
            attempts += 1.5
        except Exception as e:
            logger.error(f"safe_publish: Unexpected error: {e}")
            attempts += 1
            if not message_critical and attempts >= 5: return False
            await asyncio.sleep(2)


async def safe_reaction(message: discord.Message, emoji: str, bot: Optional[discord.Client] = None):
    """Safely add a reaction with retries."""
    forbidden_attempts = 0
    attempts = 0

    while True:
        try:
            await message.add_reaction(emoji)
            return True
        except discord.Forbidden:
            forbidden_attempts += 1
            if forbidden_attempts >= 3: return False
            await asyncio.sleep(2)
        except (discord.HTTPException, discord.ConnectionClosed, OSError) as e:
            if isinstance(e, discord.NotFound):
                logger.error("safe_reaction: Message not found")
                return False
            attempts += 1
            if attempts >= 5: return False
            await asyncio.sleep(2)

# --- Composite Helper Functions ---

async def safe_send_and_pub(message: str, channel_id: int, bot: Optional[discord.Client] = None, silent: bool = False):
    status, msg = await safe_send(message, channel_id, bot, silent)
    if status and msg:
        await safe_publish(msg.id, channel_id, bot)
    return msg

async def safe_send_react(message: str, channel_id: int, emoji: str, bot: Optional[discord.Client] = None, silent: bool = False):
    status, msg = await safe_send(message, channel_id, bot, silent)
    if status and msg:
        await safe_reaction(msg, emoji, bot)
    return msg

async def safe_send_pub_react(message: str, channel_id: int, emoji: str, bot: Optional[discord.Client] = None, silent: bool = False):
    msg = await safe_send_react(message, channel_id, emoji, bot, silent)
    if msg:
        await safe_publish(msg.id, channel_id, bot)
    return msg


async def diagnose_channel_access(channel_id: int, bot: Optional[discord.Client] = None) -> dict:
    """
    Diagnose why a channel cannot be resolved. Returns a detailed report.
    
    :param channel_id: Channel ID to diagnose
    :param bot: Discord client to use (defaults to _bot global)
    :returns: Dictionary with diagnostic info
    """
    client = bot or _bot
    report = {
        "channel_id": channel_id,
        "cache_hit": False,
        "is_ready": client.is_ready() if client else False,
        "fetch_error": None,
        "error_type": None,
        "suggestion": None,
    }
    
    if not client:
        report["error_type"] = "NO_CLIENT"
        report["suggestion"] = "Bot client is None"
        return report
    
    # Try cache
    channel = client.get_channel(channel_id)
    if channel:
        report["cache_hit"] = True
        report["channel_name"] = channel.name
        report["guild"] = getattr(channel, "guild", {}).name if hasattr(channel, "guild") else None
        return report
    
    # Try fetch
    try:
        channel = await client.fetch_channel(channel_id)
        report["fetch_error"] = "SUCCESS"
        report["channel_name"] = channel.name
        report["guild"] = getattr(channel, "guild", {}).name if hasattr(channel, "guild") else None
        return report
    except discord.NotFound:
        report["error_type"] = "NOT_FOUND"
        report["fetch_error"] = "discord.NotFound"
        report["suggestion"] = "Channel ID is invalid, bot is not in that guild, or channel was deleted"
    except discord.Forbidden:
        report["error_type"] = "FORBIDDEN"
        report["fetch_error"] = "discord.Forbidden"
        report["suggestion"] = "Bot lacks permissions to view this channel"
    except AttributeError as e:
        report["error_type"] = "ATTRIBUTE_ERROR"
        report["fetch_error"] = str(e)
        report["suggestion"] = "HTTP session not ready (transient)"
    except (discord.HTTPException, discord.ConnectionClosed) as e:
        report["error_type"] = type(e).__name__
        report["fetch_error"] = str(e)
        report["suggestion"] = "Network issue or Discord connection problem"
    except Exception as e:
        report["error_type"] = type(e).__name__
        report["fetch_error"] = str(e)
        report["suggestion"] = f"Unexpected error: {type(e).__name__}"
    
    return report


from discord import Embed, Color
try:
    from trello import parse_card, BOARD_NAME_MAP
except ImportError:
    logger.warning("Trello module not found. Trello-related functions will not work.")

MAX_FIELDS = 25  # Discord hard limit per embed


def build_trello_board_embed(username, board_name, cards, color, icon=None):
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
            text=f"Data for {username} from {BOARD_NAME_MAP.get(board_name, board_name)}. Experimental. Copyright of Data by Trello Board owner, contributors or other entities."
        )

        return embed
    except Exception as e:
        logger.exception("Error building embed for board %s: %s", board_name, e)
        return Embed(
            title="Error",
            description=f"An error occurred while building the embed: {str(e)}",
            color=Color.red(),
        )

def build_reverse_embed(username, history, color, icon=None):
    """
    Constructs a Discord Embed based on historical event logs.

    :param username: The Roblox username associated with the data.
    :param history: The history dictionary containing events.
    :param color: The discord.Color to use for the embed sidebar.
    :param icon: Optional URL for the author icon.

    :return: A discord.Embed object.
    """
    try:
        embed = Embed(color=color)
        embed.set_author(name=f"Washiez Wiki Rank Changes History: {username}", icon_url=icon)

        events = history.get("events", [])
        used_fields = 0
        guilds_set = set()

        for event in events:
            if used_fields >= MAX_FIELDS:
                break

            action = event.get("action", "unknown").capitalize()
            from_rank = event.get("from_rank", "Unknown")
            to_rank = event.get("to_rank", "Unknown")
            timestamp = event.get("at")
            
            # Format timestamp or fallback
            date_str = f"<t:{timestamp}:R>" if timestamp else "Unknown date"

            source = event.get("source", {})
            guild_name = source.get("guild_name")
            if guild_name:
                guilds_set.add(guild_name)
            
            from_rank_split = from_rank.split(" ") if from_rank else ""
            from_rank_initial = ""
            for item in from_rank_split:
                item = list(item.strip())[0] # strip, separate chars, get first letter
                
                from_rank_initial += item
            del from_rank_split

            field_name = to_rank# f"{action}: ({from_rank_initial} ->) {to_rank}"
            embed.add_field(name=field_name, value=f"{action}: {from_rank} -> {to_rank}\n{date_str}", inline=True)#action != "Demoted")
            used_fields += 1

        footer_text = f"Data for {username}"
        if guilds_set:
            footer_text += f" from {', '.join(guilds_set)}"
        footer_text += ". Experimental. Washiez Wiki, contributors or other entities."

        embed.set_footer(text=footer_text)

        return embed
    except Exception as e:
        logger.exception("Error building reverse embed for user %s: %s", username, e)
        return Embed(
            title="Error",
            description=f"An error occurred while building the history embed: {str(e)}",
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

class conversionsRolesetIDRoleID:
    """Handles translation between Roblox Role IDs and Rank numbers.
    
    :param roles_data: List of role dictionaries from Roblox API.
    """
    def __init__(self, roles_data: list[dict[str, any]]):
        self.id_to_rank: dict[int, int] = {r["id"]: r["rank"] for r in roles_data}
        self.rank_to_id: dict[int, int] = {r["rank"]: r["id"] for r in roles_data}

    def get_rank(self, role_id: int) -> int | None:
        """Get rank number from role ID.
        
        :param role_id: Target role ID.
        :returns: Rank number (0-255) or None.
        """
        return self.id_to_rank.get(role_id)

    def get_role_id(self, rank: int) -> int | None:
        """Get role ID from rank number.
        
        :param rank: Target rank number.
        :returns: Role ID or None.
        """
        return self.rank_to_id.get(rank)

class Immutable:
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __setattr__(self, key, value):
        if hasattr(self, key):
            raise AttributeError("Immutable")
        super().__setattr__(key, value)
