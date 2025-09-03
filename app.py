import asyncio
import json
import logging
import time
import os
import sys, math
from colorama import Fore, Style

from typing import cast, Optional, Union, Tuple

import aiohttp

# Stop discord loggers from propagating to root
logging.getLogger("discord").propagate = False
logging.getLogger("discord.app_commands.tree").propagate = False

import discord
from discord.ext import commands
import dotenv, hashlib

from discord_report_error_logs import DiscordErrorHandler
from coloured_log_handler import ColorFormatter


attribution = "Rankspy by Washiez Wiki Bot Developers, based on original work from MartinAstrea.\n Made with 🧼🫧 by WW:BD, Martin and MrT!\n Licensed under MIT License until further revision."


# --- Logging setup ---
logger = logging.getLogger("bot")
logger.propagate = False
logger.setLevel(logging.DEBUG)

# Console handler (short time + colors)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(ColorFormatter())  # datefmt="%YY-%MM-%DD %H:%M:%S"))
logger.addHandler(console_handler)

# ? Normal Text Log file logging
file_handler = logging.FileHandler("bot.log", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)  # ? Set to DEBUG to capture all logs
logger.addHandler(file_handler)

# ? Error Text Log file logging
error_file_handler = logging.FileHandler("ERRORbot.log", encoding="utf-8")
error_file_handler.setLevel(logging.ERROR)  # ? Set to DEBUG to capture all logs
logger.addHandler(error_file_handler)

intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix="! ", intents=intents, reconnect=True)

dotenv.load_dotenv()

GROUP_ID = 10261023
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

APP_FILE_HASH = ""

with open("app.py", "rb") as f:
    APP_FILE_HASH = hashlib.sha256(f.read()).hexdigest()

MAX_CHARS_DISCORD = 2000

# Channel IDs
# PROD
# CUSTOMER_HEAD_OP_CHANNEL = 1271730077939535913
# SHIFT_LEADER_GEN_MANAGER_CHANNEL = 1271730172692795435
# JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL = 1271730208130469920
# TIME_TRACKING_CHANNEL_ID = 1328352565443694644

CUSTOMER_HEAD_OP_CHANNEL = 1361321812859813908
SHIFT_LEADER_GEN_MANAGER_CHANNEL = 1361321834913726538
JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL = 1361321849400725786
TIME_TRACKING_CHANNEL_ID = 1361321875807932587

# Add DiscordErrorHandler
ERROR_LOG_CHANNEL = TIME_TRACKING_CHANNEL_ID  # Replace with your desired channel ID
discord_error_handler = DiscordErrorHandler(bot, ERROR_LOG_CHANNEL)
discord_error_handler.setLevel(logging.ERROR)  # Only handle ERROR level logs
formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
discord_error_handler.setFormatter(formatter)
# logger.addHandler(discord_error_handler)

# # Role mention IDs
# LOW_RANK_ROLE_MENTION = "<@&1328338426713342023>"
# MID_RANK_ROLE_MENTION = "<@&1328338484104134688>"
# HIGH_RANK_ROLE_MENTION = "<@&1328338542132330506>"

LOW_RANK_ROLE_MENTION = "LaRPING"
MID_RANK_ROLE_MENTION = "MiRPING"
HIGH_RANK_ROLE_MENTION = "HiRPING"

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
HIGH_RANKS = [
    "Junior Director",
    "Senior Director",
    "Head Director",
    "Corporate Intern",
    "Junior Corporate",
    "Senior Corporate",
    "Head Corporate",
    "Automation",
    "Chief Human Resources Officer",
    "Chief Public Relations Officer",
    "Chief Operating Officer",
    "Chief Administrative Officer",
    "Developer",
    "Vice Chairman",
    "Chairman",
]


async def load_data():
    async with file_lock:
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("Data file missing or corrupt. Creating fresh.")
            return {"user_roles": {}}


async def save_data(data):
    async with file_lock:
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
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


async def fetch_roles(session, group_id):
    url = f"https://groups.roblox.com/v1/groups/{group_id}/roles"
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch roles: {response.status}")
                return []
            data = await response.json()
            return data["roles"]
    except Exception as e:
        logger.error(f"Error fetching roles: {e}")
        return []


async def fetch_users_in_role(session, group_id, role_id, role_member_count="?"):
    users = []
    cursor = ""
    logger.debug(f"Fetching users for role {role_id} in group {group_id}.")

    time_start = time.time()
    elapsed_time = 0.0

    from rich.progress import Progress, TextColumn, BarColumn, TimeElapsedColumn

    # Create the progress bar ONCE
    with Progress(
        TextColumn(
            f"Fetched {{task.completed}}/{{task.total}} ({{task.percentage:>3.0f}}%) users for role {role_id}"
        ),
        BarColumn(),
        TextColumn("[{task.fields[ups]} u/s]"),
        TimeElapsedColumn(),
        refresh_per_second=5,
        transient=True,  # hides when done
    ) as progress:

        total_count = (
            int(role_member_count) if role_member_count not in (None, "?") else 0
        )
        task = progress.add_task("Fetching", total=total_count, ups="0")

        while True:
            url = f"https://groups.roblox.com/v1/groups/{group_id}/roles/{role_id}/users?limit=100&sortOrder=Asc"
            if cursor:
                url += f"&cursor={cursor}"

            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status != 200:
                        logger.error(
                            f"Failed to fetch users for role {role_id}: {response.status}"
                        )
                        return users

                    data = await response.json()
                    users.extend(data["data"])
                    cursor = data.get("nextPageCursor", "")

                    # Calculate stats
                    if total_count:
                        try:
                            percentage: Union[str, float] = (
                                math.ceil((len(users) / total_count * 100) * 100) / 100
                            )
                        except ZeroDivisionError as e:
                            logger.error(f"ZeroDivisionError for role {role_id}: {e}")
                            percentage = "?"
                    else:
                        percentage = "?"

                    if len(users) == total_count and total_count:
                        logger.debug(
                            f"Fetched all {total_count} users for role {role_id}."
                        )
                        percentage = 100.0

                    current_time = time.time()
                    since_last_cycle = current_time - (time_start + elapsed_time)
                    elapsed_time = current_time - time_start

                    try:
                        users_per_sec = (
                            math.ceil(len(data["data"]) / since_last_cycle * 10) / 10
                        )
                    except ZeroDivisionError:
                        users_per_sec = "?"

                    # Update the SAME progress task
                    progress.update(task, completed=len(users), ups=f"{users_per_sec}")

                    if not cursor:
                        break

            except Exception as e:
                logger.error(f"Error fetching users for role {role_id}: {e}")
                break

    logger.info(
        f"{role_id}: Completed fetching. We have {len(users)} users for role {role_id}."
    )
    return users


@bot.tree.command(name="rinse_test", description="Test the bot's response time.")
async def fling_test(interaction: discord.Interaction):
    received_rough = time.monotonic()

    # Defer the response so you can edit it later
    await interaction.response.defer(ephemeral=True)

    before = time.monotonic()
    # Simulate some processing delay (optional)
    await interaction.edit_original_response(content="Pinging...")
    after = time.monotonic()

    latency = round((after - before) * 1000)
    await interaction.edit_original_response(
        content=f"🧼 Foam response time: {latency} ms\nRequest received at {time.gmtime(received_rough)} sec — suds flow optimal 🫧"
    )

    logger.info("Fling test command executed successfully.")


async def monitor_role_changes():
    # bot_startup_notify = bot.get_channel(1361321875807932587)
    # assert isinstance(bot_startup_notify, discord.TextChannel)

    # bot_startup_notify: discord.abc.GuildChannel | None = bot.get_channel(
    # 1361321875807932587
    # )
    # await bot_startup_notify.send(
    # "## 🔄 **Bot Started**\n-# Pings: <@1114892999474815126>"
    # )
    async with aiohttp.ClientSession() as session:
        while True:
            start_time = time.time()
            logger.info("🔎 Checking for role changes...")

            logger.info("Fetching roles from Roblox API...")
            roles = await fetch_roles(session, GROUP_ID)
            if not roles:
                logger.debug(
                    "No roles found or failed to fetch roles. Retrying in 10 seconds..."
                )
                await asyncio.sleep(10)
                continue

            logger.debug(f"Fetched {len(roles)} roles from Roblox API.")

            roles_dict = {role["id"]: role["name"] for role in roles}
            data = await load_data()

            roles_processed = 0
            users_checked = 0

            logger.debug("Starting role change checks, for-loop for roles.")
            for role in roles:
                logger.info(
                    f"Starting the loop for {role['name']} with ID {role['id']}."
                )

                await bot.change_presence(
                    activity=discord.Game(f"Monitoring role changes: {role['name']}")
                )

                # Queued send - queue messages to max chars to limit messages sent.
                enable_queued_send = role["name"] not in HIGH_RANKS
                queue = ""

                logger.debug(
                    f"Fetching users for role {role['name']} with ID {role['id']}."
                )
                users = await fetch_users_in_role(
                    session, GROUP_ID, role["id"], role_member_count=role["memberCount"]
                )
                logger.debug("Starting role change checks, for-loop for users.")
                for user in users:
                    logger.debug(
                        f"Processing {user['username']} with ID {user['userId']}."
                    )
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
                            if channel_id:
                                channel = bot.get_channel(channel_id)

                                if not isinstance(channel, discord.TextChannel):
                                    channelid = ""

                                    if channel is not None and hasattr(channel, "id"):
                                        channelid = channel.id

                                    logger.exception(
                                        f"Channel {channelid} is not a TextChannel."
                                    )

                                if isinstance(channel, (discord.TextChannel)):
                                    profile_link = f"[{user['username']}](<https://www.roblox.com/users/{user['userId']}/profile>)"
                                    message = f"{profile_link} has been {action} from {prev_role_name} to {current_rank} {mention}"

                                    if enable_queued_send:
                                        if (
                                            len(queue) + len(message)
                                            > MAX_CHARS_DISCORD
                                        ):
                                            logger.info(
                                                f"📢 Releasing (aka sending) queued message to {channel.name} ({channel.id})"
                                            )
                                            await channel.send(queue)
                                            queue = ""
                                        queue += message + "\n"
                                        logger.debug(f"Queued message: {message}")

                                        if user == users[-1]:
                                            message_obj = await channel.send(queue)
                                    else:
                                        message_obj = await channel.send(message)

                                    logger.info(f"📢 {message}")
                                else:
                                    logger.exception(
                                        f"Channel {getattr(channel, 'name', None)} ({getattr(channel, 'id', None)}) is not a TextChannel or NewsChannel."
                                    )
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
            if time_channel and isinstance(time_channel, discord.TextChannel):
                await time_channel.send(summary)
            logger.info("✅ Cycle complete.")
            # await asyncio.sleep(180)  # Check every 3 minutes

            latest_app_hash = hashlib.sha256(open("app.py", "rb").read()).hexdigest()

            shutdown_scheduled = False

            if latest_app_hash != APP_FILE_HASH:
                logger.info("App file has changed. Restarting bot...")
                shutdown_scheduled = True
                time_channel = bot.get_channel(TIME_TRACKING_CHANNEL_ID)
                if time_channel and isinstance(time_channel, discord.TextChannel):
                    await time_channel.send(
                        f"# 🔄 App file changed, bot will shutdown. \n We are at the end of the monitor role changes loop, will shutdown...\n## Please restart via console.\n-# Pings: {('<@1081153729153224766>, ' if os.getenv('ENVIRONMENT_MODE') != 'local_debug' else '')}<@1114892999474815126>"
                    )
                    shutdown_scheduled = True

            if shutdown_scheduled:
                logger.info("Shutdown scheduled. Closing bot...")
                await bot.close()
                logger.info("Shutdown scheduled. Exiting monitor loop.")
                break


async def safe_monitor_wrapper():
    while True:
        try:
            await monitor_role_changes()
        except Exception as e:
            logger.error(f"‼️ monitor_role_changes crashed: {e}")
            await asyncio.sleep(10)


@bot.event
async def on_ready():
    try:
        import get_latest_git_commitid
    except (ImportError, NameError) as e:
        logger.error(
            f"Failed to import get_latest_git_commitid: {e}\n You may ignore this error."
        )

    if not bot.user:
        logger.error("Bot user is not set. Exiting.")
        sys.exit(1)

    logger.info(f"Logged in as {bot.user.name}")
    await bot.change_presence(activity=discord.Game("Monitoring role changes"))

    print("\n\n")
    logger.info(Fore.GREEN + "WELCOME TO RANKSPY!" + Style.RESET_ALL)
    logger.info(attribution)
    # logger.info("Latest Version: N/A")
    logger.info(
        f"Latest Git Commit ID for app.py: {get_latest_git_commitid.get_latest_commit('app.py', short=True)} + Further non-commited revisions.\n\n"
    )
    logger.info(f"App file hash: {APP_FILE_HASH}")

    logger.info("Starting monitor_role_changes task...")

    bot.loop.create_task(safe_monitor_wrapper())


if __name__ == "__main__":
    if TOKEN is None:
        logger.error("DISCORD_BOT_TOKEN not set in .env file.")
        sys.exit(1)
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Error running bot: {e}")
