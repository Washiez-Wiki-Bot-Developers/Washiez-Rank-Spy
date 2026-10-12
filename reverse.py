"""
# reverse.py - regex searches over the rank bot's announcement messages (Pycord).
Copyright (c) 2026 Rankspy (Washiez Variant) by Washiez Wiki: Bot Developers, 
based on original work from MartinAstrea. Made with 🧼🫧 by WW:BD, Martin and MrT!

Licensed under GNU LGPL 3.0 License until further revision.

Washiez-Wiki-Bot-Developers/Washiez-Rank-Spy

:copyright: 2026 Washiez Wiki: Bot Developers (WW:BD)
:license: GNU LGPL 3.0
:original_author: MartinAstrea
:contributors: WW:BD, Martin, MrT, LLMs
:repository: https://github.com/Washiez-Wiki-Bot-Developers/Washiez-Rank-Spy

### Descriptions
Main entry point for the Washiez Rank Spy bot. Initializes the bot, sets up configurations, 
and starts the main event loop. Handles command-line arguments and environment-specific settings.

### LLM Usage
This code uses heavily human supervised AI code. Majority should have been rewritten.
"""
from __future__ import annotations
import time

import asyncio
import re
import logging  # Added for logging setup

import discord
from discord.ext import commands
from discord.http import Route

try:  # the third-party `regex` package supports match timeouts (protects against ReDoS)
    import regex as _re

    HAS_TIMEOUT = True
except ImportError:
    _re = re
    HAS_TIMEOUT = False

import roblox

# ---- config: adjust ---------------------------------------------------------
RANK_BOT_ID = 987654321098765432
ANNOUNCE_CHANNEL_ID = 123456789012345678
MAX_PATTERN_LEN = 200
MAX_TEXT_LEN = 4000

TMM_DISCORD_ID = 1276397232341520469
# -----------------------------------------------------------------------------

logger = logging.getLogger(__name__)  # Added scriptwide logger initialization


def message_text(msg: discord.Message) -> str:
    logger.debug("Executing message_text for message ID: %s", getattr(msg, 'id', None))  # Added logging line
    """Content plus embed text, specialty bots announce via embeds."""
    parts = [msg.content or ""]
    for e in msg.embeds:
        parts += [e.title or "", e.description or ""]
        for f in e.fields:
            parts += [f.name, f.value]
        if e.footer and e.footer.text:
            parts.append(e.footer.text)
    return "\n".join(p for p in parts if p)[:MAX_TEXT_LEN]


def compile_pattern(pattern: str, flags: int = re.IGNORECASE):
    logger.debug("Compiling regex pattern of length %d", len(pattern))  # Added logging line
    if len(pattern) > MAX_PATTERN_LEN:
        logger.error("Pattern length %d exceeds max length %d", len(pattern), MAX_PATTERN_LEN)  # Added logging line
        raise ValueError(f"Pattern too long (max {MAX_PATTERN_LEN} chars).")
    return _re.compile(pattern, flags)


def _matches(compiled, text: str) -> re.Match | None:
    logger.debug("Evaluating regex match against text length %d", len(text))  # Added logging line
    try:
        return compiled.search(text, timeout=0.2) if HAS_TIMEOUT else compiled.search(text)
    except TimeoutError:
        logger.warning("Regex matching timed out.")  # Added logging line
        return None


async def _api_search(bot, guild_id, *, content, author_id, channel_id, page_size=25, max_pages=40):
    logger.info("Starting API search for guild %s, author %s, channel %s", guild_id, author_id, channel_id)  # Added logging line
    """Yield raw message dicts from the guild search endpoint, paging with offset."""
    route = Route("GET", "/guilds/{guild_id}/messages/search", guild_id=guild_id)
    for page in range(max_pages):
        params = {
            "author_id": author_id,
            "channel_id": channel_id,
            "limit": page_size,
            "offset": page * page_size,
            "sort_by": "timestamp",
            "sort_order": "desc",
        }
        if content:
            params["content"] = content

        data = None
        for _ in range(5):  # the index may answer "not ready, retry_after"
            data = await bot.http.request(route, params=params)
            if "messages" in data:
                break
            logger.debug("API search not ready, retrying after %s seconds", data.get("retry_after", 1))  # Added logging line
            await asyncio.sleep(float(data.get("retry_after", 1)))
        else:
            logger.error("API search failed after 5 retries.")  # Added logging line
            return

        groups = data["messages"]
        if not groups:
            logger.debug("API search returned no message groups on page %d", page)  # Added logging line
            return
        for group in groups:
            for raw in group:
                if raw.get("hit", True):
                    yield raw
        if len(groups) < page_size:
            return


async def _history_scan(bot, channel_id, author_id, limit):
    logger.info("Falling back to history scan for channel %s with author %s up to limit %d", channel_id, author_id, limit)  # Added logging line
    channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
    async for msg in channel.history(limit=limit):
        if msg.author.id == author_id:
            yield msg


async def search_by_author(
    bot: discord.Bot,
    guild_id: int,
    author_id: int,
    limit: int = 25,
    content: str | None = None,
) -> list[discord.Message]:
    """Return up to `limit` messages by `author_id` across the guild, newest first."""
    logger.info("search_by_author invoked for guild %s, author %s", guild_id, author_id)  # Added logging line
    print(f"[DEBUG] Searching for messages by author {author_id} in guild {guild_id} with content filter: {content}")
    
    route = Route("GET", "/guilds/{guild_id}/messages/search", guild_id=guild_id)
    page_size = 25
    messages: list[discord.Message] = []
    offset = 0

    while len(messages) < limit:
        params = {
            "author_id": author_id,
            "limit": page_size,
            "offset": offset,
            "sort_by": "timestamp",
            "sort_order": "desc",
        }
        if content:
            params["content"] = content

        # The index may answer "not ready, retry_after" instead of results
        for _ in range(5):
            data = await bot.http.request(route, params=params)
            if "messages" in data:
                break
            logger.debug("search_by_author retry triggered for offset %d", offset)  # Added logging line
            await asyncio.sleep(float(data.get("retry_after", 1)))
        else:
            logger.warning("search_by_author aborted after max retries.")  # Added logging line
            break

        groups = data["messages"]
        if not groups:
            break

        for group in groups:
            for raw in group:
                if not raw.get("hit", True):
                    continue
                cid = int(raw["channel_id"])
                channel = bot.get_channel(cid) or await bot.fetch_channel(cid)
                messages.append(discord.Message(state=bot._connection, channel=channel, data=raw))

        if len(groups) < page_size:
            break
        offset += page_size

    logger.debug("search_by_author returning %d messages", len(messages))  # Added logging line
    return messages[:limit]


async def regex_search(
    bot: discord.Bot,
    guild_id: int,
    pattern: str,
    *,
    flags: int = re.IGNORECASE,
    prefilter: str | None = None,
    author_id: int = RANK_BOT_ID,
    channel_id: int = ANNOUNCE_CHANNEL_ID,
    limit: int = 25,
    history_limit: int = 5000,
) -> list[tuple[discord.Message, re.Match]]:
    logger.info("regex_search invoked with pattern: %s", pattern)  # Added logging line
    """Return up to `limit` (message, match) pairs, newest first."""
    compiled = compile_pattern(pattern, flags)
    results: list[tuple[discord.Message, re.Match]] = []

    async def consume(messages):
        async for msg in messages:
            if (m := _matches(compiled, message_text(msg))):
                results.append((msg, m))
                if len(results) >= limit:
                    return True
        return False

    async def api_messages():
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        async for raw in _api_search(
            bot, guild_id, content=prefilter, author_id=author_id, channel_id=channel_id
        ):
            yield discord.Message(state=bot._connection, channel=channel, data=raw)

    try:
        await consume(api_messages())
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning("API search unavailable (%s), falling back to history scan", exc)  # Added logging line
        results.clear()  # search endpoint unavailable for this token -> scan history
        await consume(_history_scan(bot, channel_id, author_id, history_limit))
    return results


async def get_single_user_dict_from_announcements(
    bot: discord.Bot,
    user_ident: text | int,
    search_guild_id: int | list[int],
    author_id: int = RANK_BOT_ID,
    channel_id: int = ANNOUNCE_CHANNEL_ID,
    limit: int = 1000,
) -> dict:
    logger.info("get_single_user_dict_from_announcements called for identifier: %s", user_ident)  # Added logging line
    """Returns user.json (should be) schema-compliant dictionary."""
    print(f"[DEBUG] Searching for user {user_ident} in guild(s) {search_guild_id} with author {author_id}")
    
    if isinstance(user_ident, str):
        roblox_user = await roblox.RobloxUser.create(username=user_ident)
        target_rob_id = int(roblox_user.id)
    elif isinstance(user_ident, int):
        target_rob_id = int(user_ident)

    for guild_id in (search_guild_id if isinstance(search_guild_id, list) else [search_guild_id]):
        hits = await search_by_author(
            bot, guild_id, author_id, limit=100, content=target_rob_id
        )
        if not hits:
            logger.info("No direct hits found, running wide search for target_rob_id: %s", target_rob_id)  # Added logging line
            # Discord's index may not tokenise numbers inside URLs, so pull more and match locally
            wide = await search_by_author(bot, guild_id, TMM_DISCORD_ID, limit=500)
            hits = [m for m in wide if str(target_rob_id) in message_text(m)]
        
        user = {
            "epoch": int(time.time()),
            "user": {
                "id": str(target_rob_id),
                "username": ""
            },
            "events": []
        }
        
        pattern = re.compile(
            r'^\[([^\]]+)\]\('                            # [Username] (Group 1)             r'(?:<)?https://(?:www\.)?roblox\.com/users/(\d+)/profile(?:>)?'  # URL with optional angle brackets, ID captured (Group 2)             r'\)\s+'                                      # Closing paren and whitespace
            r'(?:has\s+(?:been\s+)?)?'                     # Optional "has been"
            r'([a-zA-Z]+)\s+'                             # Action (Group 3)
            r'(?:from\s+(.*?)\s+to\s+)?'                  # From rank (Group 4)
            r'(.*?)(?:\s+<@&\d+>)?$'                      # To rank / role (Group 5)
        )
        
        for m in hits[::-1]:  # Reverse to get chronological order
            if match := pattern.match(m.content or ""):
                username, user_id, action, from_rank, to_rank_or_left = match.groups()
                logger.debug("Matched message %s: user=%s, action=%s", m.id, username, action)  # Added logging line
                print(f"[DEBUG] Matched message {m.id}: user={username}, action={action}")
                
                if action == "left":
                    from_rank = to_rank_or_left
                    to_rank = "None"
                else:
                    to_rank = to_rank_or_left
                event_dict = {
                    "epoch": int(time.time()),
                    "id": str(m.id),
                    "action": action,
                    "from_rank": from_rank,
                    "to_rank": to_rank,
                    "at": int(m.created_at.timestamp()),
                    "date_kind": "created",
                    "source": {
                        "kind": "discord",
                        "guild_id": str(m.guild.id),
                        "guild_name": m.guild.name,
                        "channel_id": str(m.channel.id),
                        "message_id": str(m.id),
                        "url": m.jump_url
                    }
                }
                
                user["events"].append(event_dict)
                print(f"[DEBUG] Appended event. Total events: {len(user['events'])}")
                
                if (not user["user"]["username"]) and (m == hits[::-1][-1]):
                    user["user"]["username"] = username
                    logger.debug("Set fallback username: %s", username)  # Added logging line
                    print(f"[DEBUG] Set fallback username: {username}")
            else:
                logger.debug("Message %s skipped (no pattern match)", m.id)  # Added logging line
                print(f"[DEBUG] Message {m.id} skipped (no pattern match)")
                print(f"[DEBUG] Content: {m.content or '[embed]'}")
        
        return user


# ---- local test harness: only runs via `python regex_search.py` ---------------
if __name__ == "__main__":
    import asyncio, os
    import json
    import logging
    import time
    from typing import cast
    import aiohttp

    import discord
    from discord.ext import commands
    import dotenv

    from discord_report_error_logs import DiscordErrorHandler
    from utils import safe_send, safe_send_and_pub, safe_reaction, safe_publish
    import special_patches

    from aiofiles import open as aiofiles_open

    import requests

    asyncio.set_event_loop(asyncio.new_event_loop())

    intents = discord.Intents.default()
    intents.guilds = True
    bot = commands.Bot(command_prefix="! ", intents=intents, reconnect=True)

    # Set up logging
    import logging_setup

    from roblox import RobloxUser

    logger: logging.Logger = logging_setup.setup_logging(
        rankspy_default_level=True,
        bot=bot,
        error_channel_id=os.getenv("TIME_TRACKING_CHANNEL_ID"),
    )
    logger = cast(logging.Logger, logger)

    for name, logger_obj in logging.Logger.manager.loggerDict.items():
        if name.startswith("discord."):
            logging.getLogger(name).setLevel(logging.INFO)

    logging.getLogger("async_json").setLevel(logging.INFO)
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("bot")

    dotenv.load_dotenv()

    GROUP_ID = 10261023
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    guild_id = 1113097535796560014
    TEST_USER_ID = 1276397232341520469


    @bot.event
    async def on_ready():
        global role_monitor_task

        logger.info(f"Logged in as {bot.user.name}")
        await bot.change_presence(activity=discord.Game("Monitoring role changes"))

        logger.info("Executing on_ready test sequence in test harness.")  # Added logging line
        msgs = await search_by_author(bot, guild_id, TEST_USER_ID, limit=50)
        logger.info(f"Found {len(msgs)} messages from {TEST_USER_ID}")
        
        import rich
        
        from rich.console import Console
        from rich.table import Table

        console = Console()

        table = Table(title="Messages")

        table.add_column("Created At", style="cyan", max_width=15)
        table.add_column("Channel ID", style="magenta")
        table.add_column("Jump URL", style="blue")
        table.add_column("Content", style="green")
        table.add_column("Action (P/D)", style="yellow", width=1)
        table.add_column("Rank from", style="red")
        table.add_column("Rank to", style="green")
        
        pattern = re.compile(
            r'^\[([^\]]+)\]\('                            # [Username] (Group 1)             r'(?:<)?https://(?:www\.)?roblox\.com/users/(\d+)/profile(?:>)?'  # URL with optional angle brackets, ID captured (Group 2)             r'\)\s+'                                      # Closing paren and whitespace
            r'(?:has\s+(?:been\s+)?)?'                     # Optional "has been"
            r'([a-zA-Z]+)\s+'                             # Action (Group 3)
            r'(?:from\s+(.*?)\s+to\s+)?'                  # From rank (Group 4)
            r'(.*?)(?:\s+<@&\d+>)?$'                      # To rank / role (Group 5)
        )

        from_role = ""
        to_role = ""
        
        for m in msgs:
            action = ""
            if match := pattern.match(m.content or ""):
                username, user_id, action, from_role, to_role_or_left = match.groups()
                
                if action == "left":
                    from_role = to_role_or_left
                    to_role = "None"
                else:
                    to_role = to_role_or_left

                print(f"User: {username} | Action: {action} | From: {from_role} | To: {to_role}")
            
            table.add_row(
                str(m.created_at),
                str(m.channel.id),
                str(m.jump_url),
                str(m.content or "[embed]"),
                str(action[:1]),
                str(from_role or ""),
                str(to_role or "")
            )

        console.print(table)
        
        print("="*20)
        TARGET_ID = "9371807807"
        print(f"Checking {TARGET_ID}")

        table = Table(title="Announcements of this user")
        
        table.add_column("Created At", style="cyan", max_width=15)
        table.add_column("Channel ID", style="magenta")
        table.add_column("Jump URL", style="blue")
        table.add_column("Content", style="green")
        table.add_column("Action (P/D)", style="yellow", width=1)
        table.add_column("Rank from", style="red")
        table.add_column("Rank to", style="green")
        
        hits = await search_by_author(
            bot, guild_id, TEST_USER_ID, limit=100, content=TARGET_ID
        )
        if not hits:
            wide = await search_by_author(bot, guild_id, TEST_USER_ID, limit=500)
            hits = [m for m in wide if TARGET_ID in message_text(m)]

        print(f"{len(hits)} messages mention {TARGET_ID}")
        for m in hits:
            print(m.created_at, m.jump_url, (m.content or "[embed]")[:120])
            action = ""
            if match := pattern.match(m.content or ""):
                username, user_id, action, from_role, to_role_or_left = match.groups()
                
                if action == "left":
                    from_role = to_role_or_left
                    to_role = "None"
                else:
                    to_role = to_role_or_left

            table.add_row(
                str(m.created_at),
                str(m.channel.id),
                str(m.jump_url),
                str(m.content or "[embed]"),
                str(action[:1]),
                str(from_role or ""),
                str(to_role or "")
            )
            
        console.print(table)
        
        with open("messages.json", "w") as f:
            json.dump([m.content for m in msgs], f, indent=2, default=str)
        
        print("Done. Check messages.json for the output.")
        print("Will attempt to structure the messages into a list of rank changes next.")
        
        TEST_GUILD_ID = 1113097535796560014
        
        user = await get_single_user_dict_from_announcements(
            bot, 9371807807, TEST_GUILD_ID, author_id=TEST_USER_ID, channel_id=ANNOUNCE_CHANNEL_ID, limit=1000
        )
        
        with open("user.json", "w") as f:
            json.dump(user, f, indent=2)

    try:
        bot.load_extension("commands")
    except Exception as e:
        logger.error(f"Failed to load commands extension: {e}")

    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Error running bot: {e}")