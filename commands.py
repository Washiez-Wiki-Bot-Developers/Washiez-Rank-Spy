import platform
import logging
import discord
import sys
import time
from datetime import datetime, timezone
import threading, asyncio
from discord.ext import commands

from trello import fetch_cards, find_cards_by_username, BOARD_NAME_MAP

# Set up logger
logger = logging.getLogger("bot.commands")
logging.basicConfig(level=logging.INFO)


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


def setup(bot: commands.Bot):
    logger.info("Loading commands extension.")

    logger.debug("Registering commands: rinse_test...")

    # Define the "rinse_test" command
    @bot.slash_command(
        name="rinse_test",
        description="Test the bot's response time.",
        #    guild_ids=[1113097535796560014]
    )
    async def rinse_test(ctx: discord.ApplicationContext):
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
        await ctx.respond("🛑 Shutting down bot...")
        logger.info("Shutdown requested.")
        try:
            await bot.close()  # Gracefully shutdown the bot
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
        if platform.system() == "Windows":
            sys.exit(0)  # Exit the process
        sys.exit(1)  # Exit the process whilst prventing auto-restart on Linux scripts

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
            await ctx.respond("🔄 Restarting bot...")
            logger.info("Restart requested.")
            await bot.close()  # Gracefully shutdown the bot
            sys.exit(0)  # Exit the process

    logger.debug("Registering commands: threads_tasks...")

    @bot.slash_command(
        name="threads_tasks",
        description="List threads and asyncio tasks",
        default_member_permissions=discord.Permissions(administrator=True),
        guild_ids=[1113097535796560014],
    )
    async def threads_tasks_cmd(ctx: discord.ApplicationContext):
        logger.info("threads_tasks command invoked.")
        await ctx.response.defer()
        info = await threads_tasks()
        out = []

        for name, ident, tasks in info:
            out.append(f"**Thread:** {name} ({ident})")
            out.extend(f"- {t}" for t in tasks or ["No tasks"])

        text = "\n".join(out)
        for i in range(0, len(text), 2000):
            await ctx.edit(text[i : i + 2000]) if i == 0 else await ctx.send_followup(
                text[i : i + 2000]
            )
        logger.debug("threads_tasks command completed.")

    logger.debug("Registering commands: semaphore_info...")

    @bot.slash_command(
        name="semaphore_info",
        description="Get semaphore information",
        default_member_permissions=discord.Permissions(administrator=True),
        guild_ids=[1113097535796560014],
    )
    async def semaphore_info_cmd(ctx: discord.ApplicationContext):
        global roblox_limiter
        logger.info("semaphore_info command invoked.")
        await ctx.response.defer()
        info = roblox_limiter.semaphore_info()
        await ctx.respond(f"Semaphore Info:\n{info}")
        logger.debug(info)
        logger.debug("semaphore_info command completed.")

    logger.debug("Registering commands: trello_check...")

    @bot.slash_command(
        name="trello_check", description="Check both WPL and WCH Trello Boards for a user"
    )
    async def trello_check(
        interaction: discord.Interaction,
        username: str,
        group_id: int = 10261023,
        required_rank: str = None,
        # guild_ids=[1113097535796560014]
    ):
        """Check both WPL and WCH Trello boards for matching cards."""
        logger.info(f"trello_check command invoked for username: {username}")
        await interaction.response.defer()

        # Define the board IDs for WPL and WCH
        board_ids = ["hcDUWrFo", "8ttvsMXg"]  # WPL and WCH boards
        results = []

        for board_id in board_ids:
            # Fetch cards from the Trello board
            cards = fetch_cards(board_id)  # Assuming fetch_cards is an async function
            # Find matching cards
            matching_cards = find_cards_by_username(cards, username, required_rank, group_id)
            results.append(
                {"board": BOARD_NAME_MAP.get(board_id, board_id), "cards": matching_cards}
            )

        # Format the result into a message
        result_message = f"Results for {username}:\n"
        for board_result in results:
            result_message += f"\n**{board_result['board']} Board:**\n"
            if not board_result["cards"]:
                result_message += "  No matching cards found.\n"
            else:
                for card in board_result["cards"]:
                    result_message += f"  - {card['name']}\n"
                    result_message += f"  - - Description & Rank History:\n {card['desc']}\n"

        # Send the result back to the user
        await interaction.followup.send(result_message)
        logger.debug("trello_check command completed.")

    logger.debug("Registering commands: refresh_commands...")

    @bot.slash_command(
        name="refresh_commands",
        description="Refresh all slash commands globally",
        default_member_permissions=discord.Permissions(administrator=True),
        guild_ids=[1113097535796560014],
    )
    async def refresh_commands(ctx: discord.ApplicationContext):
        logger.info("refresh_commands command invoked.")
        await ctx.response.defer()
        # await bot.http.bulk_upsert_global_commands(bot.user.id, [])
        # Source - https://stackoverflow.com/a/77857548
        # Posted by Blue Robin, modified by community. See post 'Timeline' for change history
        # Retrieved 2026-02-01, License - CC BY-SA 4.0
        await bot.sync_commands()
        await ctx.followup.send("Commands refreshed globally.")
        logger.debug("refresh_commands command completed.")

    logger.info("Commands registered successfully.")

    # Print all commands registered
    for command in bot.application_commands:
        logger.debug(f"Registered command: {command.name}")
