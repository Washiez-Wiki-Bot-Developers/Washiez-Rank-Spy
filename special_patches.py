import json
import logging_setup
import discord

logger = logging_setup.setup_logging("Special_patches")

HELL_RESTRICTIONS = {}
with open("hell_restricitions.json", "r") as f:
    HELL_RESTRICTIONS = json.load(f)

all_patches = []

class all_checks:
    def heaven_or_hell(self, user_id, rank_to, rank_from):
        """
        # Heaven or Hell
        ... (keeping your docstrings) ...
        """
        if str(user_id) in HELL_RESTRICTIONS:
            restriction = HELL_RESTRICTIONS[str(user_id)]["restriction"]
            if restriction["rank_from"] == rank_from and restriction["rank_to"] == rank_to:
                return False
        return True

def check_user(user, rank_to, rank_from, action):
    """
    # Check user
    ... (keeping your docstrings) ...
    """
    user_id = user.get("userId")

    for check_function in all_patches:
        if not check_function(user_id, rank_to, rank_from):
            print(
                f"User {user_id} is restricted from performing action '{action}' "
                f"between ranks '{rank_from}' and '{rank_to}'. Skipping."
            )
            return False

    return True

# Register the restriction check
all_patches.append(all_checks().heaven_or_hell)

# --- Logic Functions for Testing ---

async def add_heaven_or_hell(user_id: int, rank_from: str, rank_to: str, reason: str):
    """Logic for adding a user to the blacklist file."""
    with open("hell_restricitions.json", "r") as f:
        hell_restrictions = json.load(f)
    
    hell_restrictions[str(user_id)] = {
        "restricted": True,
        "reason": reason,
        "restriction": {
            "rank_from": rank_from,
            "rank_to": rank_to
        }
    }
    
    with open("hell_restricitions.json", "w") as f:
        json.dump(hell_restrictions, f, indent=4)

async def get_heaven_or_hell_list():
    """Logic for retrieving the blacklist data."""
    with open("hell_restricitions.json", "r") as f:
        return json.load(f)

# --- Commands ---

def setup(bot: discord.Bot):
    # Add or remove users
    @bot.slash_command(
        name="heaven_or_hell_add",
        description="Add user to rank-change blacklist (for Roblox API issue only), prefer rank_from > rank_to.",
        default_member_permissions=discord.Permissions(administrator=True),
        guild_ids=[1113097535796560014]
    )
    async def heaven_or_hell_add(ctx: discord.ApplicationContext, user_id: int, rank_from: str, rank_to: str, reason: str = "No reason provided."):
        try:
            logger.info("heaven_or_hell_add command invoked.")
            await ctx.response.defer()
            
            # Call the extracted logic
            await add_heaven_or_hell(user_id, rank_from, rank_to, reason)

            await ctx.followup.send(f"User {user_id} added to the rank change blacklist, reason {reason}.\n-# Use carefully—learned from Heavenaa.")
            logger.debug("heaven_or_hell_add command completed.")
        except Exception as e:
            logger.error(f"Error in heaven_or_hell_add command: {e}")
            await ctx.followup.send(f"Error: {e}")
    
    @bot.slash_command(
        name="heaven_or_hell_list",
        description="List all users in the rank change blacklist (only for Roblox API issues).",
    )
    async def heaven_or_hell_list(ctx: discord.ApplicationContext):
        try:
            logger.info("heaven_or_hell_list command invoked.")
            await ctx.response.defer()
            
            # Call the extracted logic
            hell_restrictions = await get_heaven_or_hell_list()

            if not hell_restrictions:
                await ctx.followup.send("The rank change blacklist is currently empty.")
                return

            message = "Rank Change Blacklist:\n"
            for user_id, details in hell_restrictions.items():
                reason = details.get("reason", "No reason provided.")
                restriction = details.get("restriction", {})
                rank_from = restriction.get("rank_from", "N/A")
                rank_to = restriction.get("rank_to", "N/A")
                message += f"* User ID: {user_id}, Rank From: {rank_from}, Rank To: {rank_to}, Reason: {reason}\n"

            await ctx.followup.send(message)
            logger.debug("heaven_or_hell_list command completed.")
        except Exception as e:
            logger.error(f"Error in heaven_or_hell_list command: {e}")
            await ctx.followup.send(f"An error occurred while processing your request.\n{str(e)}")