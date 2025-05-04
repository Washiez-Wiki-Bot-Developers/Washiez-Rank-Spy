import discord
from discord.ext import commands
import aiohttp
import asyncio
import json
import logging
import time
import datetime  # Keep for potential future use
import gc  # Explicitly import garbage collector if needed later
from discord_report_error_logs import DiscordErrorHandler
import math
import os, dotenv

# Set up logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s:%(levelname)s:%(name)s: %(message)s"
)
logger = logging.getLogger("bot")

intents = discord.Intents.default()
intents.presences = False  # Presences are not strictly needed for this functionality
intents.members = False  # Members intent is not needed unless you check discord members
bot = commands.Bot(command_prefix="! ", intents=intents)

# Add DiscordErrorHandler
ERROR_LOG_CHANNEL = 1361321875807932587  # Replace with your desired channel ID
discord_error_handler = DiscordErrorHandler(bot, ERROR_LOG_CHANNEL)
discord_error_handler.setLevel(logging.ERROR)  # Only handle ERROR level logs
formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
discord_error_handler.setFormatter(formatter)
logger.addHandler(discord_error_handler)

# --- Configuration ---
GROUP_ID = 10261023
# WARNING: Exposing token directly in code is a security risk! (Keeping user's token as requested)
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

# --- Channel IDs ---
# Define channel mappings for each environment mode
CHANNEL_IDs = {
    "debug": {
        "ENTRY_TEAM_CHANNEL": 1361321812859813908,
        "SUPERVISION_TEAM_CHANNEL": 1361321834913726538,
        "MANAGEMENT_TEAM_CHANNEL": 1361321849400725786,
        "CYCLE_INFO_CHANNEL": 1328352565443694644,
        "STARTUP_STATUS_CHANNEL": 1328352565443694644,
    },
    "local_debug": {
        "CYCLE_INFO_CHANNEL": 1361321875807932587,
        "STARTUP_STATUS_CHANNEL": 1361321875807932587,
    },
    "PROD": {
        "ENTRY_TEAM_CHANNEL": 1271730077939535913,
        "SUPERVISION_TEAM_CHANNEL": 1271730172692795435,
        "MANAGEMENT_TEAM_CHANNEL": 1271730208130469920,
        "CYCLE_INFO_CHANNEL": 1328352565443694644,
        "STARTUP_STATUS_CHANNEL": 1328352565443694644,
    },
}

ENV_MODE = os.getenv("ENVIRONMENT_MODE", "debug")

current_CHANNEL_IDs = CHANNEL_IDs.get(ENV_MODE, CHANNEL_IDs["debug"])

ENV_MODE_DEBUG = ENV_MODE == "debug"
ENV_MODE_PROD = ENV_MODE == "PROD"
ENV_MODE_LOC_DEBUG = ENV_MODE == "local_debug"

ESTIMATED_TIME_LOG_CHANNEL = 1368547558489587932
ENTRY_TEAM_CHANNEL = current_CHANNEL_IDs.get("ENTRY_TEAM_CHANNEL")
SUPERVISION_TEAM_CHANNEL = current_CHANNEL_IDs.get("SUPERVISION_TEAM_CHANNEL")
MANAGEMENT_TEAM_CHANNEL = current_CHANNEL_IDs.get("MANAGEMENT_TEAM_CHANNEL")
CYCLE_INFO_CHANNEL = current_CHANNEL_IDs.get("CYCLE_INFO_CHANNEL")
STARTUP_STATUS_CHANNEL = current_CHANNEL_IDs.get("STARTUP_STATUS_CHANNEL")


use_real_pings = ENV_MODE_PROD and not ENV_MODE_DEBUG and not ENV_MODE_LOC_DEBUG | False

# Role mention IDs (Using user's last provided IDs)
if use_real_pings:
    LOW_RANK_ROLE_MENTION = "<@&1328338426713342023>" # Corresponds to ENTRY_TEAM_CHANNEL
    MID_RANK_ROLE_MENTION = "<@&1328338484104134688>" # Corresponds to SUPERVISION_TEAM_CHANNEL
    HIGH_RANK_ROLE_MENTION = "<@&1328338542132330506>" # Corresponds to MANAGEMENT_TEAM_CHANNEL
else:
    LOW_RANK_ROLE_MENTION = "LR PING HERE"  # Corresponds to ENTRY_TEAM_CHANNEL
    MID_RANK_ROLE_MENTION = "MR PING HERE"  # Corresponds to SUPERVISION_TEAM_CHANNEL
    HIGH_RANK_ROLE_MENTION = "HR PING HERE"  # Corresponds to MANAGEMENT_TEAM_CHANNEL

DATA_FILE = "info.json"
file_lock = asyncio.Lock()

# Define ranks by categories (in lowest to highest order)
# Cleaned up potential non-standard spaces from previous pastes
LOW_RANKS = [
    "Customer",
    "Trainee",
    "Junior Operator",
    "Senior Operator",
    "Head Operator",
]  # -> ENTRY_TEAM_CHANNEL
MID_RANKS = [
    "Shift Leader",
    "Supervisor",
    "Assistant Manager",
    "General Manager",
]  # -> SUPERVISION_TEAM_CHANNEL
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
]  # -> MANAGEMENT_TEAM_CHANNEL

# --- Helper Functions ---


async def load_data():
    # Using standard 4-space indentation
    async with file_lock:
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.info(
                f"Data file '{DATA_FILE}' not found. Creating new data structure."
            )
            return {"user_roles": {}}
        except json.JSONDecodeError:
            logger.error(
                f"Error decoding JSON from '{DATA_FILE}'. Returning empty structure."
            )
            return {"user_roles": {}}


async def save_data(data):
    # Using standard 4-space indentation
    async with file_lock:
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(data, f, indent=4)
            logger.debug(f"Data successfully saved to '{DATA_FILE}'")
        except Exception as e:
            logger.error(f"Error saving data to '{DATA_FILE}': {str(e)}")


async def fetch_roles(session, group_id):
    # Using standard 4-space indentation
    url = f"https://groups.roblox.com/v1/groups/{group_id}/roles"
    try:
        async with session.get(url) as response:
            response.raise_for_status()
            roles_data = await response.json()
            logger.info(
                f"Successfully fetched {len(roles_data.get('roles', []))} roles for group {group_id}."
            )
            return roles_data.get("roles", [])
    except aiohttp.ClientResponseError as e:
        logger.error(
            f"HTTP error fetching roles: {e.status} {e.message} for {e.request_info.url}"
        )
    except aiohttp.ClientError as e:
        logger.error(f"Network error fetching roles: {e}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error fetching roles: {e}")
    except Exception as e:
        logger.exception(f"Unexpected error fetching roles:")
    return []


async def get_role_member_count(group_id, role_name):
    url = f"https://groups.roblox.com/v1/groups/{group_id}/roles"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                data = await response.json()
                roles = data.get("roles", [])
                for role in roles:
                    if role["name"].lower() == role_name.lower():
                        return role["memberCount"]
                return f"Role '{role_name}' not found in group {group_id}."
        except aiohttp.ClientResponseError as e:
            return f"HTTP error: {e.status} {e.message}"
        except Exception as e:
            return f"An error occurred: {str(e)}"


def format_time(seconds):
    # Format Time
    total_seconds_int = int(seconds)
    hours, remainder = divmod(total_seconds_int, 3600)
    minutes, seconds = divmod(remainder, 60)
    time_parts = []
    if hours > 0:
        time_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0:
        time_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    # Display fractional seconds only if total duration is less than a minute
    if hours == 0 and minutes == 0:
        time_parts.append(f"{seconds:.3f} second{'s' if seconds != 1 else ''}")
    else:
        time_parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    formatted_time = ", ".join(time_parts) if time_parts else f"{seconds:.3f} seconds"
    return formatted_time


async def fetch_users_in_role(session, group_id, role_id, role_name):
    # Using standard 4-space indentation
    # Update bot status before fetching users for this role
    try:
        activity = discord.Game(f"Checking: {role_name}")
        await bot.change_presence(activity=activity, status=discord.Status.online)
        logger.info(f"Updating status to: Checking: {role_name}")
    except Exception as e:
        logger.error(f"Failed to update presence for role {role_name}: {e}")

    fetch_start_time = time.monotonic()

    member_count = await get_role_member_count(group_id, role_name)
    future_epoch_time = 0

    users = []
    cursor = None
    page = 1
    max_retries = 3
    retries = 0
    while True:
        url = f"https://groups.roblox.com/v1/groups/{group_id}/roles/{role_id}/users?limit=100&sortOrder=Asc"
        if cursor:
            url += f"&cursor={cursor}"

        try:
            logger.debug(
                f"Fetching users page {page} for role {role_name} ({role_id})..."
            )
            async with session.get(url) as response:
                if response.status == 429:
                    # Default wait time increased slightly
                    retry_after = int(response.headers.get("Retry-After", 90))
                    logger.warning(
                        f"Rate limited fetching users page {page} for role {role_name}. Retrying after {retry_after} seconds."
                    )
                    await bot.change_presence(
                        activity=discord.Game(
                            f"Rate Limited! Waiting {retry_after}s..."
                        ),
                        status=discord.Status.idle,
                    )
                    await asyncio.sleep(retry_after)
                    # Restore status after wait
                    await bot.change_presence(
                        activity=discord.Game(f"Checking: {role_name}"),
                        status=discord.Status.online,
                    )
                    continue

                response.raise_for_status()
                data = await response.json()

                current_page_users = data.get("data", [])
                users.extend(current_page_users)
                logger.debug(
                    f"Fetched {len(current_page_users)} users on page {page} for role {role_name}. Total now: {len(users)}"
                )

                cursor = data.get("nextPageCursor")
                if not cursor:
                    logger.debug(
                        f"No next page cursor for role {role_name}. Fetching complete for this role."
                    )
                    break
                else:
                    page += 1
                    retries = 0  # Reset retries on successful page fetch

                    if page == 125 or (
                        (member_count < 1000) and page == 10
                    ):  # Check after 10 pages
                        logger.info(
                            f"Fetched 10 pages for role {role_name} (1000 users)."
                        )

                        seconds_elapsed_till_calc = time.monotonic() - fetch_start_time
                        formatted_time = format_time(seconds_elapsed_till_calc)
                        logger.info(
                            f"Time taken to fetch 10 pages for role {role_name}: {formatted_time}"
                        )
                        if isinstance(
                            member_count, int
                        ):  # Ensure member_count is valid
                            member_count_in_pages = math.ceil(member_count / 100)
                            pages_left = member_count_in_pages - page
                            total_seconds = (pages_left + page) * (
                                seconds_elapsed_till_calc / page
                            )
                            logger.info(
                                f"Estimated time to fetch all users for role {role_name}: {format_time(total_seconds)}. Time left: {format_time(total_seconds - seconds_elapsed_till_calc)}"
                            )
                            logger.info(member_count_in_pages)
                            logger.info(member_count)
                            future_epoch_time = int(
                                time.time()
                                + (total_seconds - seconds_elapsed_till_calc)
                            )

                            await send_discord_message(
                                ESTIMATED_TIME_LOG_CHANNEL,
                                f"Estimated time to fetch all users for role {role_name}: {format_time(total_seconds)}.\n"
                                f"Time left: {format_time(total_seconds - seconds_elapsed_till_calc)}.\n"
                                f"Completion expected at: <t:{future_epoch_time}:d> <t:{future_epoch_time}:T> (<t:{future_epoch_time}:R>)\n"
                                f"## <t:{math.ceil(time.time() - seconds_elapsed_till_calc)}:T> - ~<t:{future_epoch_time}:T> ",
                            )
                        else:
                            logger.warning(
                                f"Could not retrieve member count for role {role_name}. Skipping time estimation."
                            )

        except aiohttp.ClientResponseError as e:
            logger.error(
                f"HTTP error fetching users page {page} for role {role_name}: {e.status} {e.message} for {e.request_info.url}"
            )
            retries += 1
            if retries >= max_retries:
                logger.error(
                    f"Max retries reached for role {role_name}. Returning partial list ({len(users)} users)."
                )
                break  # Stop trying for this role after max retries
            else:
                wait_time = 2**retries  # Exponential backoff
                logger.info(
                    f"Retrying fetch for role {role_name} in {wait_time} seconds (Retry {retries}/{max_retries})"
                )
                await asyncio.sleep(wait_time)
                continue  # Retry the same page

        except aiohttp.ClientError as e:
            logger.error(
                f"Network error fetching users page {page} for role {role_name}: {e}. Returning partial list."
            )
            break  # Network errors are less likely to resolve quickly, break loop for this role
        except json.JSONDecodeError as e:
            logger.error(
                f"JSON decode error fetching users page {page} for role {role_name}: {e}. Returning partial list."
            )
            break  # Data issue, break loop for this role
        except Exception as e:
            logger.exception(
                f"Unexpected error fetching users page {page} for role {role_name}:"
            )
            break  # Unexpected error, break loop for this role

        # Delay between pages (using user's last provided value)
        await asyncio.sleep(0.1)  # 100ms delay
        member_count_in_pages = math.ceil(member_count / 100)
        pages_left = member_count_in_pages - page
        logger.debug(f"pages left: {pages_left}/{member_count_in_pages}")

    logger.info(f"Finished fetching for role {role_name}. Found {len(users)} users.")
    await send_discord_message(
        ESTIMATED_TIME_LOG_CHANNEL,
        f"Finished fetching for role {role_name}. Found {len(users)} users.\n"
        f"Total pages fetched: {page}.\n"
        f"Total users fetched: {len(users)}.\n"
        f"Total time taken: {format_time(time.monotonic() - fetch_start_time)}.\n"
        f"Differences: {future_epoch_time - (time.monotonic() - fetch_start_time)}.\n",
    )
    return users


def get_rank_category_and_mention(rank_name):
    # Using standard 4-space indentation
    """Maps rank name to the correct channel ID and role mention."""
    if rank_name in LOW_RANKS:
        return ENTRY_TEAM_CHANNEL, LOW_RANK_ROLE_MENTION
    elif rank_name in MID_RANKS:
        return SUPERVISION_TEAM_CHANNEL, MID_RANK_ROLE_MENTION
    elif rank_name in HIGH_RANKS:
        return MANAGEMENT_TEAM_CHANNEL, HIGH_RANK_ROLE_MENTION
    logger.debug(
        f"Rank '{rank_name}' does not fall into a defined category for notification."
    )
    return None, None


def get_rank_index(rank_name):
    # Using standard 4-space indentation
    """Gets the numerical index of a rank based on combined lists."""
    try:
        if rank_name in LOW_RANKS:
            return LOW_RANKS.index(rank_name)
        elif rank_name in MID_RANKS:
            return len(LOW_RANKS) + MID_RANKS.index(rank_name)
        elif rank_name in HIGH_RANKS:
            return len(LOW_RANKS) + len(MID_RANKS) + HIGH_RANKS.index(rank_name)
    except ValueError:
        logger.warning(
            f"Rank '{rank_name}' not found in defined rank lists when getting index."
        )
    return -1


async def send_discord_message(channel_id, message_content):
    # Using standard 4-space indentation
    """Helper function to send messages and handle common errors."""
    channel = bot.get_channel(channel_id)
    if channel:
        try:
            await channel.send(message_content)
            logger.debug(
                f"Sent message to channel {channel_id}: '{message_content[:50]}...'"
            )
            return True
        except discord.Forbidden:
            logger.error(
                f"Missing permissions to send message in channel {channel_id} ({getattr(channel, 'name', 'N/A')})"
            )
        except discord.HTTPException as e:
            logger.error(
                f"Failed to send message to channel {channel_id} ({getattr(channel, 'name', 'N/A')}): {e}"
            )
        except Exception as e:
            logger.exception(
                f"Unexpected error sending message to channel {channel_id}:"
            )
    else:
        logger.error(f"Could not find channel with ID {channel_id} to send message.")
    return False


# --- Bot Events ---


@bot.event
async def on_ready():
    # Using standard 4-space indentation
    """Called when the bot logs in and is ready."""
    logger.info(f"Logged in as {bot.user.name} ({bot.user.id})")
    logger.info("Sending startup message...")
    await send_discord_message(
        STARTUP_STATUS_CHANNEL,
        f"✅ **Bot Online!**\nMonitoring Group ID: {GROUP_ID}\nReady to check roles.",
    )

    logger.info("Setting initial presence...")
    try:
        await bot.change_presence(
            activity=discord.Game("Monitoring role changes"),
            status=discord.Status.online,
        )
    except Exception as e:
        logger.error(f"Failed to set initial presence: {e}")

    logger.info("Starting role monitoring task...")
    bot.loop.create_task(monitor_role_changes())  # Start the main loop


# --- Discussion Thread Helper Functions ---
async def has_recent_promo_demo_message(channel_id):
    """Check if the channel has a recent promotion/demotion message."""
    channel = bot.get_channel(channel_id)
    if not channel:
        logger.error(f"Channel with ID {channel_id} not found.")
        return False

    try:
        # Fetch the last 10 messages from the channel
        async for message in channel.history(limit=10):
            if (
                "promoted" in message.content.lower()
                or "demoted" in message.content.lower()
            ):
                logger.info(
                    f"Found recent promotion/demotion message in channel {channel_id}: {message.content[:50]}..."
                )
                return True
    except discord.Forbidden:
        logger.error(f"Missing permissions to read messages in channel {channel_id}.")
    except discord.HTTPException as e:
        logger.error(f"Failed to fetch messages from channel {channel_id}: {e}")
    except Exception as e:
        logger.exception(
            f"Unexpected error while checking messages in channel {channel_id}:"
        )

    return False


async def send_thread(channel_id, parent_message, thread_name):
    # channel_id: You know this
    # parent_message: The message body that you want to send for the parent of thread.
    # thread_name: The name of the thread you want to create
    channel = bot.get_channel(channel_id)

    message = await channel.send(parent_message)

    # Create a thread under the latest message ID
    await message.create_thread(name=thread_name, auto_archive_duration=1440)


async def send_thread_to_role(role_name):
    logger.info(f"Sending discussion threads for {role_name}.")
    thread_parent_message = (
        "# <:deviizer:1267031504123330674> Promotion and discussions 🗣️"
    )
    if role_name == LOW_RANKS[-1]:
        await send_thread(
            ENTRY_TEAM_CHANNEL, thread_parent_message, "Promotion and discussions 🗣️"
        )

    elif role_name == MID_RANKS[-1]:
        await send_thread(
            SUPERVISION_TEAM_CHANNEL,
            thread_parent_message,
            "Promotion and discussions 🗣️",
        )

    elif role_name == HIGH_RANKS[-1]:
        await send_thread(
            MANAGEMENT_TEAM_CHANNEL,
            thread_parent_message,
            "Promotion and discussions 🗣️",
        )


@bot.command(name="create_discussion_thread")
async def create_discussion_thread(ctx, role: str):
    """
    Command to create a discussion thread for a specific role or all roles.
    Usage: /create_discussion_thread <role>
    Example: /create_discussion_thread "Entry Team"
    """
    role = role.lower()

    if role == "all":
        # Create threads for all roles
        await send_thread_to_role(LOW_RANKS[-1])
        await send_thread_to_role(MID_RANKS[-1])
        await send_thread_to_role(HIGH_RANKS[-1])
        await ctx.send("✅ Discussion threads created for all roles.")
    elif role == "entry team":
        await send_thread_to_role(LOW_RANKS[-1])
        await ctx.send("✅ Discussion thread created for Entry Team.")
    elif role == "supervision team":
        await send_thread_to_role(MID_RANKS[-1])
        await ctx.send("✅ Discussion thread created for Supervision Team.")
    elif role in ["management", "corporate and leadership"]:
        await send_thread_to_role(HIGH_RANKS[-1])
        await ctx.send(
            "✅ Discussion thread created for Management, Corporate, and Leadership."
        )
    else:
        await ctx.send(
            "❌ Invalid role specified. Please use one of the following: `all`, `Entry Team`, `Supervision Team`, `Management, Corporate and Leadership`."
        )


# --- Main Monitoring Loop ---


async def monitor_role_changes():
    # Using standard 4-space indentation
    await bot.wait_until_ready()
    logger.info("Bot is ready. Role monitoring loop starting.")

    async with aiohttp.ClientSession() as session:
        while True:
            start_time = time.monotonic()
            logger.info("--- Starting new role check cycle ---")
            total_users_checked_in_cycle = 0  # Reset counter for this cycle
            roles_processed_count = 0

            roles = await fetch_roles(session, GROUP_ID)
            if not roles:
                logger.warning(
                    "No roles fetched. Cycle skipped. Retrying after 60 seconds."
                )
                try:
                    await bot.change_presence(
                        activity=discord.Game("Error fetching roles"),
                        status=discord.Status.dnd,
                    )
                except Exception as e:
                    logger.error(f"Failed to set error presence: {e}")
                await asyncio.sleep(60)
                continue

            roles_dict = {role["id"]: role["name"] for role in roles}

            try:
                data = await load_data()
                previous_user_roles = data.get("user_roles", {}).copy()
                current_users_processed = {}  # user_id -> role_id
                change_detected = False
                processed_role_names = []  # Keep track of roles processed in this cycle

                # --- Role Processing Loop ---
                for role in roles:
                    role_id = role["id"]
                    role_name = role["name"]
                    processed_role_names.append(role_name)  # Add to list for summary
                    logger.info(f"Processing role: {role_name} ({role_id})")

                    # Fetch users (status updated inside this function)                    
                    users = await fetch_users_in_role(
                        session, GROUP_ID, role_id, role_name
                    )
                    total_users_checked_in_cycle += len(
                        users
                    )  # Add count for this role
                    roles_processed_count += 1

                    # --- User Processing Loop ---
                    for user in users:
                        user_id = str(user["userId"])
                        username = user["username"]
                        current_users_processed[user_id] = role_id  # Store current role

                        previous_role_id = previous_user_roles.get(user_id)

                        if previous_role_id is None:
                            # New user detected
                            logger.info(
                                f"New user {username} ({user_id}) detected with role {role_name} ({role_id}). Storing initial role."
                            )
                            change_detected = True
                        elif previous_role_id != role_id:
                            # Role change detected
                            change_detected = True
                            previous_role_name = roles_dict.get(
                                previous_role_id, "Unknown Role"
                            )
                            current_rank_name = role_name  # Already have this

                            current_rank_index = get_rank_index(current_rank_name)
                            previous_rank_index = get_rank_index(previous_role_name)

                            action = "changed role to"  # Default action

                            # Determine if promotion or demotion (check indices are valid first)
                            if (
                                previous_role_name != "Unknown Role"
                                and current_rank_index != -1
                                and previous_rank_index != -1
                            ):
                                if current_rank_index > previous_rank_index:
                                    action = "promoted"
                                elif current_rank_index < previous_rank_index:
                                    action = "demoted"
                                else:
                                    # Optional: Log if IDs changed but index didn't
                                    logger.warning(
                                        f"User {username} ({user_id}) changed role ID ({previous_role_id} -> {role_id}) but rank index remained the same ({current_rank_index}). Names: '{previous_role_name}' -> '{current_rank_name}'"
                                    )

                            # ============================================================== #
                            # V V V V V V V V V V V V V  LOGIC CHANGE IS HERE V V V V V V V V #
                            # ============================================================== #

                            # --- Determine Notification Channel & Mention (Conditional Logic) ---
                            channel_rank_name_for_lookup = None
                            mention_rank_name_for_lookup = None

                            if action == "promoted":
                                # For promotions, post in the NEW rank's channel and mention that category
                                channel_rank_name_for_lookup = current_rank_name
                                mention_rank_name_for_lookup = current_rank_name
                                logger.debug(
                                    f"Promotion detected. Targeting channel/mention for new rank: {current_rank_name}"
                                )
                            elif action == "demoted":
                                # For demotions, post in the OLD rank's channel and mention that category
                                channel_rank_name_for_lookup = previous_role_name
                                mention_rank_name_for_lookup = previous_role_name
                                logger.debug(
                                    f"Demotion detected. Targeting channel/mention for old rank: {previous_role_name}"
                                )
                            else:  # Default for "assigned", "changed role to", unknown previous rank etc.
                                # Post in the NEW rank's channel and mention that category
                                channel_rank_name_for_lookup = current_rank_name
                                mention_rank_name_for_lookup = current_rank_name
                                logger.debug(
                                    f"Action '{action}'. Targeting channel/mention for new rank: {current_rank_name}"
                                )

                            # Get the channel ID based on the determined rank name
                            channel_id, _ = (
                                get_rank_category_and_mention(
                                    channel_rank_name_for_lookup
                                )
                                if channel_rank_name_for_lookup
                                else (None, None)
                            )
                            # Get the mention based on the determined rank name
                            _, mention = (
                                get_rank_category_and_mention(
                                    mention_rank_name_for_lookup
                                )
                                if mention_rank_name_for_lookup
                                else (None, None)
                            )

                            # --- Send Notification ---
                            if channel_id:
                                profile_link = f"[{username}](<https://www.roblox.com/users/{user_id}/profile>)"
                                message = f"{profile_link} has been {action} from **{previous_role_name}** to **{current_rank_name}** {mention or ''}"
                                await send_discord_message(channel_id, message)
                                logger.info(
                                    f"Sent change notification to channel {channel_id} for {username} {action} from {previous_role_name} to {current_rank_name}"
                                )
                            else:
                                logger.debug(
                                    f"No notification channel configured based on lookup rank: {channel_rank_name_for_lookup}"
                                )

                            # ============================================================== #
                            # ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ END OF LOGIC CHANGE ^ ^ ^ ^ ^ ^ ^ ^ ^ #
                            # ============================================================== #

                        # else: user role hasn't changed, do nothing

                    logger.debug(
                        f"Finished processing {len(users)} users for role {role_name}."
                    )
                    if (
                        role_name in LOW_RANKS[-1]
                        or role_name in MID_RANKS[-1]
                        or role_name in HIGH_RANKS[-1]
                    ):
                        logger.info(
                            f"Preparing to ending discussion threads for {role_name}."
                        )
                        channel_id, _ = get_rank_category_and_mention(role_name)

                        if await has_recent_promo_demo_message(channel_id):

                            await send_thread_to_role(role_name)

                        else:

                            logger.info(
                                f"No recent promotion/demotion message found in channel {channel_id}. Skipping thread creation."
                            )  # Send discussion threads to the role
                    else:
                        logger.debug(
                            f"Role {role_name} is not the last item in the LOW/MID/HIGH rank arrays Skipping discussion thread creation."
                        )
                    # Small delay between processing roles (using user's last provided value)
                    await asyncio.sleep(0.1)  # 100ms delay

                # --- Post-Processing Checks (Removals) ---
                removed_user_ids = set(previous_user_roles.keys()) - set(
                    current_users_processed.keys()
                )
                if removed_user_ids:
                    logger.info(
                        f"Detected {len(removed_user_ids)} users potentially removed or ranked to Guest."
                    )
                    for user_id in removed_user_ids:
                        previous_role_id = previous_user_roles[user_id]
                        previous_role_name = roles_dict.get(
                            previous_role_id, "Unknown Role ID"
                        )
                        logger.info(
                            f"User {user_id} (previously {previous_role_name} [{previous_role_id}]) is no longer found in fetched roles. Removing from tracking."
                        )
                        # Optional: Send removal notification to a log channel
                        change_detected = True

                # --- Save Data if Changes Occurred ---
                if change_detected:
                    logger.info(
                        "Changes detected, updating stored user roles in info.json."
                    )
                    data["user_roles"] = current_users_processed
                    await save_data(data)
                else:
                    logger.info("No role changes detected in this cycle.")

            except Exception as e:
                logger.exception(
                    "An critical error occurred during the role processing part of the cycle:"
                )
                # Try to set status to indicate error
                try:
                    await bot.change_presence(
                        activity=discord.Game("Error during processing"),
                        status=discord.Status.dnd,
                    )
                except Exception as se:
                    logger.error(f"Failed to set error status: {se}")

            # --- Cycle Completion & Summary ---
            finally:
                # Reset status to default monitoring state regardless of errors in processing
                try:
                    await bot.change_presence(
                        activity=discord.Game("Monitoring role changes"),
                        status=discord.Status.online,
                    )
                    logger.info("Resetting status to: Monitoring role changes")
                except Exception as e:
                    logger.error(f"Failed to reset presence after cycle: {e}")

            end_time = time.monotonic()
            cycle_duration_seconds = end_time - start_time

            # Format Time
            total_seconds_int = int(cycle_duration_seconds)
            hours, remainder = divmod(total_seconds_int, 3600)
            minutes, seconds = divmod(remainder, 60)
            time_parts = []
            if hours > 0:
                time_parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes > 0:
                time_parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            # Display fractional seconds only if total duration is less than a minute
            if hours == 0 and minutes == 0:
                time_parts.append(
                    f"{cycle_duration_seconds:.3f} second{'s' if cycle_duration_seconds != 1 else ''}"
                )
            else:
                time_parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
            formatted_time = (
                ", ".join(time_parts)
                if time_parts
                else f"{cycle_duration_seconds:.3f} seconds"
            )

            # --- Send Cycle Summary Message ---
            summary_message = (
                f"📊 **Cycle Summary**\n"
                f"Processed {roles_processed_count}/{len(roles)} roles.\n"
                f"Checked a total of **{total_users_checked_in_cycle}** user entries.\n"
                f"Cycle duration: {formatted_time}."
            )
            await send_discord_message(CYCLE_INFO_CHANNEL, summary_message)
            logger.info(
                f"Cycle completed. Users checked: {total_users_checked_in_cycle}. Duration: {formatted_time}."
            )

            # --- Sleep ---
            logger.info("Sleeping for 1 second...")
            # Keeping the sleep value from the user's last paste, although 1 second is recommended.
            await asyncio.sleep(0.00001)


# --- Run the Bot ---
if __name__ == "__main__":
    # Check if the token is missing or still the placeholder (user requested check removed, but good practice)
    # if not TOKEN or TOKEN == "YOUR_BOT_TOKEN_HERE":
    #     logger.critical("BOT TOKEN IS MISSING OR INVALID. Please set it correctly.")
    # else:
    try:
        # This line is indented under the 'try'
        logger.info("Attempting to run the bot...")
        # Run the bot
        bot.run(TOKEN, log_handler=None)  # Use our configured logger
    # These 'except' blocks are indented at the same level as 'try'
    except discord.LoginFailure:
        logger.critical("CRITICAL: Failed to log in - Improper token provided.")
    except Exception as e:
        logger.critical(f"CRITICAL: Error running bot: {e}", exc_info=True)