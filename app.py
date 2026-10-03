"""
# App.py
Copyright (c) 2026 Rankspy (Washiez Variant) by Washiez Wiki: Bot Developers, 
based on original work from MartinAstrea. Made with 🧼🫧 by WW:BD, Martin and MrT!

Licensed under GNU LGPL 3.0 License until further revision.

Washiez-Wiki-Bot-Developers/Washiez-Rank-Spy

:copyright: 2026 Washiez Wiki: Bot Developers (WW:BD)
:license: GNU LGPL 3.0
:original_author: MartinAstrea
:contributors: WW:BD, Martin, MrT
:repository: https://github.com/Washiez-Wiki-Bot-Developers/Washiez-Rank-Spy

### Descriptions
Main entry point for the Washiez Rank Spy bot. Initializes the bot, sets up configurations, 
and starts the main event loop. Handles command-line arguments and environment-specific settings.
"""# pylint: disable-next=C0410
import asyncio, time, logging, datetime
from contextlib import nullcontext
from collections import defaultdict
from typing import AsyncGenerator, Any

# pylint: disable-next=C0410
import aiohttp, discord
from discord.ext import commands

# pylint: disable-next=W0401
from libraries import *  # centralized common imports
from logging_setup import setup_logging
from utils import safe_send, safe_send_and_pub, safe_send_pub_react

# pylint: disable-next=W0401
from rank_groups import *


if IS_RICH_ENV:
    from rich.progress import Progress, TextColumn, BarColumn, TimeElapsedColumn



class TypedBot(commands.Bot):
    ROLE_PROGRESS_LOCK: asyncio.Lock
    ROLE_PROGRESS: dict[str, dict[str, int | bool | float]]
    roblox_limiter: "RobloxLimiter"
    data_store: "AsyncJSONStore"  # pyright: ignore[reportUndefinedVariable]
    _process_single_user_delta: callable  # Type hint for the method attached later
    
    PRESENCE_UPDATE_INTERVAL: float = 10.0  # seconds
    _last_presence_update: float = 0.0  # Timestamp of last presence update
    
    GROUP_ID = 10261023


global bot
intents = discord.Intents.default()
intents.guilds = True
bot = TypedBot(command_prefix="!wwbd ", intents=intents, reconnect=True)

logger = setup_logging(name="bot", level=logging.INFO, bot=bot, error_channel_id=None, rankspy_default_level=False, is_rich_env=IS_RICH_ENV)
del setup_logging  # Clean up namespace

GROUP_ID = bot.GROUP_ID

bot.ROLE_PROGRESS = defaultdict(
    lambda: {"checked": 0, "total": 0, "done": False, "start": 0.0}
)
bot.ROLE_PROGRESS_LOCK = asyncio.Lock()

ROLE_PROGRESS_LOCK = bot.ROLE_PROGRESS_LOCK
ROLE_PROGRESS = bot.ROLE_PROGRESS

# Constants
ROBLOX_RPS = 6
ROBLOX_BURST = 8
ROBLOX_429_STREAK = 0

MAX_CHARS_DISCORD = 1900

TIME_TRACKING_CHANNEL_ID = 0
JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL = 0
HIGH_RANKS: set[str] = set()
RANK_ORDER: list[str] = []


class RobloxLimiter:
    def __init__(self, rate: int, burst: int):
        self._rate, self._burst = rate, burst
        self._sem = asyncio.Semaphore(burst)
        self._delay = 1 / rate

    async def wait(self) -> None:
        await self._sem.acquire()
        asyncio.get_running_loop().call_later(self._delay, self._sem.release)

    async def acquire(self) -> None:
        await self.wait()


bot.roblox_limiter = RobloxLimiter(ROBLOX_RPS, ROBLOX_BURST)


async def roblox_get_json(session: aiohttp.ClientSession, url: str, timeout: int = 10) -> dict | None:
    """Perform a rate-limited HTTP GET request to Roblox endpoints.

    :param session: Active aiohttp ClientSession instance.
    :param url: Complete endpoint URL to fetch.
    :param timeout: Total HTTP request timeout ceiling in seconds.
    :returns: Parsed JSON payload or None on non-200 responses.
    """
    async def _get(u: str) -> tuple[int, Any]:
        await bot.roblox_limiter.acquire()
        async with session.get(u, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            return r.status, await r.json()

    status, data = await _get(url)
    if status == 429:
        global ROBLOX_429_STREAK
        ROBLOX_429_STREAK = min(ROBLOX_429_STREAK + 1, 5)
        await asyncio.sleep(1.5 * ROBLOX_429_STREAK)
        status, data = await _get(await to_roproxy(url))  # pyright: ignore[reportUndefinedVariable]
    return data if status == 200 else None


async def fetch_roles(session: aiohttp.ClientSession, group_id: int) -> list[dict[str, Any]]:
    """Fetch defined role metadata for a given Roblox group.

    :param session: Active aiohttp ClientSession instance.
    :param group_id: Target Roblox group identifier.
    :returns: List of raw role dictionary definitions.
    """
    data = await roblox_get_json(session, f"https://groups.roblox.com/v1/groups/{group_id}/roles")
    return data.get("roles", []) if data else []


async def fetch_users_in_role(
    session: aiohttp.ClientSession, group_id: int, role_id: int, 
    role_member_count: int | None = None, is_rich_env: bool = True
) -> AsyncGenerator[dict[str, Any], None]:
    """Stream user membership records for a specific group role.

    :param session: Active aiohttp ClientSession instance.
    :param group_id: Target Roblox group identifier.
    :param role_id: Target Roblox role identifier.
    :param role_member_count: Expected member count for task scaling.
    :param is_rich_env: Boolean toggle for terminal progress rendering.
    :yields: Individual user dictionary records.
    """
    cursor, total = None, role_member_count or 0
    url_base = f"https://groups.roblox.com/v1/groups/{group_id}/roles/{role_id}/users?limit=100"
    
    if not is_rich_env:
        logger.info(f"Fetching users in role {role_id} (total: {total}) without rich progress...")
    else:
        progress_context = Progress(TextColumn("Fetched {task.completed}/{task.total}"), BarColumn(), TimeElapsedColumn(), transient=True) 
    
    async def main(progress_p=None, task=None):
        while True:
            url = f"{url_base}&cursor={cursor}" if cursor else url_base
            data = await roblox_get_json(session, url)
            if not data:
                break
            
            for user in data.get("data", []):
                yield user
                if task and progress_p:
                    progress_p.advance(task, 1)
            
            cursor = data.get("nextPageCursor")
            if not cursor:
                break
    
    if is_rich_env:
        with (progress_context if progress_context else nullcontext()) as progress_p:
            task = progress_p.add_task(f"Role {role_id}", total=total) if progress_p and hasattr(progress_p, "add_task") else None
            async for user in main(progress_p, task):
                yield user
    else:
        async for user in main():
            yield user

import asyncio
import aiohttp

GROUP_ID: int = 123456  # Set group ID
RANK_ORDER: list[str] = []


def can_use_asyncio_run() -> bool:
    """
    Check if asyncio.run() can execute safely.

    :returns: True if no event loop runs in current thread.
    """
    try:
        asyncio.get_running_loop()
        return False
    except RuntimeError:
        return True


async def get_all_ranks() -> list[dict]:
    """
    Fetch group roles from API.

    :returns: List of rank dictionaries.
    """
    async with aiohttp.ClientSession() as session:
        return await fetch_roles(session, GROUP_ID)


all_the_ranks: list[dict] = []
if can_use_asyncio_run():
    all_the_ranks = asyncio.run(get_all_ranks())

if all_the_ranks:
    # Sort by numerical rank before extracting names
    sorted_ranks = sorted(all_the_ranks, key=lambda r: r.get("rank", 0))
    RANK_ORDER = [rank["name"] for rank in sorted_ranks]


def get_rank_index(rank: str) -> int:
    """
    Get rank index from list.

    :param rank: Name of rank to look up.
    :returns: List index or -1 if not found.
    """
    try:
        return RANK_ORDER.index(rank)
    except ValueError:
        return -1


GET_RANK_INDEX = get_rank_index


async def update_discord_presence(force: bool = False) -> None:
    """Update Discord bot activity status to display scanning metrics.

    :param force: Override update throttle interval when True.
    """
    if not bot.is_ready():
        return
    now = time.monotonic()
    if not force and now - bot._last_presence_update < bot.PRESENCE_UPDATE_INTERVAL:
        return
    async with bot.ROLE_PROGRESS_LOCK:
        done = sum(1 for r in bot.ROLE_PROGRESS.values() if r["done"])
        checked = sum(r["checked"] for r in bot.ROLE_PROGRESS.values())
    await bot.change_presence(
        activity=discord.Game(name=f"Monitoring roles | {done}/{len(RANK_ORDER)} done | {checked:,} users")
    )
    bot._last_presence_update = now


async def flush_role_change_queue(
    queue: list[str],
    channel_id: int | None,
    channel_name: str | None,
    queue_user_id: list[int] | None = None,
) -> None:
    """Flush queued change messages to specified Discord channel in batches.

    :param queue: List of individual message strings to flush.
    :param channel_id: Discord target channel ID.
    :param channel_name: Human-readable target channel identifier.
    :param queue_user_id: Associated user IDs for batch operations.
    """
    if not queue or not channel_id:
        return

    message = "".join(queue)
    queue.clear()

    try:
        if channel_id == JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL:
            asyncio.create_task(safe_send_and_pub(message, channel_id=channel_id, bot=bot))  # pyright: ignore[reportUndefinedVariable]
        else:
            asyncio.create_task(safe_send(message, channel_id=channel_id, bot=bot))  # pyright: ignore[reportUndefinedVariable]

        logger.info(f"📢 Flushed queued batch to {channel_name} ({channel_id})")
    except Exception as e:
        logger.error(f"Failed flushing queued messages to {channel_name} ({channel_id}): {e}")


def _process_single_user_delta(
    user_id: str,
    curr: set[int],
    prev: set[int],
    roles_dict: dict[int, str],
    user_names: dict[str, str],
    user_meta: dict[str, Any],
    channel_queues: dict[int, dict[str, Any]],
    now: float,
    suppression_window: float,
) -> dict[str, Any] | None:
    """Compute rank/role changes for a single user and queue announcement message.

    :param user_id: Target Roblox user ID string.
    :param curr: Current set of assigned role IDs.
    :param prev: Historical set of assigned role IDs.
    :param roles_dict: Translation map converting role ID to role name.
    :param user_names: Cache mapping User ID to display name.
    :param user_meta: Metadata map storing cooldown timestamps.
    :param channel_queues: Target state mapping channel ID to pending queues.
    :param now: Epoch timestamp of current execution run.
    :param suppression_window: Cooldown duration before re-processing changes.
    :returns: Evaluated change payload or None if ignored/suppressed.
    """
    added, removed = curr - prev, prev - curr
    suppressed_until = user_meta.get(user_id, {}).get("suppressed_until", 0)

    if (not added and not removed) or now < suppressed_until:
        return None

    curr_names = [roles_dict[r] for r in curr if r in roles_dict]
    prev_names = [roles_dict[r] for r in prev if r in roles_dict]

    curr_name = max(curr_names, key=get_rank_index) if curr_names else None  # pyright: ignore[reportUndefinedVariable]
    prev_name = max(prev_names, key=get_rank_index) if prev_names else None  # pyright: ignore[reportUndefinedVariable]

    curr_idx = get_rank_index(curr_name) if curr_name else -1  # pyright: ignore[reportUndefinedVariable]
    prev_idx = get_rank_index(prev_name) if prev_name else -1  # pyright: ignore[reportUndefinedVariable]

    if curr_idx != -1 and prev_idx != -1 and curr_idx != prev_idx:
        action_type = "promoted" if curr_idx > prev_idx else "demoted"
        action_text = f"was {action_type} to **{curr_name}** from **{prev_name}**"
    else:
        action_type = "changed"
        added_str = f"added into {[roles_dict.get(r, str(r)) for r in added]}" if added else ""
        removed_str = f"removed from {[roles_dict.get(r, str(r)) for r in removed]}" if removed else ""
        joiner = ", " if added and removed else ""
        action_text = f"role changes: {added_str}{joiner}{removed_str}"

    punc = "!" if action_type == "promoted" else "."
    username = user_names.get(user_id, user_id)
    link = f"[{username}](<https://www.roblox.com/users/{user_id}/profile>)"

    select_name = curr_name or prev_name
    channel_id, mention = get_rank_category_and_mention(select_name) if select_name else (TIME_TRACKING_CHANNEL_ID, "")  # pyright: ignore[reportUndefinedVariable]
    target_cid = channel_id or TIME_TRACKING_CHANNEL_ID

    message = f"{link} {action_text}{punc} {mention}".strip()
    logger.info(f"📢 {message}")

    channel_info = channel_queues.setdefault(
        target_cid,
        {
            "queue": [],
            "queue_user_id": [],
            "last_channel_name": getattr(bot.get_channel(target_cid), "name", "N/A"),
        },
    )
    q, quids = channel_info["queue"], channel_info["queue_user_id"]

    if sum(len(m) for m in q) + len(message) > MAX_CHARS_DISCORD:
        asyncio.create_task(
            flush_role_change_queue(list(q), target_cid, channel_info["last_channel_name"], list(quids))
        )
        q.clear()
        quids.clear()

    q.append(f"{message}\n")
    quids.append(int(user_id))

    user_meta.setdefault(user_id, {})["suppressed_until"] = now + suppression_window

    return {
        "user_id": int(user_id),
        "to_rank": next(iter(added), next(iter(curr), 0)),
        "from_rank": next(iter(removed), next(iter(prev), 0)),
        "timestamp": int(now),
        "group_id": GROUP_ID,
        "action_type": action_type,
    }


bot._process_single_user_delta = _process_single_user_delta


async def _collect_members_in_role(
    session: aiohttp.ClientSession, role: dict[str, Any]
) -> tuple[str, list[dict[str, Any]], int, str]:
    """Iterate through role members using async generator stream to protect heap footprint.

    :param session: Active aiohttp ClientSession instance.
    :param role: Dictionary containing raw Roblox role parameters.
    :returns: Tuple containing role name, fetched user objects, total checked count, and CSV user IDs string.
    """
    role_name, role_id, role_member_count = (str(role["name"]), int(role["id"]), int(role["memberCount"]))

    async with bot.ROLE_PROGRESS_LOCK:
        ROLE_PROGRESS[role_name] = {
            "checked": 0,
            "total": role_member_count,
            "done": False,
            "start": time.time(),
        }
    
    users_checked, local_csv, role_users = 0, "", []
    
    async def main(progress: Progress | None = None, task: Any = None):        
        async for user in fetch_users_in_role(session, GROUP_ID, role_id, role_member_count):
            users_checked += 1
            
            if progress and task is not None:
                progress.update(task, advance=1)

            async with bot.ROLE_PROGRESS_LOCK:
                ROLE_PROGRESS[role_name]["checked"] = users_checked

            if role_name in HIGH_RANKS:
                local_csv += ("," if local_csv else "") + str(user["userId"])
            role_users.append(user)
    
        async with bot.ROLE_PROGRESS_LOCK:
            ROLE_PROGRESS[role_name]["done"] = True
    
        still_running = {n: info for n, info in ROLE_PROGRESS.items() if not info["done"]}
        lines = []
        for name, info in still_running.items():
            checked, total = info["checked"], info["total"]
            rem = total - checked if total else None
            elapsed = time.time() - info["start"]
            ups = checked / elapsed if elapsed > 0 else 0.0
            eta = (
                f"~{datetime.timedelta(seconds=int(rem / ups))}" if checked and rem and ups > 0 else "?"
            )
            lines.append(
                f"- {name}: {checked}/{total if total else '?'} ({rem if rem else '?'} left, {eta} remaining)"
            )
    
        elapsed_total = time.time() - ROLE_PROGRESS[role_name]["start"]
        if still_running:
            logger.info(
                "⏳ Role finished: %s (%ss) | Still running:\n%s",
                role_name,
                elapsed_total,
                "\n".join(lines),
            )
        else:
            logger.info(f"✅ Role finished: {role_name} | No roles remaining")
    
        return role_name, role_users, users_checked, local_csv
    
    progress_format: list[TextColumn | BarColumn | TextColumn | TimeElapsedColumn] | None = (
        [
            TextColumn("[bold]Role:[/bold] {task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
        ]
        if IS_RICH_ENV
        else None
    )
    
    if not IS_RICH_ENV:
        return await main(progress=None, task=None)

    progress_context = Progress(*progress_format, refresh_per_second=4, transient=True) if IS_RICH_ENV else None
    with (progress_context if progress_context else nullcontext()) as progress:
        task = progress.add_task(role_name, total=role_member_count) if progress else None
        return await main(progress, task=None)


async def process_role_deltas(
    current_state: dict[str, set[int]], 
    previous_state: dict[str, set[int]], 
    roles_dict: dict[int, str],
    user_names: dict[str, str],
    user_meta: dict[str, Any],
    suppression_window: float = 300.0
) -> list[dict[str, Any]]:
    """Compare snapshot maps across runs and dispatch announcement queues.

    :param current_state: Map of user ID to current set of role IDs.
    :param previous_state: Map of user ID to previous set of role IDs.
    :param roles_dict: Translation map converting role ID to role name.
    :param user_names: Cache mapping UID to display name.
    :param user_meta: Metadata storage dict for suppression states.
    :param suppression_window: Cooldown duration in seconds.
    :returns: List of generated rank change records.
    """
    channel_queues: dict[int, dict[str, Any]] = {}
    now = time.time()
    changes_recorded = []

    all_uids = set(current_state.keys()) | set(previous_state.keys())
    for uid in all_uids:
        curr = current_state.get(uid, set())
        prev = previous_state.get(uid, set())
        
        delta = _process_single_user_delta(
            uid, curr, prev, roles_dict, user_names, user_meta, 
            channel_queues, now, suppression_window
        )
        if delta:
            changes_recorded.append(delta)

    for target_cid, info in channel_queues.items():
        if info["queue"]:
            await flush_role_change_queue(
                info["queue"], target_cid, info["last_channel_name"], info["queue_user_id"]
            )

    return changes_recorded


async def detect_changes_main() -> None:
    """Main execution loop for fetching Roblox roles, detecting deltas, and scheduling runs.

    Iterates through Roblox group roles, tracks state changes, triggers Discord flushes,
    and handles periodic polling.
    """
    logger.info("Starting detection loop...")
    async with aiohttp.ClientSession() as session:
        roles = await fetch_roles(session, GROUP_ID)
        roles_dict = {r["id"]: r["name"] for r in roles}
        
        # Implementation logic for fetching users per role and comparing states go here
        tasks = [_collect_members_in_role(session, role) for role in roles]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Error during role scan: {res}")


@bot.event
async def on_ready() -> None:
    """Event handler triggered when Discord client successfully authenticates."""
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id if bot.user else 'N/A'})")
    await update_discord_presence(force=True)


async def main() -> None:
    """Initialize bot runtime dependencies, background tasks, and start client."""
    if not TOKEN:
        logger.error("DISCORD_BOT_TOKEN missing.")
        sys.exit(1)
    
    async with bot:
        try:
            bot.load_extension("commands")  # This loads the commands from commands.py
        except Exception as e:
            logger.error(f"Failed to load commands extension: {e}")
            # sys.exit(1)

        try:
            bot.run(TOKEN)
            bot.loop.create_task(detect_changes_main())
        except Exception as e:
            logger.error(f"Bot crashed: {e}")
        # await bot.start()
    


if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot execution terminated by user.")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")