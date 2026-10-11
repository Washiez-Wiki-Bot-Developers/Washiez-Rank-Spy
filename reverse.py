"""regex_search.py - regex searches over the rank bot's announcement messages (Pycord).

Discord's search API has no regex support, so this works in two stages:
  1. Server-side: the search API narrows by author/channel and an optional plain-text
     `prefilter` (this keeps the number of messages we have to page through small).
  2. Client-side: every candidate message is matched against your regex.

If the search endpoint refuses the bot token, it falls back to scanning
channel.history() with the same regex.

Load with:  bot.load_extension("regex_search")
Test with:  python regex_search.py
"""
from __future__ import annotations

import asyncio
import re

import discord
from discord.ext import commands
from discord.http import Route

try:  # the third-party `regex` package supports match timeouts (protects against ReDoS)
    import regex as _re

    HAS_TIMEOUT = True
except ImportError:
    _re = re
    HAS_TIMEOUT = False

# ---- config: adjust ---------------------------------------------------------
RANK_BOT_ID = 987654321098765432
ANNOUNCE_CHANNEL_ID = 123456789012345678
MAX_PATTERN_LEN = 200
MAX_TEXT_LEN = 4000
# -----------------------------------------------------------------------------


def message_text(msg: discord.Message) -> str:
    """Content plus embed text, since many bots announce via embeds."""
    parts = [msg.content or ""]
    for e in msg.embeds:
        parts += [e.title or "", e.description or ""]
        for f in e.fields:
            parts += [f.name, f.value]
        if e.footer and e.footer.text:
            parts.append(e.footer.text)
    return "\n".join(p for p in parts if p)[:MAX_TEXT_LEN]


def compile_pattern(pattern: str, flags: int = re.IGNORECASE):
    if len(pattern) > MAX_PATTERN_LEN:
        raise ValueError(f"Pattern too long (max {MAX_PATTERN_LEN} chars).")
    return _re.compile(pattern, flags)


def _matches(compiled, text: str) -> re.Match | None:
    try:
        return compiled.search(text, timeout=0.2) if HAS_TIMEOUT else compiled.search(text)
    except TimeoutError:
        return None


async def _api_search(bot, guild_id, *, content, author_id, channel_id, page_size=25, max_pages=40):
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
            await asyncio.sleep(float(data.get("retry_after", 1)))
        else:
            return

        groups = data["messages"]
        if not groups:
            return
        for group in groups:
            for raw in group:
                if raw.get("hit", True):
                    yield raw
        if len(groups) < page_size:
            return


async def _history_scan(bot, channel_id, author_id, limit):
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
            await asyncio.sleep(float(data.get("retry_after", 1)))
        else:
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
    except (discord.Forbidden, discord.HTTPException):
        results.clear()  # search endpoint unavailable for this token -> scan history
        await consume(_history_scan(bot, channel_id, author_id, history_limit))
    return results


class RegexSearch(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot

    @discord.slash_command(name="regexlookup", description="Regex search over rank announcements")
    async def regexlookup(
        self,
        ctx: discord.ApplicationContext,
        pattern: discord.Option(str, "Regex, e.g. (promoted|demoted) to Captain"),
        prefilter: discord.Option(str, "Plain text to narrow the search first", required=False),
        limit: discord.Option(int, "Max results", min_value=1, max_value=25, default=10),
    ):
        await ctx.defer()
        try:
            hits = await regex_search(
                self.bot, ctx.guild_id, pattern, prefilter=prefilter, limit=limit
            )
        except (re.error, ValueError) as exc:
            return await ctx.respond(f"Bad pattern: {exc}", ephemeral=True)

        if not hits:
            return await ctx.respond("No matches.")
        lines = [
            f"{msg.created_at:%Y-%m-%d} `{m.group(0)[:80]}` [link]({msg.jump_url})"
            for msg, m in hits
        ]
        await ctx.respond("\n".join(lines)[:2000])

    @discord.slash_command(name="search", description="Find messages by author ID")
    async def search(
        self,
        ctx: discord.ApplicationContext,
        author_id: discord.Option(str, "Author's user/bot ID"),  # str: IDs overflow slash int options
        limit: discord.Option(int, "Max results", min_value=1, max_value=50, default=10),
    ):
        if not author_id.isdigit():
            return await ctx.respond("author_id must be numeric.", ephemeral=True)

        await ctx.defer()
        msgs = await search_by_author(self.bot, ctx.guild_id, int(author_id), limit)
        if not msgs:
            return await ctx.respond("No messages found.")

        lines = [
            f"{m.created_at:%Y-%m-%d} {(m.content or '[embed]')[:80]} [link]({m.jump_url})"
            for m in msgs
        ]
        await ctx.respond("\n".join(lines)[:2000])


def setup(bot: discord.Bot):
    bot.add_cog(RegexSearch(bot))


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

    # Avoid shadowing the module-level `logger` (which is annotated as logging.Logger).
    for name, logger_obj in logging.Logger.manager.loggerDict.items():
        if name.startswith("discord."):
            logging.getLogger(name).setLevel(logging.INFO)

    logging.getLogger("async_json").setLevel(logging.INFO)
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("bot")

    dotenv.load_dotenv()

    GROUP_ID = 10261023
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    TEST_GUILD_ID = 1113097535796560014
    TEST_USER_ID = 1276397232341520469


    @bot.event
    async def on_ready():
        global role_monitor_task

        logger.info(f"Logged in as {bot.user.name}")
        await bot.change_presence(activity=discord.Game("Monitoring role changes"))

        # Search the guild by author ID via the search API (see api_search.py)
        # Search the guild by author ID via the search API (see api_search.py)
        msgs = await search_by_author(bot, TEST_GUILD_ID, TEST_USER_ID, limit=50)
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
        
        # Combined pattern handling both transitions and leaves based on your message format:
        # Matches: [Username](URL) has [been] [action] [from {prev} to {curr}] [Role] {mention}
        pattern = re.compile(
            r'^\[([^\]]+)\]\(([^)]+)\)\s+'                # [Username](URL)
            r'(?:has\s+(?:been\s+)?)?'                     # optional "has" or "has been"
            r'([a-zA-Z]+)\s+'                              # action (e.g., promoted, demoted, left)
            r'(?:from\s+(.*?)\s+to\s+)?'                   # optional "from {prev} to {curr}"
            r'(.*?)(?:\s+<@&\d+>)?$'                       # role + optional mention
        )

        from_role = ""
        to_role = ""
        
        for m in msgs:
            action = ""
            if match := pattern.match(m.content or ""):
                username, url, action, from_role, to_role_or_left = match.groups()
                
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

        # Search the bot's announcements in the guild that mention this ID
        hits = await search_by_author(
            bot, TEST_GUILD_ID, TEST_USER_ID, limit=100, content=TARGET_ID
        )
        if not hits:
            # Discord's index may not tokenise numbers inside URLs, so pull more and match locally
            wide = await search_by_author(bot, TEST_GUILD_ID, TEST_USER_ID, limit=500)
            hits = [m for m in wide if TARGET_ID in message_text(m)]

        print(f"{len(hits)} messages mention {TARGET_ID}")
        for m in hits:
            print(m.created_at, m.jump_url, (m.content or "[embed]")[:120])
        
        with open("messages.json", "w") as f:
            json.dump([m.content for m in msgs], f, indent=2, default=str)
        
        print("Done. Check messages.json for the output.")
        print("Will attempt to structure the messages into a list of rank changes next.")
        


    # if __name__ == "__main__":
    try:
        bot.load_extension("commands")  # This loads the commands from commands.py
        # bot.load_extension("special_patches")  # This loads the commands from special_patches.py
    except Exception as e:
        logger.error(f"Failed to load commands extension: {e}")

    # Register this file's cog directly (load_extension would import a second copy of the module)
    setup(bot)

    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Error running bot: {e}")