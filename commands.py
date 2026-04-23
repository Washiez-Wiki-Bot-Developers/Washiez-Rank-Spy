import platform
import logging
from aiohttp.web_urldispatcher import View
import discord
import sys
import time
from datetime import datetime, timezone, timedelta
import threading, asyncio
from discord.ext import commands

from discord import Embed, Color
from discord.ui import View, Button

import logging_setup
from app import ALL_M_RANKS_LIST

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

from utils import build_board_embed
from roblox import RobloxUser

MAX_EMBED_DESC = 1024  # Discord embed field character limit


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


def setup(bot: MyBot):
    logger.info("Loading commands extension.")

    logger.debug("Registering commands: rinse_test...")

    # Define the "rinse_test" command
    @bot.slash_command(
        name="rinse_test",
        description="Test the bot's response time.",
        #    guild_ids=[1113097535796560014]
    )
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

    # Define the "ping" command
    logger.debug("Registering commands: ping...")

    @bot.slash_command(
        name="ping", description="Check if bot is alive", guild_ids=[1113097535796560014]
    )
    async def ping(ctx: discord.ApplicationContext):
        logger.info("ping command invoked.")
        await ctx.respond("Pong!")
        logger.debug("Pong response sent.")

    # Define the "shutdown" command with admin permissions
    logger.debug("Registering commands: shutdown...")

    @bot.slash_command(
        name="shutdown",
        description="Shutdown the bot",
        guild_ids=[1113097535796560014],  # Example guild ID for testing
        default_member_permissions=discord.Permissions(administrator=True),
    )
    async def shutdown_bot(ctx: discord.ApplicationContext):
        try:
            await ctx.respond("🛑 Shutting down bot...")
            logger.info("Shutdown requested.")
            try:
                await bot.close()  # Gracefully shutdown the bot
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")
            if platform.system() == "Windows":
                sys.exit(0)  # Exit the process
            sys.exit(1)  # Exit the process whilst prventing auto-restart on Linux scripts
        except Exception as e:
            logger.error(f"Error in shutdown command: {e}")
            await ctx.followup(content="An error occurred while processing your request.")

    # Restart command for Linux
    if platform.system() == "Linux":
        logger.debug("Registering commands: restart...")

        @bot.slash_command(
            name="restart",
            description="Restart the bot",
            guild_ids=[1113097535796560014],  # Example guild ID for testing
            default_member_permissions=discord.Permissions(administrator=True),
        )
        async def restart_bot(ctx: discord.ApplicationContext):
            try:
                await ctx.respond("🔄 Restarting bot...")
                logger.info("Restart requested.")
                await bot.close()  # Gracefully shutdown the bot
                sys.exit(0)  # Exit the process
            except Exception as e:
                logger.error(f"Error in restart command: {e}")
                await ctx.followup(content="An error occurred while processing your request.")

    logger.debug("Registering commands: threads_tasks...")

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

    # logger.debug("Registering commands: semaphore_info...")
    # @bot.slash_command(
    #     name="semaphore_info",
    #     description="Get semaphore information",
    #     default_member_permissions=discord.Permissions(administrator=True),
    #     guild_ids=[1113097535796560014],
    # )
    # async def semaphore_info_cmd(ctx: discord.ApplicationContext):
    #     try:
    #         # global roblox_limiter
    #         logger.info("semaphore_info command invoked.")
    #         await ctx.response.defer()
    #         limiter = bot.Roblox_limiter
    #         info = limiter.semaphore_info()
    #         await ctx.respond(f"Semaphore Info:\n{info}")
    #         logger.debug(info)
    #         logger.debug("semaphore_info command completed.")
    #     except Exception as e:
    #         logger.error(f"Error in semaphore_info command: {e}")
    #         await ctx.followup(content="An error occurred while processing your request.")

    logger.debug("Registering commands: trello_check_embed...")

    @bot.slash_command(
        name="trello_check", description="Check both WPL and WCH Trello Boards for a user"
    )
    async def trello_check(
        interaction: discord.Interaction,
        username: str,
        group_id: int = 10261023,
        required_rank: str | None = None,
    ):
        await interaction.response.defer()
        try:
            logger.info("trello_check command invoked.")
            user = await RobloxUser.create(username)

            logger.debug("RobloxUser built")

            embeds = []

            # --- Primary user embed ---
            user_embed = Embed(
                title=user._username,
                color=10181046,
            )

            user_embed.set_author(
                name="User information: Trello",
                icon_url="https://static.wikia.nocookie.net/washiez/images/5/53/Washiez_Wiki_Bot_Developers.webp/revision/latest",
            )

            user_embed.set_thumbnail(url=await user.fetch_thumbnail("bust"))
            logger.debug("RobloxUser: Fetched Thumbnail (bust) and set as thumbnail for embed.")

            curr_rank = await user.get_rank(group_id)
            logger.debug("RobloxUser fetched current rank for group_id %d: %s", group_id, curr_rank)

            user_embed.add_field(
                name="Joined Roblox", value=await user.get_joined_roblox(), inline=False
            )
            user_embed.add_field(name="Joined Washiez", value="Unknown", inline=False)
            user_embed.add_field(name="Current Rank", value=curr_rank, inline=False)

            embeds.append(user_embed)

            # --- Board embeds ---
            board_ids = {"hcDUWrFo": (Color.orange(), "WPL"), "8ttvsMXg": (Color.green(), "WCH")}

            logger.debug("Starting to fetch and build embeds for Trello boards.")

            view = View()

            for board_id, (color, name) in board_ids.items():
                logger.debug("Fetching cards for board_id %s (%s)", board_id, name)
                cards = fetch_cards(board_id)
                logger.debug("Fetched %d cards for board_id %s (%s)", len(cards), board_id, name)
                # matches = find_cards_by_username(cards, username, required_rank, group_id)
                matches = [card for card in cards if username in card["name"].lower()]

                if not matches:
                    embeds.append(
                        Embed(description="No matching cards found.", color=color)
                        .set_author(name=f"Trello User Information: {name} Board")
                        .set_footer(
                            text="No cards found with the specified username and rank criteria. Experimental. Copyright of Data by Trello Board owner, contributors or other entities."
                        )
                    )
                    continue
                logger.debug("Fetching meta for board_id %s (%s)", board_id, name)
                icon = fetch_meta_bgimg_140(board_id)
                logger.debug(
                    "Fetched meta background image for board_id %s (%s): %s", board_id, name, icon
                )
                embeds.append(build_board_embed(username, name, matches, color, icon=icon))

                button = Button(
                    label=f"Open {name} Trello Board", url=f"https://trello.com/b/{board_id}"
                )
                view.add_item(button)

                for card in matches[:2]:
                    url = card.get("shortUrl")
                    if url:
                        view.add_item(Button(label=f"Open card on {name}", url=url))
            # Append button link (message component) to each board's card
            # Create a button linking to the Trello board

            await interaction.followup.send(embeds=embeds, view=view)
            logger.debug("trello_check command completed.")
            return True
        except Exception as e:
            logger.exception("role_checking failed")
            await interaction.followup.send(
                f"An error occurred while processing your request.\n{str(e)}"
            )
            return False

        logger.debug("Registering commands: trello_check_embed...")

    @bot.slash_command(
        name="chain_check", description="Check both WPL and WCH Trello Boards for a user"
    )
    async def chain_check(
        interaction: discord.Interaction,
        username: str,
        group_id: int = 10261023,
        required_rank: str | None = None,
    ):
        await interaction.response.defer()
        try:
            logger.info("trello_check command invoked.")
            user = await RobloxUser.create(username)

            logger.debug("RobloxUser built")

            embeds = []

            # --- Primary user embed ---
            user_embed = Embed(
                title=user._username,
                color=10181046,
            )

            user_embed.set_author(
                name="User information: Trello",
                icon_url="https://static.wikia.nocookie.net/washiez/images/5/53/Washiez_Wiki_Bot_Developers.webp/revision/latest",
            )

            user_embed.set_thumbnail(url=await user.fetch_thumbnail("bust"))
            logger.debug("RobloxUser: Fetched Thumbnail (bust) and set as thumbnail for embed.")

            curr_rank = await user.get_rank(group_id)
            logger.debug("RobloxUser fetched current rank for group_id %d: %s", group_id, curr_rank)

            user_embed.add_field(
                name="Joined Roblox", value=await user.get_joined_roblox(), inline=False
            )
            user_embed.add_field(name="Joined Washiez", value="Unknown", inline=False)
            user_embed.add_field(name="Current Rank", value=curr_rank, inline=False)

            embeds.append(user_embed)

            chain_embed = (
                Embed(description="No matching cards found.", color=color)
                .set_author(name=f"Chain User Information: {name} Board")
                .set_footer(
                    text="No cards found with the specified username and rank criteria. Experimental. Copyright of Data by Trello Board owner, contributors or other entities."
                )
            )

            # # --- Board embeds ---
            # board_ids = {"hcDUWrFo": (Color.orange(), "WPL"), "8ttvsMXg": (Color.green(), "WCH")}

            # logger.debug("Starting to fetch and build embeds for Trello boards.")

            # view = View()

            # for board_id, (color, name) in board_ids.items():
            #     logger.debug("Fetching cards for board_id %s (%s)", board_id, name)
            #     cards = fetch_cards(board_id)
            #     logger.debug("Fetched %d cards for board_id %s (%s)", len(cards), board_id, name)
            #     # matches = find_cards_by_username(cards, username, required_rank, group_id)
            #     matches = [card for card in cards if username in card["name"].lower()]

            #     if not matches:
            #         embeds.append(
            #             Embed(description="No matching cards found.", color=color)
            #             .set_author(name=f"Trello User Information: {name} Board")
            #             .set_footer(
            #                 text="No cards found with the specified username and rank criteria. Experimental. Copyright of Data by Trello Board owner, contributors or other entities."
            #             )
            #         )
            #         continue
            #     logger.debug("Fetching meta for board_id %s (%s)", board_id, name)
            #     icon = fetch_meta_bgimg_140(board_id)
            #     logger.debug(
            #         "Fetched meta background image for board_id %s (%s): %s", board_id, name, icon
            #     )
            #     embeds.append(build_board_embed(username, name, matches, color, icon=icon))

            #     button = Button(
            #         label=f"Open {name} Trello Board", url=f"https://trello.com/b/{board_id}"
            #     )
            #     view.add_item(button)

            #     for card in matches[:2]:
            #         url = card.get("shortUrl")
            #         if url:
            #             view.add_item(Button(label=f"Open card on {name}", url=url))
            # # Append button link (message component) to each board's card
            # Create a button linking to the Trello board

            await interaction.followup.send(embeds=embeds, view=view)
            logger.debug("trello_check command completed.")
            return True
        except Exception as e:
            logger.exception("role_checking failed")
            await interaction.followup.send(
                f"An error occurred while processing your request.\n{str(e)}"
            )
            return False

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

    logger.info("All commands located in commands.py registered successfully.")
    logger.info("Loading special_patches.py's commands...")
    bot.load_extension("special_patches")  # Load the commands from special_patches.py

    logger.info("Commands registered successfully.")

    # Print all commands registered
    for command in bot.application_commands:
        logger.debug(f"Registered command: {command.name}")
