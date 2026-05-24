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

# Channel IDs
CUSTOMER_HEAD_OP_CHANNEL = 1413577828498276474
SHIFT_LEADER_GEN_MANAGER_CHANNEL = 1413577873159229481
JUNIOR_DIRECTOR_CHAIRMAN_CHANNEL = 1413578146120204298
TIME_TRACKING_CHANNEL_ID = 1413620449912295645

# Role mention IDs
LOW_RANK_ROLE_MENTION = "<@&1328338426713342023>"
MID_RANK_ROLE_MENTION = "<@&1328338484104134688>"
HIGH_RANK_ROLE_MENTION = "<@1114892999474815126> <@& 1328338542132330506>"

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
MGMT_RANKS = [
    "Assistant Director",
    "Junior Director",
    "Senior Director",
    "Head Director",
]
CORP_RANKS = [
    "Corporate Intern",
    "Junior Corporate",
    "Senior Corporate",
    "Head Corporate",
]
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
ALL_RANKS = ET_RANKS + ST_RANKS + HIGH_RANKS
ALL_M_RANKS_LIST = [ET_RANKS, ST_RANKS, MGMT_RANKS, CORP_RANKS, LS_RANKS]

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
                if response.status not in (200, 429) or str(response.status).startswith(
                    "5"
                ):
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


def get_group_rank_name(user_id, group_id):
    url = f"https://groups.roblox.com/v2/users/{user_id}/groups/roles"
    response = requests.get(url)
    response.raise_for_status()

    for group in response.json()["data"]:
        if group["group"]["id"] == group_id:
            return group["role"]["name"]
    return None


async def monitor_role_changes(disallowed_rank_names=None):
    message = "Bot started! Monitoring role changes..."
    await safe_send(message, channel_id=TIME_TRACKING_CHANNEL_ID, bot=bot)  
    
    async with aiohttp.ClientSession() as session:
        while True:
            start_time = time.time()
            logger.info("🔎 Checking for role changes...")
            message = "Starting role check..."
            await safe_send(message, channel_id=TIME_TRACKING_CHANNEL_ID, bot=bot)

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

                            if not special_patches.check_user(  # function returns True if the user shouldn't be
                                user,
                                current_rank,
                                prev_role_name,
                                action,  #  ignored for this change, False if
                            ):  #                it should be processed as ignoredThat's why for not instruction
                                continue

                            if (
                                get_group_rank_name(user["userId"], GROUP_ID)
                                == current_rank
                            ):
                                logger.info(
                                    f"✅ Verified {user['username']} is actually {action} to {current_rank}."
                                )
                            else:
                                logger.warning(
                                    f"⚠️ Verification failed: {user['username']} is not actually {action} to {current_rank} according to Roblox. Skipping notification."
                                )
                                notification_channel = bot.get_channel(
                                    TIME_TRACKING_CHANNEL_ID
                                )
                                if notification_channel:
                                    await safe_send(  # Sent when user likely has more than one role
                                        message=f"⚠️ User {user['username']} likely has more than one role. Roblox API returns {get_group_rank_name(user['userId'], GROUP_ID)} when asked directly about user, found in {current_rank}. <@1114892999474815126>",
                                        channel_id=TIME_TRACKING_CHANNEL_ID,
                                        bot=bot,
                                    )
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
                f"* 🕐 Started at <t:{int(start_time)}:T>, ended at <t:{int(end_time)}:T>.\n\n"
                f"* 🔍 Next check in approximately <t:{str(int(time.time() + 180))}:T>."
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
        # all_lower_HO.extend(MID_RANKS)
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
