import platform
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
import threading, asyncio

import discord
from discord import Embed, Color
from discord.ui import View, Button
from discord.ext import commands

import logging_setup
from app import (
    ALL_M_RANKS_LIST,
    get_rank_index,
    get_rank_category_and_mention,
    get_group_rank_name,
    safe_send_and_pub,
    save_data,
    GROUP_ID,
    fetch_roles,
    DATA_FILE,
)

from roblox import RobloxUser
import special_patches

# Set up logger
logger: logging.Logger = logging_setup.setup_logging(
    name="bot.commands", rankspy_default_level=True
)
logger.setLevel(logging.DEBUG)  # Set to DEBUG for detailed trace, INFO for less verbosity

try:
    from trello import (
        fetch_cards,
        find_cards_by_username,
        parse_card,
        BOARD_NAME_MAP,
        fetch_meta_bgimg_140,
    )
except ImportError as e:
    logger.error(f"Error importing modules: {e}")

try:
    from reverse import get_single_user_dict_from_announcements, ANNOUNCE_CHANNEL_ID
except ImportError as e:
    logger.error(f"Error importing modules: {e}")

from utils import build_trello_board_embed, build_reverse_embed

MAX_EMBED_DESC = 1024  # Discord embed field character limit
BOARDS: dict[str, tuple[Color, str]] = {
    "hcDUWrFo": (Color.orange(), "WPL"),
    "8ttvsMXg": (Color.green(), "WCH"),
}
WCH_INVITE_URL: str = "https://discord.gg/g2PFKDbBCd"
BOT_ICON_URL: str = (
    "https://static.wikia.nocookie.net/washiez/images/5/53/Washiez_Wiki_Bot_Developers.webp/revision/latest"
)


class MyBot(commands.Bot):
    ROLE_PROGRESS_LOCK: asyncio.Lock  # Tell Pylance this exists
    ROLE_PROGRESS: dict[str, dict[str, int | bool | float]]
    roblox_limiter: "RobloxLimiter"


async def threads_tasks():
    results = []
    frames = sys._current_frames()

    for thread in threading.enumerate():
        info = []
        try:
            loop = asyncio.get_running_loop()
            for task in asyncio.all_tasks(loop):
                coro = task.get_coro()
                frame = getattr(coro, "cr_frame", None)
                if frame:
                    info.append(f"{task.get_name()} @ {frame.f_code.co_name}:{frame.f_lineno}")
        except RuntimeError:
            pass

        frame = frames.get(thread.ident)
        if frame:
            info.append(f"[sync] {frame.f_code.co_name}:{frame.f_lineno}")

        results.append((thread.name, thread.ident, info))
    return results


async def trello_check_main(
    interaction: discord.Interaction, username: str, group_id: int = 10261023
) -> tuple[list[Embed], View]:
    """Execute Trello check sub-workflow and build embeds/views."""
    user = await RobloxUser.create(username)
    embeds: list[Embed] = []

    # --- Primary user embed ---
    user_embed = Embed(title=user._username, color=10181046)
    user_embed.set_author(name="User information: Trello", icon_url=BOT_ICON_URL)
    user_embed.set_thumbnail(url=await user.fetch_thumbnail("bust"))
    
    curr_rank = await user.get_rank(group_id)
    user_embed.add_field(name="Joined Roblox", value=await user.get_joined_roblox(), inline=False)
    user_embed.add_field(name="Joined Washiez", value="Unknown", inline=False)
    user_embed.add_field(name="Current Rank", value=curr_rank, inline=False)
    embeds.append(user_embed)

    # --- Board embeds ---
    view = View()
    for board_id, (color, name) in BOARDS.items():
        cards = fetch_cards(board_id)
        matches = [card for card in cards if username in card["name"].lower()]
        if not matches:
            embeds.append(
                Embed(description="No matching cards found.", color=color)
                .set_author(name=f"Trello User Information: {name} Board")
                .set_footer(
                    text=(
                        "No cards found with the specified username and rank"
                        " criteria. Experimental. Copyright of Data by Trello"
                        " Board owner, contributors or other entities."
                    )
                )
            )
            continue

        icon = fetch_meta_bgimg_140(board_id)
        embeds.append(build_trello_board_embed(username, name, matches, color, icon=icon))

        button = Button(label=f"Open {name} Trello Board", url=f"https://trello.com/b/{board_id}")
        view.add_item(button)

        for card in matches[:2]:
            url = card.get("shortUrl")
            if url:
                view.add_item(Button(label=f"Open card on {name}", url=url))

        if name == "WCH":
            view.add_item(
                Button(
                    label="Request to be added onto Washiez Community Hub (WCH)",
                    url=WCH_INVITE_URL,
                )
            )
    return embeds, view


async def chain_check_main(
    interaction: discord.Interaction, username: str, group_id: int = 10261023
) -> tuple[list[Embed], View]:
    """Execute event chain history sub-workflow and build embeds/views."""
    user = await RobloxUser.create(username)
    embeds: list[Embed] = []

    # --- Primary user embed ---
    user_embed = Embed(title=user._username, color=10181046)
    user_embed.set_author(name="User information: Reverse Search", icon_url=BOT_ICON_URL)
    user_embed.set_thumbnail(url=await user.fetch_thumbnail("bust"))

    curr_rank = await user.get_rank(group_id)
    user_embed.add_field(name="Joined Roblox", value=await user.get_joined_roblox(), inline=False)
    user_embed.add_field(name="Joined Washiez", value="Unknown", inline=False)
    user_embed.add_field(name="Current Rank", value=curr_rank, inline=False)
    user_embed.add_field(name="Profile URL", value=user.profile_url, inline=False)
    embeds.append(user_embed)

    # --- History / Chain embed ---
    history_data = await get_single_user_dict_from_announcements(
        interaction.client,
        user._user_id,
        interaction.guild.id,
        1276397232341520469,
        channel_id=ANNOUNCE_CHANNEL_ID,
        limit=1000,
    )

    view = View()

    if not history_data or not history_data.get("events"):
        chain_embed = Embed(description="No event history found.", color=Color.orange())
        chain_embed.set_author(name=f"Chain User Information: {username}")
        embeds.append(chain_embed)
        return embeds, view
    else:
        color = Color.blue()
        icon = await user.fetch_thumbnail("bust")
        chain_embed = build_reverse_embed(username, history_data, color, icon=icon)
        embeds.append(chain_embed)
        for event in history_data.get("events", [])[::-1][:2]:
            source = event.get("source", {})
            url = source.get("url")
            if url:
                action_label = event.get("action", "event").capitalize()
                view.add_item(Button(label=f"Open {action_label} Message", url=url))
        return embeds, view


def setup(bot: MyBot):
    logger.info("Loading commands extension.")

    @bot.slash_command(name="rinse_test", description="Test the bot's response time.")
    async def rinse_test(ctx: discord.ApplicationContext):
        try:
            logger.info("rinse_test command invoked.")
            await ctx.defer(ephemeral=True)
            start = time.monotonic()
            await ctx.edit(content="Pinging...")
            latency = round((time.monotonic() - start) * 1000)
            await ctx.edit(
                content=(
                    f"🧼 Foam response time: {latency} ms 🫧\n\n"
                    f"> {time.strftime('%d-%m-%Y %H:%M:%S', datetime.now(timezone.utc).timetuple())} UTC"
                )
            )
            logger.debug("rinse_test command completed.")
        except Exception as e:
            logger.error(f"Error in rinse_test command: {e}")
            await ctx.followup(content="An error occurred while processing your request.")

    @bot.slash_command(
        name="ping", description="Check if bot is alive", guild_ids=[1113097535796560014]
    )
    async def ping(ctx: discord.ApplicationContext):
        logger.info("ping command invoked.")
        await ctx.respond("Pong!")
        logger.debug("Pong response sent.")

    @bot.slash_command(
        name="shutdown",
        description="Shutdown the bot",
        guild_ids=[1113097535796560014],
        default_member_permissions=discord.Permissions(administrator=True),
    )
    async def shutdown_bot(ctx: discord.ApplicationContext):
        try:
            await ctx.respond("🛑 Shutting down bot...")
            logger.info("Shutdown requested.")
            try:
                await bot.close()
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")
            if platform.system() == "Windows":
                sys.exit(0)
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error in shutdown command: {e}")
            await ctx.followup(content="An error occurred while processing your request.")

    if platform.system() == "Linux":

        @bot.slash_command(
            name="restart",
            description="Restart the bot",
            guild_ids=[1113097535796560014],
            default_member_permissions=discord.Permissions(administrator=True),
        )
        async def restart_bot(ctx: discord.ApplicationContext):
            try:
                await ctx.respond("🔄 Restarting bot...")
                logger.info("Restart requested.")
                await bot.close()
                sys.exit(0)
            except Exception as e:
                logger.error(f"Error in restart command: {e}")
                await ctx.followup(content="An error occurred while processing your request.")

    @bot.slash_command(
        name="threads_tasks",
        description="List threads and asyncio tasks",
        default_member_permissions=discord.Permissions(administrator=True),
        guild_ids=[1113097535796560014],
    )
    async def threads_tasks_cmd(ctx: discord.ApplicationContext):
        try:
            logger.info("threads_tasks command invoked.")
            await ctx.response.defer()
            info = await threads_tasks()
            out = []

            for name, ident, tasks in info:
                out.append(f"**Thread:** {name} ({ident})")
                out.extend(f"* {t}" for t in tasks or ["No tasks"])

            text = "\n".join(out)
            for i in range(0, len(text), 2000):
                if i == 0:
                    await ctx.edit(content=text[i : i + 2000])
                else:
                    await ctx.send_followup(content=text[i : i + 2000])
            logger.debug("threads_tasks command completed.")
        except Exception as e:
            logger.error(f"Error in threads_tasks command: {e}")
            await ctx.followup(content="An error occurred while processing your request.")

    @bot.slash_command(
        name="trello_check",
        description="Check both WPL and WCH Trello Boards for a user",
    )
    async def trello_check(
        interaction: discord.Interaction,
        username: str,
        group_id: int = 10261023,
        required_rank: str | None = None,
    ) -> bool:
        await interaction.response.defer()
        try:
            logger.info("trello_check command invoked.")
            embeds, view = await trello_check_main(interaction, username, group_id)
            await interaction.followup.send(embeds=embeds, view=view)
            logger.debug("trello_check command completed.")
            return True
        except Exception as e:
            logger.exception("trello_check failed")
            await interaction.followup.send(
                f"An error occurred while processing your request.\n{str(e)}"
            )
            return False

    @bot.slash_command(
        name="chain_check",
        description="Check promotion and demotion history for a user",
    )
    async def chain_check(
        interaction: discord.Interaction,
        username: str,
        group_id: int = 10261023,
        required_rank: str | None = None,
    ) -> bool:
        await interaction.response.defer()
        try:
            logger.info("chain_check command invoked.")
            embeds, view = await chain_check_main(interaction, username, group_id)
            await interaction.followup.send(embeds=embeds, view=view)
            logger.debug("chain_check command completed.")
            return True
        except Exception as e:
            logger.exception("chain_check failed")
            await interaction.followup.send(
                f"An error occurred while processing your request.\n{str(e)}"
            )
            return False

    @bot.slash_command(
        name="check",
        description=(
            "Check Trello boards (WPL & WCH) and promotion/demotion history for a user"
        ),
    )
    async def check(
        interaction: discord.Interaction,
        username: str,
        group_id: int = 10261023,
        required_rank: str | None = None,
    ) -> bool:
        await interaction.response.defer()
        try:
            logger.info("check command invoked.")
            user = await RobloxUser.create(username)

            embeds: list[Embed] = []
            combined_view = View()

            # --- Primary user embed ---
            thumbnail = await user.fetch_thumbnail("bust")
            curr_rank = await user.get_rank(group_id)

            user_embed = Embed(title=user._username, color=10181046)
            user_embed.set_author(name="User information: Check", icon_url=BOT_ICON_URL)
            user_embed.set_thumbnail(url=thumbnail)
            user_embed.add_field(
                name="Joined Roblox", value=await user.get_joined_roblox(), inline=False
            )
            user_embed.add_field(name="Joined Washiez", value="Unknown", inline=False)
            user_embed.add_field(name="Current Rank", value=curr_rank, inline=False)
            user_embed.add_field(name="Profile URL", value=user.profile_url, inline=False)
            embeds.append(user_embed)

            # --- Trello board embeds ---
            embeds_trello, view_trello = await trello_check_main(
                interaction, username, group_id
            )
            embeds.extend(embeds_trello[1:])  # Skip duplicate user embed
            for item in view_trello.children:
                combined_view.add_item(item)

            # --- Promotion / demotion chain embed ---
            embeds_chain, view_chain = await chain_check_main(
                interaction, username, group_id
            )
            embeds.extend(embeds_chain[1:])  # Skip duplicate user embed
            for item in view_chain.children:
                combined_view.add_item(item)

            await interaction.followup.send(embeds=embeds, view=combined_view)
            logger.debug("check command completed.")
            return True
        except Exception as e:
            logger.exception("check failed")
            await interaction.followup.send(
                f"An error occurred while processing your request.\n{str(e)}"
            )
            return False

    @bot.slash_command(
        name="check_user_roles",
        description="Check which roles a user have and compare",
        guild_ids=[1113097535796560014],
    )
    async def check_user_roles(ctx: discord.ApplicationContext, roblox_username: str):
        await ctx.defer()

        try:
            data = ctx.bot.data
            roles_dict = ctx.bot.roles_dict  # Expected format: {role_id: role_name}

            name_to_id = {v: k for k, v in roles_dict.items()}

            logger.info(f"role_checking invoked for {roblox_username}.")
            rblx_usr = await RobloxUser.create(roblox_username)

            curr_rank = await rblx_usr.get_rank(10261023)

            if not curr_rank:
                await ctx.followup.send("User has no roles found in the group.")
                return

            current_rank = curr_rank["role_name"]
            user_id = str(rblx_usr._user_id)
            current_index = get_rank_index(current_rank)
            current_role_id = name_to_id.get(current_rank)

            prev_role_name = "N/A"
            prev_role_id = "N/A"

            if user_id in data["user_roles"]:
                prev_role_id = data["user_roles"][user_id]
                prev_role_name = roles_dict.get(prev_role_id, "Unknown")

            await ctx.followup.send(
                f"Current Rank: {current_rank} (ID: {current_role_id})\n"
                f"Previous Rank: {prev_role_name} (ID: {prev_role_id})"
            )
        except Exception as e:
            logger.exception("check_user_roles failed")
            await ctx.followup.send(f"An error occurred: {str(e)}")
    
    logger.debug("Registering commands: check_role_users...")
    import asyncio
    import aiohttp  # Or aiohttp session if fetch_roles uses async HTTP client
    from app import LOW_RANKS, MID_RANKS  # Assuming these are defined in app.py
    
    exempt_roles = [*LOW_RANKS, *MID_RANKS, "Member", "Guest"]
    EXEMPT_SET = set(exempt_roles)

    async def _fetch_and_set_roles_dict(bot_inst):
        """
        Fetch group roles asynchronously and populate bot.roles_dict.

        :param bot_inst: Discord bot instance.
        :returns: Dictionary mapping role IDs to role names.
        """
        async with aiohttp.ClientSession() as session:
            roles = await fetch_roles(session, GROUP_ID)
            
            # Filter out exempt roles before dict creation
            bot_inst.roles_dict = {
                role["id"]: role["name"]
                for role in roles
                if role["name"] not in EXEMPT_SET
            }
            
            return bot_inst.roles_dict

    # Populate bot.roles_dict before command registration
    bot.roles_dict = asyncio.run(_fetch_and_set_roles_dict(bot))

    # Deduplicate and format roles into a valid choice list (Max 25 for Discord API)
    role_choices = list(set(bot.roles_dict.values()))[:25]
    
    del exempt_roles, EXEMPT_SET  # Clean up namespace

    @bot.slash_command(
        name="check_role_users",
        description="Check all users in specific role for rank changes",
        guild_ids=[1113097535796560014]
    )
    async def check_role_users(
        ctx: discord.ApplicationContext, 
        role_name: discord.Option(
            str, 
            description="Select target role to check",
            choices=role_choices
        )
    ):
        """
        Fetch users from Roblox API in target role and compare role_id directly with local data.
        Also detects users who have left the role. Prioritizes rank changes over no changes.

        :param ctx: Discord application context.
        :param role_name: Selected role name from choice list.
        :returns: None
        """
        await ctx.defer()
        
        try:
            data = ctx.bot.data
            roles_dict = ctx.bot.roles_dict  # {role_id: role_name}
            name_to_id = {v: k for k, v in roles_dict.items()}
            
            target_role_id = name_to_id.get(role_name)
            if not target_role_id:
                await ctx.followup.send(f"Role `{role_name}` not found in roles_dict.")
                return

            logger.info(f"check_role_users invoked for role '{role_name}' (Role ID: {target_role_id}).")

            # 1. Fetch live users from Roblox Group Role API
            # GET https://groups.roblox.com/v1/groups/{groupId}/roles/{roleSetId}/users
            target_users = []
            cursor = ""
            
            async with aiohttp.ClientSession() as session:
                while True:
                    url = f"https://groups.roblox.com/v1/groups/{GROUP_ID}/roles/{target_role_id}/users?limit=100&cursor={cursor}"
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            logger.error(f"Failed to fetch role members: {resp.status}")
                            break
                        res_json = await resp.json()
                        
                        target_users.extend(res_json.get("data", []))
                        cursor = res_json.get("nextPageCursor")
                        if not cursor:
                            break

            if not target_users:
                await ctx.followup.send(f"No users found in group for role `{role_name}`.")
                return

            # Get set of user IDs currently in the remote role
            remote_user_ids = {str(user["userId"]) for user in target_users}
            
            # Find users in local cache who have this role but aren't in remote
            left_role_users = []
            for user_id, cached_role_id in data["user_roles"].items():
                # Ensure both are strings for comparison
                if str(cached_role_id) == str(target_role_id) and user_id not in remote_user_ids:
                    left_role_users.append({
                        "user_id": user_id,
                        "role_id": cached_role_id,
                        "role_name": role_name
                    })

            logger.info(f"Found {len(left_role_users)} users who left role '{role_name}'")

            results = []
            updated_count = 0

            # 2. Iterate through live API users & compare directly with cached data
            for user_data in target_users:
                user_id = str(user_data["userId"])
                username = user_data["username"]

                # Direct compare live target_role_id against cached role_id
                current_role_id = target_role_id
                current_rank = role_name
                current_index = get_rank_index(current_rank)

                prev_role_id = data["user_roles"].get(user_id, "N/A")
                prev_role_name = roles_dict.get(prev_role_id, "Unknown")
                prev_index = get_rank_index(prev_role_name)

                action = None
                if current_index != -1 and prev_index != -1 and current_index != prev_index:
                    action = "promoted" if current_index > prev_index else "demoted"
                    channel_id, mention = get_rank_category_and_mention(current_rank)

                    if not special_patches.check_user({"userId": int(user_id)}, current_rank, prev_role_name, action):
                        results.append((2, f"• {username}: Ignored / special patch"))
                        continue

                    if channel_id:
                        profile_link = f"[{username}](<https://www.roblox.com/users/{user_id}/profile>)"
                        message = f"{profile_link} has been {action} from {prev_role_name} to {current_rank} {mention}"
                        await safe_send_and_pub(message=message, channel_id=channel_id, bot=bot)
                        
                        data["user_roles"][user_id] = current_role_id
                        updated_count += 1
                        
                    results.append((1, f"• {username}: **{action.capitalize()}** → {current_rank}"))
                else:
                    # Update role ID if untracked previously
                    if prev_role_id == "N/A":
                        data["user_roles"][user_id] = current_role_id
                        updated_count += 1
                    results.append((2, f"• {username}: No change ({current_rank})"))

            # 3. Process users who LEFT the role
            if left_role_users:
                async with aiohttp.ClientSession() as session:
                    for user_info in left_role_users:
                        user_id = user_info["user_id"]
                        prev_role_id = user_info["role_id"]
                        prev_role_name = user_info["role_name"]
                        new_role_name = "Guest"
                        new_role_id = name_to_id.get(new_role_name)

                        # Validate Guest role exists in the system
                        if not new_role_id:
                            logger.warning(f"Guest role not found in roles_dict for user {user_id}")
                            results.append((2, f"• User_{user_id}: Left role (Guest role undefined)"))
                            continue

                        # Try to fetch username from Roblox API
                        username = f"User_{user_id}"
                        try:
                            async with session.get(f"https://users.roblox.com/v1/users/{user_id}") as resp:
                                if resp.status == 200:
                                    user_json = await resp.json()
                                    username = user_json.get("name", f"User_{user_id}")
                        except aiohttp.ClientError as e:
                            logger.warning(f"Failed to fetch username for {user_id}: {e}")
                        except Exception as e:
                            logger.exception(f"Unexpected error fetching username for {user_id}: {e}")

                        prev_index = get_rank_index(prev_role_name)

                        logger.debug(f"User {user_id} ({username}): prev={prev_role_name}(idx={prev_index}), left=True")

                        # They left the role (only check prev_index is valid)
                        if prev_index != -1:
                            action = "left"
                            
                            # Send in the role's channel
                            channel_id, mention = get_rank_category_and_mention(prev_role_name)
                            mention = ""
                            
                            logger.debug(f"User {user_id} ({username}): channel_id={channel_id}")

                            if not special_patches.check_user(
                                {"userId": int(user_id)}, 
                                new_role_name, 
                                prev_role_name, 
                                action
                            ):
                                results.append((2, f"• {username}: Left role (ignored / special patch)"))
                                continue

                            if channel_id:
                                try:
                                    profile_link = f"[{username}](<https://www.roblox.com/users/{user_id}/profile>)"
                                    message = f"{profile_link} has {action} {prev_role_name} {mention}"
                                    
                                    logger.info(f"Sending left message for {user_id}: {message}")
                                    await safe_send_and_pub(message=message, channel_id=channel_id, bot=bot)
                                    
                                    data["user_roles"][user_id] = new_role_id
                                    updated_count += 1
                                    results.append((1, f"• {username}: **Left** {prev_role_name}"))
                                except Exception as e:
                                    logger.error(f"Failed to send left message for {user_id}: {e}")
                                    results.append((1, f"• {username}: Left role (send failed)"))
                            else:
                                logger.warning(f"No channel found for {prev_role_name}")
                                results.append((1, f"• {username}: **Left** {prev_role_name} (no channel)"))
                        else:
                            logger.debug(f"User {user_id}: prev_index invalid ({prev_index})")
                            results.append((1, f"• {username}: Left role"))

            if updated_count > 0:
                await save_data(data)

            # Sort results: changes first (priority 1), no changes last (priority 2)
            results.sort(key=lambda x: (x[0], x[1]))
            
            # Extract just the text
            results_text = [r[1] for r in results]

            logger.info(
                f"check_role_users completed for '{role_name}': "
                f"{len(target_users)} current, {len(left_role_users)} left, {updated_count} updated"
            )

            summary = "\n".join(results_text[:20])
            if len(results_text) > 20:
                summary += f"\n...and {len(results_text) - 20} more."

            resp_embed = discord.Embed(
                title=f"Role Check: {role_name}",
                description=summary or "No results.",
                color=discord.Color.blue()
            )
            resp_embed.add_field(name="In Role", value=str(len(target_users)), inline=True)
            resp_embed.add_field(name="Left Role", value=str(len(left_role_users)), inline=True)
            resp_embed.add_field(name="Updated", value=str(updated_count), inline=True)

            await ctx.followup.send(embed=resp_embed)

        except Exception as e:
            logger.exception("check_role_users failed")
            await ctx.followup.send(f"An error occurred: {str(e)}")
            
    logger.debug("Registering commands: role_checking...")
    @bot.slash_command(
        name="role_checking",
        description="Check which roles are still being checked",
        guild_ids=[1113097535796560014],
    )
    async def role_checking(ctx: discord.ApplicationContext):
        await ctx.response.defer()

        try:
            logger.info("role_checking invoked.")

            print(bot.ROLE_PROGRESS_LOCK)

            # if not hasattr(bot, "ROLE_PROGRESS"):
            #     await ctx.followup.send("ℹ️ Role monitoring has not started yet.")
            #     return

            if not bot.ROLE_PROGRESS_LOCK:
                await ctx.followup.send("ℹ️ Role monitoring has not started yet.")
                return
            if not isinstance(bot.ROLE_PROGRESS_LOCK, asyncio.Lock):
                await ctx.followup.send("ℹ️ Role monitoring is not properly initialized.")

            async with bot.ROLE_PROGRESS_LOCK:
                still_running = {
                    name: info
                    for name, info in bot.ROLE_PROGRESS.items()
                    if not info.get("done", False)
                }

            if not still_running:
                await ctx.followup.send("✅ All role checks complete.")
                return

            lines = []
            for name, info in still_running.items():
                checked = info["checked"]
                total = info["total"]

                remaining = total - checked if total else None

                time_elapsed = time.time() - info["start"]
                ups = checked / time_elapsed if time_elapsed > 0 else 0.0

                if checked == 0:
                    eta_str = "(N/A)..."
                elif remaining is not None and ups > 0:
                    time_remaining = int(remaining / ups)
                    eta_str = f"~{str(timedelta(seconds=time_remaining))}"
                else:
                    eta_str = "?"

                remaining_str = str(remaining) if remaining is not None else "?"
                progress_str = f"{checked}/{total}" if total else f"{checked}/?"

                lines.append(
                    f"- {name}: {progress_str} ({remaining_str} left, {eta_str} remaining)"
                )
            
            # Include roles which hasn't been processed yet.
            for name in bot.ROLE_PROGRESS:
                if name not in still_running:
                    lines.append(f"- {name}: Not started yet or has been completed.")
            
            # Reorder the lines to follow catergories and orders of the roles
            # This is the actual reordering logic which the order is 
            ordered_lines = {}
            for line in lines:
                role_name = line.split(":")[0].strip("- ").strip()
                ordered_lines[role_name] = line
            
            for role_group in ALL_M_RANKS_LIST:
                for role in role_group:
                    if role in ordered_lines:
                        lines.append(ordered_lines[role])
                        del ordered_lines[role]
            
            msg = "⏳ Role checks still in progress (or complete):\n" + "\n".join(lines)
            
            await ctx.followup.send(msg)

            logger.debug("role_checking command completed.")

        except Exception as e:
            logger.exception("role_checking failed")
            await ctx.followup.send(f"An error occurred while processing your request.\n{str(e)}")

    logger.debug("Registering commands: refresh_commands...")

    @bot.slash_command(
        name="refresh_commands",
        description="Refresh all slash commands globally",
        default_member_permissions=discord.Permissions(administrator=True),
        guild_ids=[1113097535796560014],
    )
    async def refresh_commands(ctx: discord.ApplicationContext):
        try:
            logger.info("refresh_commands command invoked.")
            await ctx.response.defer()
            # await bot.http.bulk_upsert_global_commands(bot.user.id, [])
            # Source - https://stackoverflow.com/a/77857548
            # Posted by Blue Robin, modified by community. See post 'Timeline' for change history
            # Retrieved 2026-02-01, License - CC BY-SA 4.0
            await bot.sync_commands()
            await ctx.followup.send("Commands refreshed globally.")
            logger.debug("refresh_commands command completed.")
        except Exception as e:
            logger.error(f"Error in refresh_commands command: {e}")
            await ctx.followup.send(f"An error occurred while processing your request.\n{str(e)}")
    
    # @bot.slash_command(
    #     name="save_csv_file_jdplus",
    #     description="Save all the jd+ members into the jdplus_users.csv file.",
    #     default_member_permissions=discord.Permissions(administrator=True),
    #     guild_ids=[1113097535796560014],
    # )
    # async def save_csv_file_jdplus(ctx: discord.ApplicationContext):
    #     try:
    #         logger.info("save_csv_file_jdplus command invoked.")
    #         await ctx.response.defer()
            
    #         async with aiofiles.open("jdplus_users.csv", mode="w", newline="") as csvfile:
    #             async with aiofiles.open(DATA_FILES, mode="r") as datafile:
    #                 data = await datafile.read().get("user_roles", {})
    #                 for user, role in data.items():
    #                     if role in 

    #         await ctx.followup.send("jdplus_users.csv file saved successfully.")
    #         logger.debug("save_csv_file_jdplus command completed.")
    #     except Exception as e:
    #         logger.error(f"Error in save_csv_file_jdplus command: {e}")
    #         await ctx.followup.send(f"An error occurred while processing your request.\n{str(e)}")

    logger.info("All commands located in commands.py registered successfully.")
    logger.info("Loading special_patches.py's commands...")
    bot.load_extension("special_patches")  # Load the commands from special_patches.py
    
<<<<<<< HEAD
    logger.info("Loading career_stats.py's commands...")
    bot.load_extension("career_stats")  # Load the commands from career_stats.py
=======
    bot.load_extension("career_stats")
>>>>>>> bb7797fb8e474f44d673c1fe3161f6e8dea9fdff

    logger.info("Commands registered successfully.")

    # Print all commands registered
    for command in bot.application_commands:
        logger.debug(f"Registered command: {command.name}")

