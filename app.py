import discord
from discord.ext import commands
import aiohttp
import asyncio
import json
import logging
import time

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('bot')

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='! ', intents=intents)

GROUP_ID = 10261023
TOKEN = "put tocken here"

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

# Define ranks by categories (in lowest to highest order)
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
        except FileNotFoundError:
            logger.info("Data file not found. Creating new data structure.")
            return {'user_roles': {}}
        except json.JSONDecodeError:
            logger.error("Error decoding JSON from info.json. Creating new data structure.")
            return {'user_roles': {}}

async def save_data(data):
    async with file_lock:
        try:
            with open(DATA_FILE, 'w') as f:
                json.dump(data, f)
            logger.info("Data successfully saved to info.json")
        except Exception as e:
            logger.error(f"Error saving data to info.json: {str(e)}")

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user.name}")
    await bot.change_presence(activity=discord.Game("Monitoring role changes"))
    bot.loop.create_task(monitor_role_changes())

async def fetch_roles(session, group_id):
    url = f'https://groups.roblox.com/v1/groups/{group_id}/roles'
    async with session.get(url) as response:
        if response.status != 200:
            logger.error(f"Failed to fetch roles. Status: {response.status}")
            return []
        roles_data = await response.json()
        return roles_data['roles']

async def fetch_users_in_role(session, group_id, role_id):
    users = []
    cursor = ''
    while True:
        url = f'https://groups.roblox.com/v1/groups/{group_id}/roles/{role_id}/users?limit=100&sortOrder=Asc'
        if cursor:
            url += f'&cursor={cursor}'

        async with session.get(url) as response:
            if response.status != 200:
                logger.error(f"Failed to fetch users for role {role_id}. Status: {response.status}")
                return users

            data = await response.json()
            users.extend(data['data'])

            if data.get('nextPageCursor'):
                cursor = data['nextPageCursor']
            else:
                break

    return users

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

async def monitor_role_changes():
    async with aiohttp.ClientSession() as session:
        while True:
            start_time = time.time()  # Start timing the cycle
            logger.info("Checking for role changes...")
            roles = await fetch_roles(session, GROUP_ID)
            if not roles:
                await asyncio.sleep(1)
                continue

            roles_dict = {role['id']: role['name'] for role in roles}
            data = await load_data()
            for role in roles:
                users = await fetch_users_in_role(session, GROUP_ID, role['id'])
                for user in users:
                    user_id = str(user['userId'])
                    current_rank_name = role['name']
                    current_rank_index = get_rank_index(current_rank_name)

                    if user_id in data['user_roles']:
                        previous_role_name = roles_dict.get(data['user_roles'][user_id], "Unknown")
                        previous_rank_index = get_rank_index(previous_role_name)

                        if current_rank_index != -1 and previous_rank_index != -1:
                            if current_rank_index > previous_rank_index:
                                action = "promoted"
                            elif current_rank_index < previous_rank_index:
                                action = "demoted"
                            else:
                                continue  # No rank change
                            channel_id, mention = get_rank_category_and_mention(current_rank_name)
                            if channel_id:
                                channel = bot.get_channel(channel_id)
                                if channel:
                                    profile_link = f"[{user['username']}](<https://www.roblox.com/users/{user['userId']}/profile>)"
                                    message = f"{profile_link} has been {action} from {previous_role_name} to {current_rank_name} {mention}"
                                    await channel.send(message)
                                    logger.info(f"Role change detected: {message}")

                    data['user_roles'][user_id] = role['id']

            await save_data(data)
            end_time = time.time()  # End timing
            cycle_time = end_time - start_time
            time_channel = bot.get_channel(TIME_TRACKING_CHANNEL_ID)
            if time_channel:
                await time_channel.send(f"Role monitoring cycle completed in {cycle_time:.2f} seconds.")
            logger.info(f"Cycle completed in {cycle_time:.2f} seconds.")
            await asyncio.sleep(1)

try:
    bot.run(TOKEN)
except Exception as e:
    logger.error(f"Error running bot: {str(e)}")
