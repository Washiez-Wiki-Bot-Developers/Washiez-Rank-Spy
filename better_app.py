import asyncio
import json
import logging
import time
import os, sys
import aiohttp

import discord
from discord.ext import commands
import dotenv
from string import ascii_uppercase

from typing import Optional, Dict, Any, AsyncGenerator, cast
from io import BytesIO
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

console = Console()

from utils import safe_send, safe_send_and_pub, safe_reaction, safe_publish
# import wiki


from discord_report_error_logs import DiscordErrorHandler
import special_patches

import logging_setup

asyncio.set_event_loop(asyncio.new_event_loop())

global bot
intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="! ", intents=intents, reconnect=True)


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
MGMT_RANKS = ["Junior Director", "Senior Director", "Head Director"]
CORP_RANKS = ["Corporate Intern", "Junior Corporate", "Senior Corporate"]
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


role_monitor_task: asyncio.Task | None = None
AWAITING_SHUTDOWN = False
shutdown_scheduled = False

csv_jdplus_str = ""

# ASYNC JSON STORE
from asyncjsonstore import AsyncJSONStore

store = AsyncJSONStore("data.json")

load_data = store.load_data
save_data = store.save_data
# data = asyncio.run(load_data())
data: dict[str, Any] = {"user_roles": {}}

MAX_CHARS_DISCORD = 2000
LOOP_COUNT = 0
changes = {}
PRESENCE_UPDATE_INTERVAL = 10  # seconds
_last_presence_update = 0.0

from collections import defaultdict

ROLE_PROGRESS: dict[str, dict[str, int | bool]] = defaultdict(
    lambda: {"checked": 0, "total": 0, "done": False}
)
ROLE_PROGRESS_LOCK = asyncio.Lock()
bot.ROLE_PROGRESS_LOCK = ROLE_PROGRESS_LOCK

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

    async with ROLE_PROGRESS_LOCK:
        total_roles = len(ROLE_PROGRESS)
        done_roles = sum(1 for r in ROLE_PROGRESS.values() if r["done"])
        users_checked = sum(r["checked"] for r in ROLE_PROGRESS.values())

    activity_text = f"Monitoring roles | {done_roles}/{total_roles} done | {users_checked:,} users"

    try:
        await bot.change_presence(activity=discord.Game(name=activity_text))
        _last_presence_update = now
    except Exception as e:
        logger.debug(f"Presence update skipped: {e}")


async def to_roproxy(url: str) -> str:
    return url.replace("roblox.com", "roproxy.com")


retrieve_roproxy_url = to_roproxy


async def roblox_get_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    timeout: int = 10,
) -> Optional[Dict[str, Any]]:
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
    cursor = ""
    next_page_task: asyncio.Task | None = None

    logger.debug(f"Fetching users in role {role_id} of group {group_id}...")

    fetched = 0
    start = last_progress_update = time.monotonic()

    timeout = aiohttp.ClientTimeout(total=10)

    from rich.progress import Progress, TextColumn, BarColumn, TimeElapsedColumn

    async def fetch_page(c: str):
        await roblox_limiter.wait()

        url = (
            f"https://groups.roblox.com/v1/groups/{group_id}/roles/"
            f"{role_id}/users?limit=100&sortOrder=Asc"
        )
        if c:
            url += f"&cursor={c}"

        if ENABLE_ROPROXY_USAGE_FIRST_PRIORITY:
            url = await retrieve_roproxy_url(url)

        async with session.get(url, timeout=timeout) as r:
            if r.status == 429:
                await asyncio.sleep(1.2)  # cooldown
                proxy_url = await retrieve_roproxy_url(url)
                async with session.get(proxy_url, timeout=timeout) as pr:
                    pr.raise_for_status()
                    return await pr.json()

            r.raise_for_status()
            return await r.json()

    total = int(role_member_count) if role_member_count not in (None, "?") else None

    with Progress(
        TextColumn("Fetched {task.completed}/{task.total}"),
        BarColumn(),
        TextColumn("[{task.fields[ups]} u/s]"),
        TimeElapsedColumn(),
        refresh_per_second=4,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"Role {role_id}",
            total=total or 0,
            ups="0",
        )

        data = await fetch_page(cursor)

        while True:
            users = data["data"]
            prefetch_at = len(users) >> 1  # faster than //

            for i, user in enumerate(users):
                if i == prefetch_at and not next_page_task and data.get("nextPageCursor"):
                    next_page_task = asyncio.create_task(fetch_page(data["nextPageCursor"]))

                if i == prefetch_at and not next_page_task and data.get("nextPageCursor"):
                    next_page_task = asyncio.create_task(fetch_page(data["nextPageCursor"]))

                fetched += 1
                now = time.monotonic()

                # Throttle progress updates (~5x/sec max)
                if now - last_progress_update >= 0.2:
                    elapsed = now - start
                    ups = round(fetched / elapsed, 1) if elapsed else "?"

                    progress.update(
                        task,
                        completed=fetched,
                        ups=str(ups),
                    )
                    last_progress_update = now

                yield user

                # At 0%, 50%, 100% progress, update Discord presence
                if total:
                    progress_percent = (fetched / total * 100) if total > 0 else 0
                    if progress_percent in (0, 50, 100):
                        asyncio.create_task(update_discord_presence())
            cursor = data.get("nextPageCursor")
            if not cursor:
                break

            data = await next_page_task if next_page_task else await fetch_page(cursor)
            next_page_task = None
    logger.debug(f"Completed fetching users in role {role_id}.")


# -------------------- RANK ORDER --------------------
RANK_ORDER = {}
priority = 1
for group in (HIGH_RANKS, MID_RANKS, LOW_RANKS):
    for rank in group:
        RANK_ORDER[rank] = priority
        priority += 1


async def get_all_ranks():
    async with aiohttp.ClientSession() as session:
        return await fetch_roles(session, GROUP_ID)


all_ranks = asyncio.run(get_all_ranks())

print(all_ranks)
for rank in all_ranks:
    print(rank)
    RANK_ORDER[rank["name"]] = rank["rank"]
    print(f"rank added: {rank['name']} → {rank['rank']}")
    # if rank["name"] not in RANK_ORDER:

del get_all_ranks, all_ranks


def get_rank_index(rank: str) -> int:
    # return RANK_ORDER.get(rank, -1)
    # print(f"{rank}: {RANK_ORDER.get(rank, -1)}")
    return RANK_ORDER.get(rank, -1)


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
):
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


async def monitor_role_changes(disallowed_rank_names: Optional[list] = None):
    global LOOP_COUNT, AWAITING_SHUTDOWN, shutdown_scheduled, csv_jdplus_str, changes
    LOOP_COUNT += 1
    logger.info(f"🧼 Starting monitoring loop #{LOOP_COUNT}")

    asyncio.create_task(
        safe_send(
            f"🧼 Monitoring loop started\n-# disallowed_rank_names: `{disallowed_rank_names}`",
            TIME_TRACKING_CHANNEL_ID,
        )
    )

    await bot.wait_until_ready()

    async with aiohttp.ClientSession() as session:
        while True:
            start_time = time.time()
            users_checked_total = 0
            changes.clear()
            csv_jdplus_str = ""

            roles = await fetch_roles(session, GROUP_ID)
            if not roles:
                await asyncio.sleep(10)
                continue

            if disallowed_rank_names:
                roles = [r for r in roles if r["name"] not in disallowed_rank_names]

            roles_dict = {r["id"]: r["name"] for r in roles}
            data = await load_data()

            sem = asyncio.Semaphore(4)

            async def process_role(role: dict):
                async with sem:
                    asyncio.create_task(update_discord_presence())
                    logger.info(f"Processing role: {role['name']}")
                    role_name = role["name"]
                    role_id = role["id"]

                    async with ROLE_PROGRESS_LOCK:
                        ROLE_PROGRESS[role_name]["checked"] = 0
                        ROLE_PROGRESS[role_name]["total"] = role["memberCount"]
                        ROLE_PROGRESS[role_name]["done"] = False

                    enable_queue = role_name not in HIGH_RANKS
                    queue = []
                    last_channel_id = None
                    last_channel_name = None

                    role_changes = []
                    role_updates = {}
                    users_checked = 0
                    local_csv = ""

                    from rich.progress import Progress, TextColumn, BarColumn, TimeElapsedColumn

                    with Progress(
                        TextColumn("[bold]Role:[/bold] {task.description}"),
                        BarColumn(),
                        TextColumn("{task.completed}/{task.total}"),
                        TimeElapsedColumn(),
                        refresh_per_second=4,
                        transient=True,
                    ) as progress:
                        task = progress.add_task(
                            role_name,
                            total=role["memberCount"],
                        )

                        async for user in fetch_users_in_role(
                            session,
                            GROUP_ID,
                            role_id,
                            role["memberCount"],
                        ):
                            users_checked += 1
                            progress.update(task, advance=1)

                            async with ROLE_PROGRESS_LOCK:
                                ROLE_PROGRESS[role_name]["checked"] = users_checked

                            user_id = str(user["userId"])
                            current_rank = role_name
                            current_index = get_rank_index(current_rank)

                            if role_name in HIGH_RANKS:
                                local_csv += ("," if local_csv else "") + user_id

                            if user_id in data["user_roles"]:
                                prev_role_id = data["user_roles"][user_id]
                                prev_rank = roles_dict.get(prev_role_id)
                                prev_index = get_rank_index(prev_rank)

                                if prev_rank and current_index != prev_index and prev_index != -1:
                                    # action = "promoted" if current_index > prev_index else "demoted"
                                    if current_index > prev_index:
                                        action = "promoted"
                                    else:
                                        action = "demoted"

                                    if not special_patches.check_user(
                                        user, current_rank, prev_rank, action
                                    ):
                                        continue

                                    channel_id, mention = get_rank_channel(
                                        current_rank if action == "promoted" else prev_rank
                                    )
                                    channel = bot.get_channel(channel_id)
                                    channel_name = getattr(channel, "name", "N/A")

                                    message = (
                                        f"[{user['username']}](<https://www.roblox.com/users/{user['userId']}/profile>) "
                                        f"has been {action} from {prev_rank} to {current_rank} {mention}"
                                    )

                                    logger.info(f"📢 {message}")

                                    if enable_queue:
                                        if (
                                            sum(len(m) for m in queue) + len(message)
                                            > MAX_CHARS_DISCORD
                                        ):
                                            logger.info(
                                                f"📢 Releasing (aka sending) queued message to {channel.name} ({channel.id})"
                                            )
                                            await flush_role_change_queue(
                                                queue,
                                                last_channel_id,
                                                last_channel_name,
                                            )
                                        queue.append(message + "\n")
                                        last_channel_id = channel_id
                                        last_channel_name = channel_name
                                    else:
                                        asyncio.create_task(
                                            safe_send_and_pub(message, channel_id, bot=bot)
                                            if channel_id == JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL
                                            else safe_send(message, channel_id, bot=bot)
                                        )

                                    role_changes.append(
                                        {
                                            "username": user["username"],
                                            "user_id": user["userId"],
                                            "action": action,
                                            "from_rank": prev_rank,
                                            "to_rank": current_rank,
                                            "timestamp": time.time(),
                                        }
                                    )

                    await flush_role_change_queue(queue, last_channel_id, last_channel_name)

                    logger.info(f"Finished processing role: {role_name}")
                    async with ROLE_PROGRESS_LOCK:
                        ROLE_PROGRESS[role_name]["done"] = True

                        still_running = {
                            name: info for name, info in ROLE_PROGRESS.items() if not info["done"]
                        }

                    if still_running:
                        lines = []
                        for name, info in still_running.items():
                            checked = info["checked"]
                            total = info["total"]
                            remaining = total - checked if total else "?"
                            lines.append(f"- {name}: {checked}/{total} ({remaining} left)")

                        logger.info(
                            "⏳ Role finished: %s | Still running:\n%s",
                            role_name,
                            "\n".join(lines),
                        )
                    else:
                        logger.info(f"✅ Role finished: {role_name} | No roles remaining")

                    return (
                        role_name,
                        role_changes,
                        role_updates,
                        users_checked,
                        local_csv,
                    )

            tasks = [asyncio.create_task(process_role(role)) for role in roles]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Role task failed: {result}")
                    continue

                role_name, role_changes, role_updates, users_checked, local_csv = result

                users_checked_total += users_checked
                data["user_roles"].update(role_updates)

                if local_csv:
                    csv_jdplus_str += ("," if csv_jdplus_str else "") + local_csv

                changes[role_name] = {
                    "changes_count": len(role_changes),
                    "promotions": sum(c["action"] == "promoted" for c in role_changes),
                    "demotions": sum(c["action"] == "demoted" for c in role_changes),
                    "changes": role_changes,
                }

            await save_data(data)

            duration = time.time() - start_time
            summary = (
                f"## 📊 Cycle Summary\n"
                f"* Roles processed: {len(changes)}\n"
                f"* Users checked: {users_checked_total}\n"
                f"* Time: {duration:.2f}s\n"
                f"* Disallowed ranks: `{disallowed_rank_names}`"
            )

            asyncio.create_task(safe_send(summary, TIME_TRACKING_CHANNEL_ID, bot=bot))

            # asyncio.create_task(wiki.update_wiki_recent_rank_changes(changes))
            # asyncio.create_task(wiki.update_wiki_all_JDP(data))

            shutdown_scheduled = False
            if AWAITING_SHUTDOWN:
                shutdown_scheduled = True

            if shutdown_scheduled:
                LOOP_COUNT -= 1
                if LOOP_COUNT <= 0:
                    await bot.close()
                return True

            if sys.platform != "win32":
                await asyncio.sleep(180)


# -------------------- CHANNEL TESTING --------------------
async def test_single_channel_send_publish_react(channel):
    chan = bot.get_channel(channel) or await bot.fetch_channel(channel)
    if not chan:
        return False, None

    logger.debug(f"Testing channel: {chan.name} ({chan.id})")
    logger.debug(f"Channel type: {chan.type}")

    logger.debug("Sending test message...")
    success, msg = await safe_send(
        f"-# Testing bot permissions ({chan.name})",
        channel_id=chan.id,
        bot=bot,
        silent=True,
    )

    if not success or not msg:
        return False, None

    logger.debug("Adding reaction to test message...")
    await safe_reaction(msg, emoji="✅", bot=bot)

    if chan.type == discord.ChannelType.news:
        logger.debug("Publishing test message...")
        asyncio.create_task(safe_publish(msg.id, channel_id=chan.id, bot=bot))

    published_msg = msg

    # if chan.type == discord.ChannelType.news:
    #     published_msg = await safe_publish(msg.id, channel_id=chan.id)

    # try:
    #     await msg.delete()
    # except Exception:
    #     pass

    logger.info(f"{'.' * 10}\n✅ Channel test successful for {chan.name} ({chan.id})\n{'*' * 10}")

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

    await safe_send_and_pub(
        "-# ||Testing safe_send_and_pub to Junior Director+ channel.|| Please ignore.",
        channel_id=JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL,
        bot=bot,
        silent=True,
    )

    while True:
        try:
            quit_flag = await monitor_role_changes(disallowed_rank_names)
            if quit_flag:
                logger.info("Monitor loop requested shutdown.")
                sys.exit(0)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received.")
            await save_data(data)
            sys.exit(0)
        except Exception as e:
            logger.error(f"‼️ monitor_role_changes crashed: {e}")
            await asyncio.sleep(10)


# -------------------- BOT READY --------------------
@bot.event
async def on_ready():
    global role_monitor_task, data

    logger.info(f"Logged in as {bot.user}")
    await bot.change_presence(activity=discord.Game("Monitoring role changes"))

    data = await load_data()
    # await test_data_file_operations()

    channel = bot.get_channel(TIME_TRACKING_CHANNEL_ID)
    if channel:
        await channel.send("🧼 Bot is online and monitoring role changes!")

    if not role_monitor_task or role_monitor_task.done():
        logger.info("Starting monitor task...")
        restricted = []
        # restricted = LOW_RANKS.copy()
        # restricted += ["Shift Leader", "Supervisor", "Assistant Manager"]
        role_monitor_task = bot.loop.create_task(
            safe_monitor_wrapper(restricted),
            name="rank_monitor_task",
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
