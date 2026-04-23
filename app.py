<<<<<<< HEAD
import asyncio
import json
import logging
import time
import os
from typing import cast
import aiohttp

import discord
from discord.ext import commands
import dotenv

from discord_report_error_logs import DiscordErrorHandler
from utils import safe_send, safe_send_and_pub, safe_reaction, safe_publish
import special_patches

asyncio.set_event_loop(asyncio.new_event_loop())

intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="! ", intents=intents, reconnect=True)

# Set up logging
import logging_setup

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

# Channel IDs
CUSTOMER_HEAD_OP_CHANNEL = 1413577828498276474
SHIFT_LEADER_GEN_MANAGER_CHANNEL = 1413577873159229481
JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL = 1413578146120204298
TIME_TRACKING_CHANNEL_ID = 1413620449912295645

# Role mention IDs
LOW_RANK_ROLE_MENTION = "<@&1328338426713342023>"
MID_RANK_ROLE_MENTION = "<@&1328338484104134688>"
HIGH_RANK_ROLE_MENTION = "<@&1328338542132330506>"

DATA_FILE = "info.json"
file_lock = asyncio.Lock()

LOW_RANKS = [
    "Customer",
    "Trainee",
    "Junior Operator",
    "Senior Operator",
    "Head Operator",
]
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

ENABLE_ROPROXY_USAGE_FIRST_PRIORITY = False


async def load_data():
    async with file_lock:
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("Data file missing or corrupt. Creating fresh.")
            return {"user_roles": {}}


async def save_data(data):
    async with file_lock:
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(data, f)
            logger.info("Data saved.")
        except Exception as e:
            logger.error(f"Failed saving data: {e}")


def get_rank_category_and_mention(rank_name):
    if rank_name in LOW_RANKS:
        return CUSTOMER_HEAD_OP_CHANNEL, LOW_RANK_ROLE_MENTION
    elif rank_name in MID_RANKS:
        return SHIFT_LEADER_GEN_MANAGER_CHANNEL, MID_RANK_ROLE_MENTION
    elif rank_name in HIGH_RANKS:
        return JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL, HIGH_RANK_ROLE_MENTION
    return None, None


def get_rank_index(rank_name):
    if rank_name in LOW_RANKS:
        return LOW_RANKS.index(rank_name)
    elif rank_name in MID_RANKS:
        return len(LOW_RANKS) + MID_RANKS.index(rank_name)
    elif rank_name in HIGH_RANKS:
        return len(LOW_RANKS) + len(MID_RANKS) + HIGH_RANKS.index(rank_name)
    return -1


async def retrieve_roproxy_url(url):
    url = url.replace("roblox.com", "roproxy.com")
    return url


async def fetch_roles(session, group_id):
    base_url = f"https://groups.roblox.com/v1/groups/{group_id}/roles"
    try:
        async with session.get(
            base_url, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status == 429:
                # Rate limited — switch to RoProxy
                roproxy_url = await retrieve_roproxy_url(base_url)
                logger.warning(f"Rate limited. Retrying with RoProxy: {roproxy_url}")
                async with session.get(
                    roproxy_url, timeout=aiohttp.ClientTimeout(total=10)
                ) as proxy_response:
                    if proxy_response.status != 200:
                        logger.error(f"RoProxy failed: {proxy_response.status}")
                        return []
                    data = await proxy_response.json()
                    return data.get("roles", [])
            elif response.status != 200:
                logger.error(f"Failed to fetch roles: {response.status}")
                return []
            data = await response.json()
            return data.get("roles", [])
    except Exception as e:
        logger.error(f"Error fetching roles: {e}")
        return []


async def fetch_users_in_role(
    session: aiohttp.ClientSession,
    group_id: int,
    role_id: int,
    role_member_count: int | None = None,
):
    cursor = ""
    next_page_task: asyncio.Task | None = None

    async def fetch_page(cursor: str):
        url = f"https://groups.roblox.com/v1/groups/{group_id}/roles/{role_id}/users?limit=100&sortOrder=Asc"
        if cursor:
            url += f"&cursor={cursor}"

        if ENABLE_ROPROXY_USAGE_FIRST_PRIORITY:
            url = await retrieve_roproxy_url(url)

        tries = 0
        while True:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status not in (200, 429) or str(response.status).startswith("5"):
                    raise RuntimeError(f"HTTP {response.status}")

                data = await response.json()

                if response.status == 429 or str(response.status).startswith("5"):
                    if str(response.status).startswith("5"):
                        logger.warning(
                            "FUIR: 5xx error. This might be a sign of servers failing or block."
                        )
                        tries += 1
                        if tries > 3:
                            raise RuntimeError("Too many 5xx errors, aborting.")
                        continue
                    roproxy_url = await retrieve_roproxy_url(url)
                    async with session.get(roproxy_url) as proxy_response:
                        if proxy_response.status != 200:
                            raise RuntimeError("RoProxy failed")
                        data = await proxy_response.json()

                return data

    # Initial fetch (blocking)
    data = await fetch_page(cursor)

    while True:
        users = data["data"]
        total_users = len(users)
        half_index = total_users // 2

        # for index, user in enumerate(users):
        #     # Start fetching next page once half is yielded
        #     if index == half_index and data.get("nextPageCursor") and next_page_task is None:
        #         next_page_task = asyncio.create_task(fetch_page(data["nextPageCursor"]))

        #     yield user

        # No more pages
        if not data.get("nextPageCursor"):
            break

        # Wait for prefetched page (or fetch now if not started)
        if next_page_task:
            data = await next_page_task
            next_page_task = None
        else:
            data = await fetch_page(data["nextPageCursor"])

    return users


async def monitor_role_changes(disallowed_rank_names=None):
    async with aiohttp.ClientSession() as session:
        while True:
            start_time = time.time()
            logger.info("🔎 Checking for role changes...")

            roles = await fetch_roles(session, GROUP_ID)
            if not roles:
                await asyncio.sleep(10)
                continue

            if disallowed_rank_names:
                logger.debug(
                    "Removing roles from fetched list so only goes through the restricted role."
                )
                # iterate over role names directly
                for role_name in disallowed_rank_names:
                    # find the role object in roles that matches this name
                    roles = [r for r in roles if r["name"] != role_name]

                logger.debug(
                    f"Removed roles to restricted set of roles. \nRestricted for:{disallowed_rank_names}\nWe have {roles}"
                )

            roles_dict = {role["id"]: role["name"] for role in roles}
            data = await load_data()

            roles_processed = 0
            users_checked = 0

            for role in roles:
                logger.info(f"Processing role: {role['name']} (ID: {role['id']})")
                users = await fetch_users_in_role(
                    session, GROUP_ID, role["id"], role_member_count=role["memberCount"]
                )
                for user in users:
                    user_id = str(user["userId"])
                    current_rank = role["name"]
                    current_index = get_rank_index(current_rank)

                    if user_id in data["user_roles"]:
                        prev_role_id = data["user_roles"][user_id]
                        prev_role_name = roles_dict.get(prev_role_id, "Unknown")
                        prev_index = get_rank_index(prev_role_name)

                        if (
                            current_index != -1
                            and prev_index != -1
                            and current_index != prev_index
                        ):
                            action = (
                                "promoted" if current_index > prev_index else "demoted"
                            )
                            channel_id, mention = get_rank_category_and_mention(
                                current_rank
                            )

                            if not special_patches.check_user(
                                user, current_rank, prev_role_name, action
                            ):
                                continue

                            if (prev_role_name in HIGH_RANKS) and action == "demoted":
                                logger.info(
                                    f"!! Demoted HIGH_RANK: {user['username']} to {current_rank}"
                                )
                                channel_id, mention = get_rank_category_and_mention(
                                    prev_role_name
                                )

                            if channel_id:
                                channel = bot.get_channel(channel_id)
                                if channel:
                                    profile_link = f"[{user['username']}](<https://www.roblox.com/users/{user['userId']}/profile>)"  # ({user['userId']})"
                                    message = f"{profile_link} has been {action} from {prev_role_name} to {current_rank} {mention}"
                                    # message_obj = await channel.send(message)
                                    message_obj = await safe_send_and_pub(
                                        message=message, channel_id=channel_id, bot=bot
                                    )

                                    data["user_roles"][user_id] = role["id"]

                                    # try:
                                    #     await message_obj.publish()
                                    # except discord.Forbidden as e:
                                    #     print(f"Failed to publish: {e}")
                                    # except discord.HTTPException as e:
                                    #     print(f"HTTP error during publish: {e}")
                                    logger.info(f"📢 {message}")
                    data["user_roles"][user_id] = role["id"]
                    users_checked += 1
                roles_processed += 1

            await save_data(data)
            end_time = time.time()
            duration = end_time - start_time

            summary = (
                f"## 📊 **Cycle Summary**\n"
                f"* ✅ Processed {roles_processed}/{len(roles)} roles.\n"
                f"* 👥 Checked **{users_checked}** user entries.\n"
                f"* ⏱ Time taken: **{duration:.2f} seconds**.\n"
                f"* 🕐 Started at <t:{int(start_time)}:T>, ended at <t:{int(end_time)}:T>."
            )
            time_channel = bot.get_channel(TIME_TRACKING_CHANNEL_ID)
            if time_channel:
                # await time_channel.send(summary)
                await safe_send(summary, channel_id=TIME_TRACKING_CHANNEL_ID, bot=bot)
            logger.info("✅ Cycle complete.")
            await asyncio.sleep(180)  # Check every 3 minutes


async def safe_monitor_wrapper(disallowed_rank_names=None):
    while True:
        try:
            await monitor_role_changes(disallowed_rank_names)
        except Exception as e:
            logger.error(f"‼️ monitor_role_changes crashed: {e}", exc_info=True)
            await asyncio.sleep(10)


# @bot.slash_command(name="rinse_test", description="Test the bot's response time.")
# async def rinse_test(ctx: discord.ApplicationContext):
#     received_rough = time.monotonic()
#     await ctx.defer(ephemeral=True)
#     before = time.monotonic()
#     await ctx.edit(content="Pinging...")
#     after = time.monotonic()
#     latency = round((after - before) * 1000)
#     await ctx.edit(
#         content=f"🧼 Foam response time: {latency} ms\nRequest received at {time.gmtime(received_rough)} sec — suds flow optimal 🫧"
#     )

# @bot.slash_command(
#     name="threads_tasks",
#     description="List all thread names and their asyncio tasks",
#     default_member_permissions=discord.Permissions(administrator=True),
# )
# async def threads_tasks_apps_command(ctx: discord.ApplicationContext):
#     threads_info = await threads_tasks()
#     output = []

#     # Build the text output
#     for name, ident, tasks in threads_info:
#         output.append(f"**Thread:** {name} (id={ident})")
#         if tasks:
#             output.append("  Tasks:")
#             for t in tasks:
#                 output.append(f"   - {t}")
#         else:
#             output.append("  No asyncio tasks")

#     # Join into one big string
#     full_text = "\n".join(output)

#     # Split into chunks of <=2000 characters
#     split_per_two_thousand = [
#         full_text[i : i + 2000] for i in range(0, len(full_text), 2000)
#     ]

#     # Debug logging after the split
#     for idx, part in enumerate(split_per_two_thousand):
#         logging.debug(f"Chunk {idx} length: {len(part)}")

#     # Send first chunk as the initial response
#     await ctx.respond(split_per_two_thousand[0])

#     # Send the rest as follow-ups
#     for part in split_per_two_thousand[1:]:
#         await ctx.send_followup(part)

list_of_channels = [
    TIME_TRACKING_CHANNEL_ID,
    CUSTOMER_HEAD_OP_CHANNEL,
    SHIFT_LEADER_GEN_MANAGER_CHANNEL,
    JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL,
]


# -------------------- CHANNEL TESTING --------------------
async def test_single_channel_send_publish_react(channel):
    chan = bot.get_channel(channel) or await bot.fetch_channel(channel)
    if not chan:
        return False, None

    logger.debug(f"Testing channel: {chan.name} ({chan.id})")
    logger.debug(f"Channel type: {chan.type}")

    logger.debug("Sending test message...")
    success, msg = await chan.send(
        f"-# Testing bot permissions ({chan.name})",
        channel_id=chan.id,
        bot=bot,
        silent=True,
    )

    if not success or not msg:
        return False, None

    logger.debug("Adding reaction to test message...")
    # await safe_reaction(msg, emoji="✅", bot=bot)
    msg = await msg.add_reaction("✅")

    if chan.type == discord.ChannelType.news:
        logger.debug("Publishing test message...")
        msg.publish()
        # asyncio.create_task(safe_publish(msg.id, channel_id=chan.id, bot=bot))

    published_msg = msg

    # if chan.type == discord.ChannelType.news:
    #     published_msg = await safe_publish(msg.id, channel_id=chan.id)

    # try:
    #     await msg.delete()
    # except Exception:
    #     pass

    logger.info(
        f"{'.' * 10}\n✅ Channel test successful for {chan.name} ({chan.id})\n{'*' * 10}"
    )

    return True, msg


@bot.slash_command(
    name="test_publish", description="Test publishing to one or all channels"
)
@discord.guild_only()
@discord.commands.option(
    "channel",
    description="Choose 'all' or a specific channel ID",
    choices=[discord.OptionChoice(name="all", value="all")]
    + [
        discord.OptionChoice(name=f"Channel ({cid})", value=str(cid))
        for cid in list_of_channels
    ],
)
async def test_publish(interaction: discord.Interaction, channel: str):
    await interaction.response.defer(ephemeral=True)
    if channel == "all":
        results = []
        for cid in list_of_channels:
            success, msg = await test_single_channel_send_publish_react(cid)
            results.append(f"{'✅' if success else '❌'} <#{cid}>")
        await interaction.followup.send("\n".join(results))
    else:
        cid = int(channel)
        success, msg = await test_single_channel_send_publish_react(cid)
        await interaction.followup(
            content=f"{'✅' if success else '❌'} <#{cid}> — {msg}"
        )


role_monitor_task = None


@bot.event
async def on_ready():
    global role_monitor_task

    logger.info(f"Logged in as {bot.user.name}")
    await bot.change_presence(activity=discord.Game("Monitoring role changes"))

    if role_monitor_task is None or role_monitor_task.done():
        logger.info("Starting monitor_role_changes task restricted to HO+...")
        all_lower_HO = []
        all_lower_HO.extend(LOW_RANKS)
        all_lower_HO.remove("Head Operator")
        all_lower_HO.remove("Customer")  # Incase of demotions
        all_lower_HO.append("Member")
        role_monitor_task = bot.loop.create_task(safe_monitor_wrapper(all_lower_HO))
    else:
        logger.info("Monitor task already running, not starting another.")


if __name__ == "__main__":
    try:
        bot.load_extension("commands")  # This loads the commands from commands.py
        # bot.load_extension("special_patches")  # This loads the commands from special_patches.py
    except Exception as e:
        logger.error(f"Failed to load commands extension: {e}")

    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Error running bot: {e}")
=======
import asyncio
import json
import logging
import time, datetime
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

from utils import safe_send, safe_send_and_pub, safe_reaction, safe_publish, fetch_git_revision
from chains import * # ! CHANGE
# import wiki


from discord_report_error_logs import DiscordErrorHandler
import special_patches

import logging_setup

asyncio.set_event_loop(asyncio.new_event_loop())


class MyBot(commands.Bot):
    ROLE_PROGRESS_LOCK: asyncio.Lock  # Tell Pylance this exists
    ROLE_PROGRESS: dict[str, dict[str, int | bool | float]]
    roblox_limiter: "RobloxLimiter"


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

    activity_text = f"Monitoring roles | {done_roles}/{total_roles} done | {users_checked:,} users"

    try:
        await bot.change_presence(activity=discord.Game(name=activity_text))
        _last_presence_update = now
    except Exception as e:
        logger.debug(f"Presence update skipped: {e}")


from utils import to_roproxy
import chains
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
    queue_user_id: list[int] | None = None
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
            asyncio.create_task(chains.store_run_func(queue_user_id, safe_send_and_pub(message, channel_id=channel_id, bot=bot)))
        else:
            asyncio.create_task(chains.store_run_func(queue_user_id, safe_send(message, channel_id=channel_id, bot=bot)))

        # asyncio.create_task(changes_txt(message))

        logger.info(f"📢 Flushed queued batch to {channel_name} ({channel_id})")
    except Exception as e:
        logger.error(f"Failed flushing queued messages to {channel_name} ({channel_id}): {e}")


async def monitor_role_changes(
    disallowed_rank_names: Optional[list] = None,
    stop_after_one_loop: bool = False,
    test_mode: bool = False,
):
    global LOOP_COUNT, AWAITING_SHUTDOWN, shutdown_scheduled, csv_jdplus_str, changes, RANKS_INITIALIZED
    LOOP_COUNT += 1
    logger.info(f"🧼 Starting monitoring loop #{LOOP_COUNT}")
    
    disallowed_rank_names.append("Member")

    RANKS_INITIALIZED = False

    # Initialize RANK_ORDER asynchronously inside the running event loop
    if not RANKS_INITIALIZED:
        try:
            async with aiohttp.ClientSession() as session:
                all_ranks = await fetch_roles(session, GROUP_ID)

            for rank in all_ranks:
                RANK_ORDER[rank["name"]] = rank["rank"]

            RANKS_INITIALIZED = True
        except Exception as e:
            logger.exception(f"Failed initializing ranks: {e}")

    AWAITING_SHUTDOWN = stop_after_one_loop
    if test_mode:
        AWAITING_SHUTDOWN = test_mode

    role_time_used = {}

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

                    async with bot.ROLE_PROGRESS_LOCK:
                        ROLE_PROGRESS[role_name]["checked"] = 0
                        ROLE_PROGRESS[role_name]["total"] = role["memberCount"]
                        ROLE_PROGRESS[role_name]["done"] = False

                        ROLE_PROGRESS[role_name]["start"] = time.time()

                    enable_queue = role_name not in HIGH_RANKS
                    queue = []
                    queue_user_id = []
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

                            async with bot.ROLE_PROGRESS_LOCK:
                                ROLE_PROGRESS[role_name]["checked"] = users_checked

                            user_id = str(user["userId"])
                            current_rank = role_name
                            current_index = get_rank_index(current_rank)

                            # logger.debug(
                            #     f"DBG: checking user store presence: user_id={user_id} "
                            #     f"in_store={'yes' if user_id in data.get('user_roles', {}) else 'no'}"
                            # )
                            # logger.debug(
                            #     f"DBG: user_id={user_id} current_rank={current_rank} current_index={current_index}"
                            # )

                            if role_name in HIGH_RANKS:
                                local_csv += ("," if local_csv else "") + user_id

                            if user_id in data["user_roles"]:
                                prev_role_id = data["user_roles"][user_id]

                                # `prev_role_id` in the store may be either:
                                # - an integer role id (preferred),
                                # - a numeric string role id,
                                # - or a role name string from older data.
                                prev_rank = None
                                try:
                                    if isinstance(prev_role_id, (int, float)):
                                        prev_rank = roles_dict.get(int(prev_role_id))
                                    elif isinstance(prev_role_id, str):
                                        if prev_role_id.isdigit():
                                            prev_rank = roles_dict.get(int(prev_role_id))
                                        else:
                                            # assume it's already a role name
                                            prev_rank = prev_role_id
                                except Exception:
                                    prev_rank = None

                                prev_index = get_rank_index(prev_rank)

                                # logger.debug(
                                #     f"DBG: prev_role_id={prev_role_id} prev_rank={prev_rank} prev_index={prev_index}"
                                # )

                                if prev_rank and current_index != prev_index and prev_index != -1:
                                    # action = "promoted" if current_index > prev_index else "demoted"
                                    if current_index > prev_index:
                                        action = "promoted"
                                    else:
                                        action = "demoted"

                                    check_pass = special_patches.check_user(
                                        user, current_rank, prev_rank, action
                                    )
                                    # logger.debug(
                                    #     f"DBG: special_patches.check_user -> {check_pass} for user={user_id} "
                                    #     f"action={action} from={prev_rank} to={current_rank}"
                                    # )
                                    if not check_pass:
                                        continue

                                    channel_id, mention = get_rank_channel(
                                        current_rank if action == "promoted" else prev_rank
                                    )
                                    channel = bot.get_channel(channel_id)
                                    channel_name = getattr(channel, "name", "N/A")
                                    message = (
                                        f"[{user['username']}](<https://www.roblox.com/users/{user['userId']}/profile{await chains.get_build_chain_params_for_user(user['userId'], bot, True)}>) "
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
                                                queue_user_id
                                            )
                                        queue.append(message + "\n")
                                        queue_user_id.append(user_id)
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
                                    # Record the user's current role id so we update the store after processing
                                    try:
                                        role_updates[str(user["userId"])] = role_id
                                    except Exception:
                                        role_updates[user_id] = role_id

                    await flush_role_change_queue(queue, last_channel_id, last_channel_name)

                    logger.info(f"Finished processing role: {role_name}")
                    async with bot.ROLE_PROGRESS_LOCK:
                        ROLE_PROGRESS[role_name]["done"] = True

                        still_running = {
                            name: info for name, info in ROLE_PROGRESS.items() if not info["done"]
                        }

                    if still_running:
                        lines = []
                        for name, info in still_running.items():
                            checked = info["checked"]
                            total = info["total"]

                            remaining = total - checked if total else None

                            time_elapsed = time.time() - info["start"]
                            ups = checked / time_elapsed if time_elapsed > 0 else 0.0

                            if checked == 0:
                                eta_str = "(N/A)"
                            elif remaining is not None and ups > 0:
                                time_remaining = int(remaining / ups)
                                eta_str = f"~{str(datetime.timedelta(seconds=time_remaining))}"
                            else:
                                eta_str = "?"

                            remaining_str = str(remaining) if remaining is not None else "?"
                            progress_str = f"{checked}/{total}" if total else f"{checked}/?"

                            lines.append(
                                f"- {name}: {progress_str} ({remaining_str} left, {eta_str} remaining)"
                            )
                        time_elapsed = time.time() - ROLE_PROGRESS[role_name]["start"]

                        logger.info(
                            "⏳ Role finished: %s (%s) | Still running:\n%s",
                            role_name,
                            time_elapsed,
                            "\n".join(lines),
                        )

                        role_time_used[role_name] = time_elapsed
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

            if test_mode:
                return {
                    "total_duration_s": duration,
                    "users_checked_total": users_checked_total,
                    "total_users_in_group": sum(r["memberCount"] for r in roles),
                    "roles_processed": len(changes),
                    "changes": changes,
                    "role_time_used": role_time_used,
                }

            shutdown_scheduled = False
            if AWAITING_SHUTDOWN:
                shutdown_scheduled = True
                
            with open("app.py", "r") as f:
                new_hash = hash(f.read())
                if new_hash != APP_FILE_HASH:
                    logger.warning("app.py file changed during execution. Scheduling shutdown.")
                    shutdown_scheduled = True

            if shutdown_scheduled:
                LOOP_COUNT -= 1
                if LOOP_COUNT <= 0:
                    await bot.close()
                return True

            if True:  # sys.platform != "win32":
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

    # await safe_send_and_pub(
    #     "-# ||Testing safe_send_and_pub to Junior Director+ channel.|| Please ignore.",
    #     channel_id=JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL,
    #     bot=bot,
    #     silent=True,
    # )

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
    if channel:
        await channel.send("🧼 Bot is online and monitoring role changes!")

    # 4. Background Task Management
    # Ensure task only starts if ~~we are in the main execution (or run by SOCKS) and~~ task isn't already running
    should_start_task = (
        # __name__ == "__main__" and 
        (role_monitor_task is None or role_monitor_task.done())
    ) 

    if should_start_task:
        logger.info("Starting monitor task...")
        
        # Build restricted list from MID_RANKS
        # Easily extendable by adding lists: restricted = MID_RANKS + LOW_RANKS
        restricted = list(MID_RANKS) 

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
>>>>>>> origin/deploy/STAGING
