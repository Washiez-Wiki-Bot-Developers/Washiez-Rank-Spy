import asyncio
import datetime
import logging
import os
import sys
import time
from string import ascii_uppercase
from typing import Any, AsyncGenerator, Set, cast

import aiohttp
import discord
import dotenv
from discord.ext import commands
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

import logging_setup
import special_patches

# import wiki
import wiki_update as wiki
from discord_report_error_logs import DiscordErrorHandler
from utils import (
    fetch_git_revision,
    safe_publish,
    safe_reaction,
    safe_send,
    safe_send_and_pub,
)

console = Console()

from utils import safe_send, safe_send_and_pub, safe_reaction, safe_publish, fetch_git_revision

# import wiki
import wiki_update as wiki

from discord_report_error_logs import DiscordErrorHandler
import special_patches

import logging_setup

asyncio.set_event_loop(asyncio.new_event_loop())


class MyBot(commands.Bot):
    ROLE_PROGRESS_LOCK: asyncio.Lock  # Tell Pylance this exists
    ROLE_PROGRESS: dict[str, dict[str, int | bool | float]]
    roblox_limiter: "RobloxLimiter"
    data_store: "AsyncJSONStore"


global bot
intents = discord.Intents.default()
intents.guilds = True
bot = MyBot(command_prefix="! ", intents=intents, reconnect=True)


logger: logging.Logger = logging_setup.setup_logging(
    rankspy_default_level=True,
    bot=bot,
    error_channel_id=os.getenv("TIME_TRACKING_CHANNEL_ID"),
)
logger = cast(logging.Logger, logger)

for name in logging.Logger.manager.loggerDict:
    if name.startswith("discord."):
        logging.getLogger(name).setLevel(logging.INFO)

logging.getLogger("async_json").setLevel(logging.INFO)

# ? Normal Text Log file logging
file_handler = logging.FileHandler("bot.log")
file_handler.setLevel(logging.DEBUG)  # ? Set to DEBUG to capture all logs
logger.addHandler(file_handler)


# Add DiscordErrorHandler
ERROR_LOG_CHANNEL = 1332185599859359774  # Replace with your desired channel ID
discord_error_handler = DiscordErrorHandler(bot, ERROR_LOG_CHANNEL)
discord_error_handler.setLevel(logging.ERROR)  # Only handle ERROR level logs
formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
discord_error_handler.setFormatter(formatter)
logger.addHandler(discord_error_handler)

dotenv.load_dotenv()

GROUP_ID = 10261023
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

ENABLE_ROPROXY_USAGE_FIRST_PRIORITY = False
ENABLE_MULTI_ROLE_MODE = True

# Channel IDs
CUSTOMER_HEAD_OP_CHANNEL = int(os.getenv("CUSTOMER_HEAD_OP_CHANNEL_ID", 1413641192712704100))
SHIFT_LEADER_GEN_MANAGER_CHANNEL = int(
    os.getenv("SHIFT_LEADER_GEN_MANAGER_CHANNEL_ID", 1413641215420924035)
)
JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL = int(
    os.getenv("JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL_ID", 1413641231908737135)
)
TIME_TRACKING_CHANNEL_ID = int(os.getenv("TIME_TRACKING_CHANNEL_ID", 1413620449912295645))


# Role mention IDs
LOW_RANK_ROLE_MENTION = "<@&1328338426713342023>"
MID_RANK_ROLE_MENTION = "<@&1328338484104134688>"
HIGH_RANK_ROLE_MENTION = "<@&1328338542132330506>"

DATA_FILE = "info.json"
file_lock = asyncio.Lock()

LOW_RANKS = ["Customer", "Trainee", "Junior Operator", "Senior Operator", "Head Operator"]
MID_RANKS = ["Shift Leader", "Supervisor", "Assistant Manager", "General Manager"]
MGMT_RANKS = ["Assistant Director", "Junior Director", "Senior Director", "Head Director"]
CORP_RANKS = ["Corporate Intern", "Junior Corporate", "Senior Corporate", "Head Corporate"]
LS_RANKS = [
    "Chief Human Resources Officer",
    "Chief Public Relations Officer",
    "Chief Operating Officer",
    "Chief Administrative Officer",
    "Developer",
    "Vice Chairman",
    "Chairman",
]
ET_RANKS = LOW_RANKS
ST_RANKS = MID_RANKS
HIGH_RANKS = MGMT_RANKS + CORP_RANKS + LS_RANKS
ALL_RANKS = ET_RANKS + MID_RANKS + HIGH_RANKS
ALL_M_RANKS_LIST = [ET_RANKS, ST_RANKS, MGMT_RANKS, CORP_RANKS, LS_RANKS]

role_monitor_task: asyncio.Task | None = None
AWAITING_SHUTDOWN = False
shutdown_scheduled = False

csv_jdplus_str = ""

with open("app.py", "r") as f:
    APP_FILE_HASH = hash(f.read())

# ASYNC JSON STORE
from asyncjsonstore import AsyncJSONStore

store = AsyncJSONStore("data.json")

bot.data_store = store

load_data = store.load_data
save_data = store.save_data
# data = asyncio.run(load_data())
data: dict[str, Any] = {"user_roles": {}}
# Per-user metadata for notification suppression and other metadata
if "user_meta" not in data:
    data["user_meta"] = {}

MAX_CHARS_DISCORD = 2000
LOOP_COUNT = 0
changes = []
PRESENCE_UPDATE_INTERVAL = 10  # seconds
_last_presence_update = 0.0

from collections import defaultdict

from collections import defaultdict
import asyncio

ROLE_PROGRESS: dict[str, dict[str, int | bool | float]] = defaultdict(
    lambda: {"checked": 0, "total": 0, "done": False, "start": 0.0}
)

ROLE_PROGRESS_LOCK: asyncio.Lock = asyncio.Lock()

bot.ROLE_PROGRESS_LOCK = ROLE_PROGRESS_LOCK
bot.ROLE_PROGRESS = ROLE_PROGRESS

ROBLOX_RPS = 6  # safe sustained rate
ROBLOX_BURST = 8  # allows prefetch overlap
ROBLOX_429_STREAK = 0


class RobloxLimiter:
    def __init__(self, rate, burst):
        self._rate = rate
        self._burst = burst
        self._sem = asyncio.Semaphore(burst)
        self._delay = 1 / rate

    async def wait(self):
        await self._sem.acquire()
        asyncio.get_running_loop().call_later(self._delay, self._sem.release)

    async def acquire(self):
        await self.wait()

    def semaphore_info(self) -> str:
        used = self._burst - self._sem._value
        return (
            f"Rate limit: {self._rate} req/sec\n"
            f"Burst limit: {self._burst}\n"
            f"Semaphore available permits: {self._sem._value}\n"
            f"In use: {used}/{self._burst}"
        )


global roblox_limiter
roblox_limiter = RobloxLimiter(ROBLOX_RPS, ROBLOX_BURST)
bot.roblox_limiter = roblox_limiter


async def update_discord_presence(force: bool = False):
    global _last_presence_update

    if not bot.is_ready():
        return

    now = time.monotonic()
    if not force and now - _last_presence_update < PRESENCE_UPDATE_INTERVAL:
        return

    async with bot.ROLE_PROGRESS_LOCK:
        total_roles = len(ROLE_PROGRESS)
        done_roles = sum(1 for r in ROLE_PROGRESS.values() if r["done"])
        users_checked = sum(r["checked"] for r in ROLE_PROGRESS.values())

    activity_text = f"Monitoring roles | {done_roles}/{len(RANK_ORDER)} done | {total_roles} roles (checked/checking), {users_checked:,} users checked"

    try:
        await bot.change_presence(activity=discord.Game(name=activity_text))
        _last_presence_update = now
    except Exception as e:
        logger.debug(f"Presence update skipped: {e}")


from utils import to_roproxy

retrieve_roproxy_url = to_roproxy


async def roblox_get_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    timeout: int = 10,
) -> dict[str, Any] | None:
    async def _get(u: str):
        await roblox_limiter.acquire()
        async with session.get(u, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            return r.status, await r.json()

    status, data = await _get(url)

    if status == 429:
        global ROBLOX_429_STREAK
        ROBLOX_429_STREAK = min(ROBLOX_429_STREAK + 1, 5)
        await asyncio.sleep(1.5 * ROBLOX_429_STREAK)

        proxy_url = await to_roproxy(url)
        logger.warning(f"429 → RoProxy retry: {proxy_url}")
        status, data = await _get(proxy_url)

    if status != 200:
        logger.error(f"Roblox GET failed ({status}) for {url}")
        return None

    return data


async def fetch_roles(session: aiohttp.ClientSession, group_id: int):
    url = f"https://groups.roblox.com/v1/groups/{group_id}/roles"
    data = await roblox_get_json(session, url)
    return data.get("roles", []) if data else []


# -------------------- USERS IN ROLE --------------------
async def fetch_users_in_role(
    session: aiohttp.ClientSession,
    group_id: int,
    role_id: int,
    role_member_count: int | None = None,
) -> AsyncGenerator[dict, None]:

    # 1. Config & State
    cursor = ""
    next_page_task: asyncio.Task | None = None
    fetched = 0
    start = last_progress_update = time.monotonic()
    timeout = aiohttp.ClientTimeout(total=10)

    total = int(role_member_count) if role_member_count not in (None, "?") else 0
    logger.debug(f"Fetching users in role {role_id} of group {group_id}...")

    # 2. Helper for API Requests
    async def fetch_page(c: str) -> dict:
        await roblox_limiter.wait()

        base_url = f"https://groups.roblox.com/v1/groups/{group_id}/roles/{role_id}/users?limit=100&sortOrder=Asc"
        url = f"{base_url}&cursor={c}" if c else base_url

        if ENABLE_ROPROXY_USAGE_FIRST_PRIORITY:
            url = await retrieve_roproxy_url(url)

        async with session.get(url, timeout=timeout) as response:
            # Handle standard success
            if response.status == 200:
                return await response.json()

            # Handle rate limits or server errors with proxy fallback
            if response.status == 429 or 500 <= response.status < 600:
                logger.warning(f"FUIR: Status {response.status}. Attempting RoProxy fallback.")
                proxy_url = await retrieve_roproxy_url(url)
                async with session.get(proxy_url) as proxy_res:
                    if proxy_res.status == 200:
                        return await proxy_res.json()
                    raise RuntimeError(f"RoProxy fallback failed with status {proxy_res.status}")

            raise RuntimeError(f"HTTP Error {response.status} for URL: {url}")

    # 3. Main Loop with Progress Bar
    with Progress(
        TextColumn("Fetched {task.completed}/{task.total}"),
        BarColumn(),
        TextColumn("[{task.fields[ups]} u/s]"),
        TimeElapsedColumn(),
        refresh_per_second=4,
        transient=True,
    ) as progress:
        task = progress.add_task(f"Role {role_id}", total=total, ups="0")

        # Initial fetch
        current_data = await fetch_page(cursor)

        while True:
            users = current_data.get("data", [])
            next_cursor = current_data.get("nextPageCursor")
            prefetch_threshold = len(users) >> 1  # 50% through current batch

            for i, user in enumerate(users):
                # Trigger prefetch for next page mid-way through current batch
                if i == prefetch_threshold and next_cursor and not next_page_task:
                    next_page_task = asyncio.create_task(fetch_page(next_cursor))

                fetched += 1
                now = time.monotonic()

                # Update UI at most 5 times per second
                if now - last_progress_update >= 0.2:
                    elapsed = now - start
                    ups = round(fetched / elapsed, 1) if elapsed > 0 else 0
                    progress.update(task, completed=fetched, ups=str(ups))
                    last_progress_update = now

                # Presence updates at major milestones
                if total > 0:
                    percent = (fetched / total) * 100
                    if percent in (0, 50, 100):
                        asyncio.create_task(update_discord_presence())

                yield user

            # Prepare for next iteration
            if not next_cursor:
                break

            # Use prefetched data or fetch now if task wasn't started
            current_data = await next_page_task if next_page_task else await fetch_page(next_cursor)
            next_page_task = None

    logger.debug(f"Completed fetching {fetched} users in role {role_id}.")


# -------------------- RANK ORDER --------------------
RANK_ORDER = {}
priority = 1
# for group in (HIGH_RANKS, MID_RANKS, LOW_RANKS):
#     for rank in group:
#         RANK_ORDER[rank] = priority
#         priority += 1


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


async def get_all_ranks():
    async with aiohttp.ClientSession() as session:
        return await fetch_roles(session, GROUP_ID)


all_the_ranks: list = []
if can_use_asyncio_run():
    all_the_ranks = asyncio.run(get_all_ranks())

if all_the_ranks:
    # print(all_ranks)
    for rank in all_the_ranks:
        # print(rank)
        RANK_ORDER[rank["name"]] = rank["rank"]
        # print(f"rank added: {rank['name']} → {rank['rank']}")
        # if rank["name"] not in RANK_ORDER:

global GET_RANK_INDEX


def GET_RANK_INDEX(rank: str) -> int:
    # return RANK_ORDER.get(rank, -1)
    # print(f"{rank}: {RANK_ORDER.get(rank, -1)}")
    return RANK_ORDER.get(rank, -1)


get_rank_index = GET_RANK_INDEX

for rank in LOW_RANKS + MID_RANKS + HIGH_RANKS:
    if rank not in RANK_ORDER:
        RANK_ORDER[rank] = -1
    # get_rank_index(rank)


def get_rank_channel(rank: str):
    if rank in LOW_RANKS:
        return CUSTOMER_HEAD_OP_CHANNEL, LOW_RANK_ROLE_MENTION
    if rank in MID_RANKS:
        return SHIFT_LEADER_GEN_MANAGER_CHANNEL, MID_RANK_ROLE_MENTION
    if rank in HIGH_RANKS:
        return JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL, HIGH_RANK_ROLE_MENTION
    return None, None


async def flush_role_change_queue(
    queue: list[str],
    channel_id: int | None,
    channel_name: str | None,
    queue_user_id: list[int] | None = None,
):
    """
    # flush_role_change_queue
    Sends a list of message queued in one channel

    :param queue: (list[str]) The list of messages to flush as a single batch.
    :param channel_id: (int | None) The channel ID to send the batch to. If None, the function will return without sending.
    :param channel_name: (str | None) The name of the channel (for logging purposes). Can be None if channel_id is None.
    :param queue_user_id: (list[int] | None, optional) The list of user IDs associated with the queued messages. This is for chains. Defaults to None. Can be found otherwise.
    """
    if not queue or not channel_id:
        return

    message = "".join(queue)
    queue.clear()

    print(f"Flushing queued message to {channel_name} ({channel_id})")
    print(message)
    print(queue)

    try:
        if channel_id == JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL:
            asyncio.create_task(safe_send_and_pub(message, channel_id=channel_id, bot=bot))
        else:
            asyncio.create_task(safe_send(message, channel_id=channel_id, bot=bot))

        # asyncio.create_task(changes_txt(message))

        logger.info(f"📢 Flushed queued batch to {channel_name} ({channel_id})")
    except Exception as e:
        logger.error(f"Failed flushing queued messages to {channel_name} ({channel_id}): {e}")


import copy


async def _init_rank_order(session: Any) -> None:
    """Initialize RANK_ORDER dictionary from API data asynchronously.

    :param session: Active aiohttp ClientSession instance.
    """
    try:
        all_ranks = await fetch_roles(session, GROUP_ID)
        for rank in all_ranks:
            RANK_ORDER[rank["name"]] = rank["rank"]
        global RANKS_INITIALIZED
        RANKS_INITIALIZED = True
    except Exception as e:
        logger.exception(f"Failed initializing ranks: {e}")


async def _collect_members_in_role(
    session: Any, role: dict[str, Any]
) -> tuple[str, list[dict[str, Any]], int, str]:
    """Iterate through role members using async generator stream to protect heap footprint.

    :param session: Active aiohttp ClientSession instance.
    :param role: dictionary containing role data attributes.
    :returns: tuple containing role name, collected user objects, checked count, and high-rank CSV string.
    """
    from rich.progress import (
        BarColumn,
        Progress,
        TextColumn,
        TimeElapsedColumn,
    )

    r_name, r_id, total_cnt = role["name"], role["id"], role["memberCount"]

    async with bot.ROLE_PROGRESS_LOCK:
        ROLE_PROGRESS[r_name] = {
            "checked": 0,
            "total": total_cnt,
            "done": False,
            "start": time.time(),
        }

    users_checked, local_csv, role_users = 0, "", []
    p_format = [
        TextColumn("[bold]Role:[/bold] {task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
    ]

    with Progress(*p_format, refresh_per_second=4, transient=True) as progress:
        task = progress.add_task(r_name, total=total_cnt)
        # Streaming generator pipeline optimization minimizes active memory overhead
        async for user in fetch_users_in_role(session, GROUP_ID, r_id, total_cnt):
            users_checked += 1
            progress.update(task, advance=1)

            async with bot.ROLE_PROGRESS_LOCK:
                ROLE_PROGRESS[r_name]["checked"] = users_checked

            if r_name in HIGH_RANKS:
                local_csv += ("," if local_csv else "") + str(user["userId"])
            role_users.append(user)

    async with bot.ROLE_PROGRESS_LOCK:
        ROLE_PROGRESS[r_name]["done"] = True

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

    elapsed_total = time.time() - ROLE_PROGRESS[r_name]["start"]
    if still_running:
        logger.info(
            "⏳ Role finished: %s (%ss) | Still running:\n%s",
            r_name,
            elapsed_total,
            "\n".join(lines),
        )
    else:
        logger.info(f"✅ Role finished: {r_name} | No roles remaining")

    return r_name, role_users, users_checked, local_csv


def _process_single_user_delta(
    uid: str,
    curr: set[int],
    prev: set[int],
    roles_dict: dict[int, str],
    user_names: dict[str, str],
    user_meta: dict[str, Any],
    channel_queues: dict[int, dict[str, Any]],
    now: float,
    suppression_window: float,
) -> dict[str, Any] | None:
    """Compute structural differential states for an individual user and populate buffers.

    :param uid: Roblox target string ID.
    :param curr: Runtime role integer identifiers list.
    :param prev: Stored backup database identifiers snapshot.
    :param roles_dict: Translation table resolving role ID to visual strings.
    :param user_names: Cache of profile metadata display handles.
    :param user_meta: Mutable control tracking system block thresholds.
    :param channel_queues: Storage routing maps separated by specific targets.
    :param now: Precise epoch clock calculation mark.
    :param suppression_window: Delta timing delay thresholds.
    :returns: dictionary describing raw tracking block elements if change matches criteria, otherwise None.
    """
    added, removed = curr - prev, prev - curr
    if not added and not removed or now < user_meta.get(uid, {}).get("suppressed_until", 0):
        return None

    curr_names = [roles_dict[r] for r in curr if r in roles_dict]
    prev_names = [roles_dict[r] for r in prev if r in roles_dict]

    curr_name = max(curr_names, key=get_rank_index) if curr_names else None
    prev_name = max(prev_names, key=get_rank_index) if prev_names else None

    current_index = get_rank_index(curr_name) if curr_name else -1
    prev_index = get_rank_index(prev_name) if prev_name else -1

    if current_index == -1 or prev_index == -1 or current_index == prev_index:
        added_role_names = [roles_dict.get(role_id, str(role_id)) for role_id in added]
        removed_role_names = [roles_dict.get(role_id, str(role_id)) for role_id in removed]

        action_text = f"role changes: {f'added into {added_role_names}' if added_role_names else ''}{f', ' if added_role_names and removed_role_names else ''}{f'removed from {removed_role_names}' if removed_role_names else ''}"
        action_type = "changed"
    else:
        action_type = "promoted" if current_index > prev_index else "demoted"
        action_text = f"was {action_type} to **{curr_name}** from **{prev_name}**"

    punc = "!" if action_type == "promoted" else "."

    username = user_names.get(uid, f"{uid}")
    link = f"[{username}](<https://www.roblox.com/users/{uid}/profile>)"

    select_name = curr_name or prev_name
    channel_id, mention = (
        get_rank_channel(select_name) if select_name else (TIME_TRACKING_CHANNEL_ID, "")
    )

    message = f"{link} {action_text}{punc} {mention}".strip()
    logger.info(f"📢 {message}")

    target_cid = channel_id or TIME_TRACKING_CHANNEL_ID

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
            flush_role_change_queue(
                list(q), channel_id, channel_info["last_channel_name"], list(quids)
            )
        )
        q.clear()
        quids.clear()

    q.append(message + "\n")
    quids.append(int(uid))

    user_meta.setdefault(uid, {})["suppressed_until"] = now + suppression_window

    return {
        "user_id": int(uid),
        "to_rank": next(iter(added)) if added else (next(iter(curr)) if curr else 0),
        "from_rank": next(iter(removed)) if removed else (next(iter(prev)) if prev else 0),
        "timestamp": int(now),
        "group_id": GROUP_ID,
        "action_type": action_type,
    }


async def monitor_role_changes(
    disallowed_rank_names: list[str] | None = None,
    stop_after_one_loop: bool = False,
    test_mode: bool = False,
) -> Any:
    """Core tracking orchestration pipeline assessing live roles metrics against database maps.

    :param disallowed_rank_names: Optional filtering list for ranks to skip entirely.
    :param stop_after_one_loop: If True, halts background routine execution after single iteration.
    :param test_mode: If True, bypasses standard interval controls and returns raw metrics payload.
    :returns: Operational analytics summary structure if testing, else boolean true upon completion.
    """
    global \
        LOOP_COUNT, \
        AWAITING_SHUTDOWN, \
        shutdown_scheduled, \
        csv_jdplus_str, \
        changes, \
        RANKS_INITIALIZED, \
        users_checked_total
    LOOP_COUNT += 1
    logger.info(f"🧼 Starting monitoring loop #{LOOP_COUNT}")

    disallowed_rank_names = disallowed_rank_names or []
    if "Member" not in disallowed_rank_names:
        disallowed_rank_names.append("Member")

    RANKS_INITIALIZED = False
    AWAITING_SHUTDOWN = test_mode if test_mode else stop_after_one_loop

    asyncio.create_task(
        safe_send(
            f"🧼 Monitoring loop started\n-# disallowed_rank_names: `{disallowed_rank_names}`",
            TIME_TRACKING_CHANNEL_ID,
        )
    )

    if not bot.is_ready():
        logger.warning("Bot not ready, waiting before starting monitor loop...")
    await bot.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        if not RANKS_INITIALIZED:
            await _init_rank_order(session)

        while True:
            start_time, users_checked_total, csv_jdplus_str = (time.time(), 0, "")
            changes.clear()

            roles = await fetch_roles(session, GROUP_ID)
            if not roles:
                await asyncio.sleep(10)
                continue

            roles = [role for role in roles if role["name"] not in disallowed_rank_names]
            roles_dict = {role["id"]: role["name"] for role in roles}
            data = await load_data()
            sem = asyncio.Semaphore(4)

            channel_queues: dict[int, dict[str, Any]] = {}
            user_meta = data.get("user_meta", {})
            now, suppression_window = time.time(), 49 * 24 * 3600
            notified_users: set[str] = set()
            role_updates_final: dict[str, list[int]] = {}
            role_name_to_id = {role["name"]: role["id"] for role in roles}
            user_names: dict[str, str] = {}
            role_time_used: dict[str, float] = {}

            prev_user_roles: dict[str, set[int]] = {}
            for uid, usr_role_val in data.get("user_roles", {}).items():
                try:
                    if isinstance(usr_role_val, list):
                        prev_user_roles[uid] = set(int(x) for x in usr_role_val)
                    elif isinstance(usr_role_val, (int, float)):
                        prev_user_roles[uid] = {int(usr_role_val)}
                    elif isinstance(usr_role_val, str):
                        if usr_role_val.isdigit():
                            prev_user_roles[uid] = {int(usr_role_val)}
                        else:
                            found = next(
                                (rid for rid, rname in roles_dict.items() if rname == usr_role_val),
                                None,
                            )
                            prev_user_roles[uid] = {found} if found is not None else set()
                except Exception:
                    prev_user_roles[uid] = set()

            changes_lock = asyncio.Lock()

            async def process_role(role: dict[str, Any]) -> Any:
                global users_checked_total, csv_jdplus_str

                async with sem:
                    asyncio.create_task(update_discord_presence())
                    logger.info(f"Processing role: {role['name']}")

                    resp = await _collect_members_in_role(session, role)
                    role_name, role_users, users_checked, role_csv = resp

                    async with changes_lock:
                        users_checked_total += users_checked
                        if role_csv:
                            csv_jdplus_str += ("," if csv_jdplus_str else "") + role_csv

                    role_id = role_name_to_id.get(role_name)
                    if role_id is not None:
                        for user in role_users:
                            uid = str(user["userId"])
                            user_names[uid] = user.get("username", user.get("displayName", uid))

                            curr = {role_id}
                            prev = prev_user_roles.get(uid, set())

                            change_obj = _process_single_user_delta(
                                uid,
                                curr,
                                prev,
                                roles_dict,
                                user_names,
                                user_meta,
                                channel_queues,
                                now,
                                suppression_window,
                            )

                            if change_obj:
                                async with changes_lock:
                                    changes.append(change_obj)
                                    notified_users.add(uid)

                            if curr:
                                async with changes_lock:
                                    if uid not in role_updates_final:
                                        role_updates_final[uid] = []
                                    if role_id not in role_updates_final[uid]:
                                        role_updates_final[uid].append(role_id)
                    return resp

            tasks = [asyncio.create_task(process_role(role)) for role in roles]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for resp in results:
                if isinstance(resp, Exception):
                    logger.error(f"Role task failed: {resp}")

            # Standardize structural records configuration maps cleanly
            cleaned_updates = {}
            for uid, roles_list in role_updates_final.items():
                cleaned_updates[str(uid)] = sorted(list(set(roles_list)))

            # Flush standard notifications down downstream queues
            for cid, info in channel_queues.items():
                await flush_role_change_queue(
                    info["queue"],
                    cid,
                    info.get("last_channel_name"),
                    info.get("queue_user_id"),
                )

            # Persist accurate mappings directly to disk store
            data["user_roles"] = cleaned_updates
            data["user_meta"] = user_meta
            await save_data(data)

            from interchange import create_RGRCDBINIC_contact_data

            payload_raw = create_RGRCDBINIC_contact_data(changes, source="TMM12", is_json=False)

            duration = time.time() - start_time
            summary = (
                f"## 📊 Cycle Summary\n"
                f"* Roles processed: {len(roles)}\n"
                f"* Users checked: {users_checked_total}\n"
                f"* Time: {duration:.2f}s\n"
                f"* Disallowed ranks: `{disallowed_rank_names}`"
            )
            asyncio.create_task(safe_send(summary, TIME_TRACKING_CHANNEL_ID, bot=bot))

            if test_mode:
                return {
                    "total_duration_s": duration,
                    "users_checked_total": users_checked_total,
                    "total_users_in_group": sum(r["memberCount"] for r in roles),
                    "roles_processed": len(roles),
                    "changes": changes,
                    "role_time_used": role_time_used,
                }

            shutdown_scheduled = AWAITING_SHUTDOWN
            try:
                with open("app.py", "r") as f:
                    if hash(f.read()) != APP_FILE_HASH:
                        logger.warning("app.py file changed during execution. Scheduling shutdown.")
                        shutdown_scheduled = True
            except Exception:
                pass

            if shutdown_scheduled:
                LOOP_COUNT -= 1
                if LOOP_COUNT <= 0:
                    await bot.close()
                return True

            await asyncio.sleep(180)


# -------------------- CHANNEL TESTING --------------------
async def test_single_channel_send_publish_react(channel):
    chan = bot.get_channel(channel) or await bot.fetch_channel(channel)
    if not chan:
        return False, None

    chan_name = getattr(chan, "name", None) or "Unnamed"
    chan_type = getattr(chan, "type", None) or "Unknown (Private Channel?)"
    logger.debug("Testing channel: %s (%s)", chan_name, chan.id)
    logger.debug("Channel type: %s", chan_type)

    logger.debug("Sending test message...")
    success, msg = await safe_send(
        f"-# Testing bot permissions ({chan_name})",
        channel_id=chan.id,
        bot=bot,
        silent=True,
    )

    if not success or not msg:
        return False, None

    logger.debug("Adding reaction to test message...")
    await safe_reaction(msg, emoji="✅", bot=bot)

    if getattr(chan, "type", None) == discord.ChannelType.news:
        logger.debug("Publishing test message...")
        asyncio.create_task(safe_publish(msg.id, channel_id=chan.id, bot=bot))

    published_msg = msg

    # if chan.type == discord.ChannelType.news:
    #     published_msg = await safe_publish(msg.id, channel_id=chan.id)

    # try:
    #     await msg.delete()
    # except Exception:
    #     pass

    logger.info(f"{'.' * 10}\n✅ Channel test successful for {chan_name} ({chan.id})\n{'*' * 10}")

    return True, msg


async def test_channel_send_publish(channels):
    results = []
    for cid in channels:
        results.append(await test_single_channel_send_publish_react(cid))
    logger.info(f"{'.' * 20}\n✅ Channel test completed\n{'*' * 20}")
    return results


# -------------------- DATA TEST --------------------
async def test_data_file_operations():
    original = await load_data()

    test = {"user_roles": {"1": 1, "2": 2}}
    await save_data(test, "test.json")
    loaded = await load_data("test.json")
    assert test["user_roles"] == loaded["user_roles"]

    os.remove("test.json")
    await save_data(original)
    return True


# -------------------- SAFE WRAPPER --------------------
async def safe_monitor_wrapper(disallowed_rank_names=None):
    logger.debug("Running safe monitor wrapper...")

    await test_channel_send_publish(
        [
            TIME_TRACKING_CHANNEL_ID,
            CUSTOMER_HEAD_OP_CHANNEL,
            SHIFT_LEADER_GEN_MANAGER_CHANNEL,
            JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL,
        ]
    )

    # await safe_send_and_pub(
    #     "-# ||Testing safe_send_and_pub to Junior Director+ channel.|| Please ignore.",
    #     channel_id=JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL,
    #     bot=bot,
    #     silent=True,
    # )

    stop_after_one_loop = "--run-once" in sys.argv

    while True:
        try:
            quit_flag = await monitor_role_changes(
                disallowed_rank_names, stop_after_one_loop=stop_after_one_loop
            )
            if quit_flag:
                logger.info("Monitor loop requested shutdown.")
                sys.exit(0)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received.")
            await save_data(data)

            sys.exit(0)
        except Exception as e:
            logger.error(f"‼️ monitor_role_changes crashed: {e}", exc_info=True)
            await asyncio.sleep(10)


# -------------------- BOT READY --------------------


@bot.event
async def on_ready():
    # Only use 'global' if you are re-assigning these variables in this scope
    global role_monitor_task, data

    # 1. Initialization & Logging
    git_hash = fetch_git_revision()

    logger.info(f"Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game("Monitoring role changes"))

    print("\n\n")
    logger.info(f"WELCOME TO RANKSPY!")
    logger.info(f"Latest Git Commit ID for app.py: {git_hash} + Further non-commited revisions.")
    logger.info(f"App file hash: {APP_FILE_HASH}")
    print("\n\n")

    # 2. Data Loading
    data = await load_data()

    # 3. Notification
    channel = bot.get_channel(TIME_TRACKING_CHANNEL_ID)
    if isinstance(channel, discord.abc.Messageable):
        await channel.send("🧼 Bot is online and monitoring role changes!")

    # 4. Background Task Management
    # Ensure task only starts if ~~we are in the main execution (or run by SOCKS) and~~ task isn't already running
    should_start_task = (
        # __name__ == "__main__" and
        role_monitor_task is None or role_monitor_task.done()
    )

    if should_start_task:
        logger.info("Starting monitor task...")

        logger.info("Starting monitor_role_changes task restricted to HO+...")
        restricted = []
        # restricted.extend(LOW_RANKS)
        # restricted.extend(MID_RANKS)
        # restricted.remove("Head Operator")
        # restricted.remove("Customer")  # Incase of demotions
        restricted.append("Member")

        # Build restricted list from MID_RANKS
        # Easily extendable by adding lists: restricted = MID_RANKS + LOW_RANKS
        # restricted = list(MID_RANKS)
        from interchange import start_server

        bot.loop.create_task(start_server(), name="interchange_server")
        role_monitor_task = bot.loop.create_task(
            safe_monitor_wrapper(restricted), name="rank_monitor_task"
        )


# -------------------- ENTRYPOINT --------------------
if __name__ == "__main__":
    if not TOKEN:
        logger.error("DISCORD_BOT_TOKEN missing.")
        sys.exit(1)

    try:
        bot.load_extension("commands")  # This loads the commands from commands.py
    except Exception as e:
        logger.error(f"Failed to load commands extension: {e}")
        sys.exit(1)

    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
