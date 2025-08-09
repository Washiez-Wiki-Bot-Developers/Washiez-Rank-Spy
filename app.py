import aiohttp
import asyncio
import json
import logging
import time
import os

import discord
from discord.ext import commands
import dotenv

from discord_report_error_logs import DiscordErrorHandler

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('bot')

# ? Normal Text Log file logging
file_handler = logging.FileHandler("bot.log")
file_handler.setLevel(logging.DEBUG)  # ? Set to DEBUG to capture all logs
logger.addHandler(file_handler)

intents = discord.Intents.default()
intents.guilds = True
bot = commands.Bot(command_prefix='! ', intents=intents, reconnect=True)

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

# Channel IDs
CUSTOMER_HEAD_OP_CHANNEL = 1271730077939535913
SHIFT_LEADER_GEN_MANAGER_CHANNEL = 1271730172692795435
JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL = 1271730208130469920
TIME_TRACKING_CHANNEL_ID = 1328352565443694644

# Role mention IDs
LOW_RANK_ROLE_MENTION = "<@&1328338426713342023>"
MID_RANK_ROLE_MENTION = "<@&1328338484104134688>"
HIGH_RANK_ROLE_MENTION = "<@&1328338542132330506>"

DATA_FILE = 'info.json'
file_lock = asyncio.Lock()

LOW_RANKS = ["Customer", "Trainee", "Junior Operator", "Senior Operator", "Head Operator"]
MID_RANKS = ["Shift Leader", "Supervisor", "Assistant Manager", "General Manager"]
HIGH_RANKS = [
    "Junior Director", "Senior Director", "Head Director", "Corporate Intern",
    "Junior Corporate", "Senior Corporate", "Head Corporate", "Automation",
    "Chief Human Resources Officer", "Chief Public Relations Officer",
    "Chief Operating Officer", "Chief Administrative Officer", "Developer",
    "Vice Chairman", "Chairman"
]

async def load_data():
    async with file_lock:
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.info("Data file missing or corrupt. Creating fresh.")
            return {'user_roles': {}}

async def save_data(data):
    async with file_lock:
        try:
            with open(DATA_FILE, 'w') as f:
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

async def fetch_roles(session, group_id):
    url = f'https://groups.roblox.com/v1/groups/{group_id}/roles'
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch roles: {response.status}")
                return []
            data = await response.json()
            return data['roles']
    except Exception as e:
        logger.error(f"Error fetching roles: {e}")
        return []

async def fetch_users_in_role(session, group_id, role_id):
    users = []
    cursor = ''
    while True:
        url = f'https://groups.roblox.com/v1/groups/{group_id}/roles/{role_id}/users?limit=100&sortOrder=Asc'
        if cursor:
            url += f'&cursor={cursor}'
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    logger.error(f"Failed to fetch users for role {role_id}: {response.status}")
                    return users
                data = await response.json()
                users.extend(data['data'])
                cursor = data.get('nextPageCursor', '')
                if not cursor:
                    break
        except Exception as e:
            logger.error(f"Error fetching users for role {role_id}: {e}")
            break
    return users

async def monitor_role_changes():
    async with aiohttp.ClientSession() as session:
        while True:
            start_time = time.time()
            logger.info("🔎 Checking for role changes...")

            roles = await fetch_roles(session, GROUP_ID)
            if not roles:
                await asyncio.sleep(10)
                continue

            roles_dict = {role['id']: role['name'] for role in roles}
            data = await load_data()

            roles_processed = 0
            users_checked = 0

            for role in roles:
                users = await fetch_users_in_role(session, GROUP_ID, role['id'])
                for user in users:
                    user_id = str(user['userId'])
                    current_rank = role['name']
                    current_index = get_rank_index(current_rank)

                    if user_id in data['user_roles']:
                        prev_role_id = data['user_roles'][user_id]
                        prev_role_name = roles_dict.get(prev_role_id, "Unknown")
                        prev_index = get_rank_index(prev_role_name)

                        if current_index != -1 and prev_index != -1 and current_index != prev_index:
                            action = "promoted" if current_index > prev_index else "demoted"
                            channel_id, mention = get_rank_category_and_mention(current_rank)
                            if channel_id:
                                channel = bot.get_channel(channel_id)
                                if channel:
                                    profile_link = f"[{user['username']}](<https://www.roblox.com/users/{user['userId']}/profile>)"
                                    message = f"{profile_link} has been {action} from {prev_role_name} to {current_rank} {mention}"
                                    message_obj = await channel.send(message)
                                    try:
                                        await message_obj.publish()
                                    except discord.Forbidden as e:
                                        print(f"Failed to publish: {e}")
                                    except discord.HTTPException as e:
                                        print(f"HTTP error during publish: {e}")
                                    logger.info(f"📢 {message}")
                    data['user_roles'][user_id] = role['id']
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
                await time_channel.send(summary)
            logger.info("✅ Cycle complete.")
            await asyncio.sleep(180)  # Check every 3 minutes

async def safe_monitor_wrapper():
    while True:
        try:
            await monitor_role_changes()
        except Exception as e:
            logger.error(f"‼️ monitor_role_changes crashed: {e}")
            await asyncio.sleep(10)

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user.name}")
    await bot.change_presence(activity=discord.Game("Monitoring role changes"))
    bot.loop.create_task(safe_monitor_wrapper())

try:
    bot.run(TOKEN)
except Exception as e:
    logger.error(f"Error running bot: {e}")
