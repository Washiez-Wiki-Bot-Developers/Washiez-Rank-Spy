"""
# Career_stats.py
Copyright (c) 2026 "bleuetor." & Rankspy (Washiez Variant) by Washiez Wiki: Bot Developers.
Licensed under GNU LGPL 3.0 License until further revision.

Washiez-Wiki-Bot-Developers/Washiez-Rank-Spy

:copyright: 2026 Washiez Wiki: Bot Developers (WW:BD)
:license: GNU LGPL 3.0
:original_author: "bleuetor."
:contributors: "bleuetor.", WW:BD, MrT
:repository: https://github.com/Washiez-Wiki-Bot-Developers/Washiez-Rank-Spy

THANK YOU TO BLEUETOR. FOR GIVING PERMISSION TO USE THIS CODE FOR THE WASHIEZ VARIANT OF RANKSPY.

### Descriptions
The career_stats.py module provides functionality to fetch and display career statistics for Roblox users. It includes functions to retrieve user information, avatar images, and build detailed career history embeds for Discord. The module also defines a Discord UI view for navigating through the career stats pages.

### Modifications by WW:BD
We modified the code to use internal libraries such as roblox.py and our needs.
Rank history is now read from Trello cards across multiple boards (via trello.py parsers) with local stored data.
"""

import asyncio
from collections import OrderedDict
from datetime import datetime, timezone
import logging
import os
import time

import aiohttp
discord = ...  # Type hint stub / external import
import discord

import logging_setup
from reverse import get_single_user_dict_from_announcements
import roblox
from trello import (
    BOARD_NAME_MAP,
    fetch_cards,
    parse_card,
    parse_us_numeric_date,
)

TEAM_SECTIONS = (
    "Entry Team",
    "Supervision Team",
    "Management Team",
    "Corporate Team",
)

# Optional, lowest -> highest, e.g. {'Trainee': 0, 'Staff': 1}. Empty = no demotions detected.
RANK_ORDER: dict[str, int] = {}

_record_cache: OrderedDict[
    tuple[tuple[str, ...], str], tuple[float, dict[str, any]]
] = OrderedDict()
_CACHE_MAX, _CACHE_TTL = 128, 300
ANNOUNCE_CHANNEL_ID: int = 123456789  # Replace with actual channel ID

logger = logging_setup.setup_logging(__name__)


async def fetch_roblox_user(identifier: str) -> dict[str, any] | None:
    """Fetch Roblox user details by username or numeric User ID.

    :param identifier: Roblox username or string representation of User ID.
    :returns: Dictionary containing Roblox user info, or None if not
        found/error.
    """
    async with aiohttp.ClientSession() as session:
        if identifier.isdigit():
            url = f"https://users.roblox.com/v1/users/{identifier}"
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                return await response.json()

        url = "https://users.roblox.com/v1/usernames/users"
        async with session.post(
            url, json={"usernames": [identifier], "excludeBannedUsers": True}
        ) as response:
            if response.status != 200:
                return None
            result = await response.json()
            data = result.get("data", [])
            return data[0] if data else None


async def fetch_roblox_avatar(user_id: str) -> str | None:
    """Fetch headshot thumbnail URL for a Roblox user ID.

    :param user_id: The numeric Roblox user ID.
    :returns: Direct image URL for the avatar, or None if fetch fails.
    """
    url = "https://thumbnails.roblox.com/v1/users/avatar-headshot"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params={
                    "userIds": user_id,
                    "size": "150x150",
                    "format": "Png",
                    "isCircular": "true",
                },
            ) as response:
                if response.status != 200:
                    return None
                result = await response.json()
                data = result.get("data", [{}])
                return data[0].get("imageUrl")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


def _epoch(dt: datetime | None) -> int | None:
    """Convert datetime object to integer UTC epoch timestamp.

    :param dt: Datetime object to convert.
    :returns: Integer UTC timestamp, or None if input was None.
    """
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _rank_events(parsed: dict[str, any]):
    """Yields tuples of (rank_name, datetime_object, timestamp_epoch).

    Falls back to 'Final Date Parsed' from card title if rank date is
    missing/generic.
    """
    card_fallback_dt = parsed.get("Final Date Parsed")

    for section_name, section in parsed.items():
        if not isinstance(section, dict) or section_name in (
            "Username",
            "Final Date",
            "Final Date Parsed",
        ):
            continue

        for rank, details in section.items():
            if rank == "Dept":
                continue

            date_str = None
            if isinstance(details, dict):
                date_str = details.get("date")
            elif isinstance(details, str):
                date_str = details

            dt = parse_us_numeric_date(date_str) if date_str else None

            # Fall back to card title date (e.g. 8/20/24) if rank date unavailable/unparseable
            if dt is None and card_fallback_dt:
                dt = card_fallback_dt

            yield rank, dt, _epoch(dt)


def build_record_from_announcement(data: dict[str, any]) -> dict[str, any]:
    """Transform structured announcement history data into multi-tenure career
    history.

    :param data: Dictionary containing user announcement history events.
    :returns: Dictionary containing parsed merged history entries, promotion
        count, and board info.
    """
    events = data.get("events", [])
    if not events:
        logger.warning(
            "build_record_from_announcement received empty or missing events"
            " list."
        )
        return {
            "history": [],
            "promotions": 0,
            "board_id": "",
            "board_name": "Discord Announcements",
        }

    # Sort events chronologically by timestamp 'at'
    sorted_events = sorted(events, key=lambda ev: ev.get("at", 0))
    logger.info(
        f"Parsing {len(sorted_events)} announcement events chronologically."
    )

    history = []
    promotions = 0

    # Initialize first entry using from_rank of the earliest recorded event
    first_event = sorted_events[0]
    initial_rank = first_event.get("from_rank")
    if initial_rank:
        history.append(
            {"rank": initial_rank, "start": None, "end": first_event.get("at")}
        )

    for ev in sorted_events:
        action = ev.get("action", "")
        from_rank = ev.get("from_rank")
        to_rank = ev.get("to_rank")
        start_time = ev.get("at")

        if history:
            history[-1]["end"] = start_time

        is_promo = action == "promoted"
        if is_promo:
            promotions += 1

        entry = {
            "rank": to_rank,
            "start": start_time,
            "end": None,
            "from_rank": from_rank,
            "change": "promotion" if is_promo else "demotion",
        }
        history.append(entry)

    guild_name = (
        events[0]
        .get("source", {})
        .get("guild_name", "Discord Announcements")
    )
    guild_id = events[0].get("source", {}).get("guild_id", "")

    logger.info(
        f"Successfully built announcement record with {len(history)} history"
        f" steps and {promotions} promotions."
    )
    return {
        "history": history,
        "promotions": promotions,
        "board_id": guild_id,
        "board_name": guild_name,
    }

def build_record_from_cards(cards_with_boards: List[Tuple[Dict[str, Any], str]]) -> Dict[str, Any]:
    """
    Transform raw Trello cards data across boards into structured multi-tenure career history.

    :param cards_with_boards: List of tuples (card, board_id).
    :returns: Dictionary containing parsed merged history entries, promotion count, and board info.
    """
    raw_events = []
    board_names = set()

    for card, board_id in cards_with_boards:
        parsed = parse_card(card)
        board_names.add(BOARD_NAME_MAP.get(board_id, 'Unknown Board'))
        for rank, dt, epoch in _rank_events(parsed):
            raw_events.append((rank, dt, epoch))

    # Sort events chronologically by timestamp epoch
    raw_events.sort(key=lambda event: (event[2] is None, event[2] if event[2] is not None else 0))

    # Deduplicate sequential identical rank entries
    filtered_events = []
    for rank, dt, epoch in raw_events:
        if not filtered_events or filtered_events[-1][0] != rank or filtered_events[-1][2] != epoch:
            filtered_events.append((rank, dt, epoch))

    history, promotions = [], 0
    for rank, dt, epoch in filtered_events:
        entry = {'rank': rank, 'start': epoch, 'end': None}
        if history:
            prev = history[-1]
            prev['end'] = entry['start']
            entry['from_rank'] = prev['rank']
            up = RANK_ORDER.get(rank, 1) >= RANK_ORDER.get(prev['rank'], 0)
            entry['change'] = 'promotion' if up else 'demotion'
            promotions += up
        history.append(entry)

    primary_board_name = ', '.join(sorted(board_names))
    return {
        'history': history,
        'promotions': promotions,
        'board_id': cards_with_boards[0][1] if cards_with_boards else '',
        'board_name': primary_board_name
    }

async def get_trello_record(
    username: str, board_ids: list[str] | None = None
) -> dict[str, any] | None:
    """Retrieve user career record across Trello boards mapped in
    BOARD_NAME_MAP with local caching. Merges multiple cards across boards and
    tenures.

    :param username: Roblox username to look up.
    :param board_ids: Optional list of board IDs to check (defaults to all
        boards in BOARD_NAME_MAP).
    :returns: Prepared record dict with merged history and promotion stats, or
        None if not found.
    """
    if not board_ids:
        board_ids = list(BOARD_NAME_MAP.keys())

    cache_key = (tuple(board_ids), username.lower())
    hit = _record_cache.get(cache_key)
    if hit and hit[0] > time.time():
        _record_cache.move_to_end(cache_key)
        return hit[1]

    api_key = os.getenv("TRELLO_KEY")
    token = os.getenv("TRELLO_TOKEN")
    target = username.lower()

    matching_cards: list[tuple[dict[str, any], str]] = []

    for board_id in board_ids:
        try:
            cards = await asyncio.to_thread(fetch_cards, board_id, api_key, token)
        except Exception:
            continue

        for card in cards:
            card_name_user = card["name"].split("|", 1)[0].strip().lower()
            if card_name_user == target:
                matching_cards.append((card, board_id))

    if matching_cards:
        record = build_record_from_cards(matching_cards)
        _record_cache[cache_key] = (time.time() + _CACHE_TTL, record)
        if len(_record_cache) > _CACHE_MAX:
            _record_cache.popitem(last=False)
        return record

    return None


def format_duration(seconds: float) -> str:
    """Format time duration in seconds into human readable short format (e.g.

    1y 20d 4h 5m).

    :param seconds: Time duration in seconds.
    :returns: Formatted string representing elapsed time.
    """
    total_minutes = max(0, int(seconds // 60))
    total_days, remaining_minutes = divmod(total_minutes, 1440)
    years, days = divmod(total_days, 365)
    hours, minutes = divmod(remaining_minutes, 60)
    parts = []
    if years:
        parts.append(f"{years}y")
    if days or years:
        parts.append(f"{days}d")
    if hours or days or years:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)


def build_career_embeds(
    display_name: str,
    user_id: str,
    records: list[dict[str, any]],
    avatar_url: str | None = None,
) -> list[discord.Embed]:
    """Construct Discord embeds containing career summary, statistics, and rank
    timeline pages, supporting multiple data sources (Trello and Announcements)
    with fallback logic.

    :param display_name: Member display name.
    :param user_id: Roblox numeric User ID string.
    :param records: List of prepared career record dictionaries.
    :param avatar_url: Optional Roblox avatar headshot URL.
    :returns: List of discord.Embed objects ready for pagination view.
    """
    logger.info(
        f"Building career embeds for {display_name} ({user_id}) using"
        f" {len(records)} source(s)."
    )

    # Safety check if single dict was passed
    if isinstance(records, dict):
        records = [records]

    combined_history = []
    board_names = []
    total_promotions = 0

    for idx, rec in enumerate(records):
        if not rec or not isinstance(rec, dict):
            logger.warning(f"Record at index {idx} is invalid or empty: {rec}")
            continue

        rec_history = rec.get("history", [])
        if isinstance(rec_history, list) and rec_history:
            logger.info(
                f"Loaded {len(rec_history)} history entries from:"
                f" {rec.get('board_name', 'Unknown')}"
            )
            combined_history.extend(rec_history)

        b_name = rec.get("board_name")
        if b_name and b_name not in board_names:
            board_names.append(b_name)
        total_promotions += rec.get("promotions", 0)

    # Sort combined history chronologically by start timestamp
    combined_history.sort(
        key=lambda entry: (entry.get("start") is None, entry.get("start") or 0)
    )

    history = combined_history
    board_name = " & ".join(board_names) if board_names else "WASHIEZ"

    if not history:
        logger.warning(
            f"No history records found for {display_name}. Applying fallback"
            " entry."
        )
        history = [{"rank": "Unknown", "start": None, "end": None}]

    now = int(time.time())
    current_entry = history[-1]
    current_start = current_entry.get("start")

    known_entries = [entry for entry in history if entry.get("start") is not None]

    durations = [
        (entry, max(0, (entry.get("end") or now) - entry["start"]))
        for entry in known_entries
    ]
    total_tracked = sum(duration for _, duration in durations)
    longest_entry, longest_duration = (
        max(durations, key=lambda item: item[1]) if durations else (None, 0)
    )
    first_tracked = min((entry["start"] for entry in known_entries), default=None)
    unique_ranks = list(dict.fromkeys(entry["rank"] for entry in history))
    rank_durations: dict[str, float] = {}

    for entry, duration in durations:
        rank_durations[entry["rank"]] = (
            rank_durations.get(entry["rank"], 0) + duration
        )

    latest_change = next(
        (entry for entry in reversed(history) if entry.get("change")), None
    )
    promotion_count = (
        total_promotions
        if total_promotions > 0
        else sum(entry.get("change") == "promotion" for entry in history)
    )
    demotion_count = sum(entry.get("change") == "demotion" for entry in history)

    summary = discord.Embed(
        title="Career Summary & Dossier",
        url=f"https://www.roblox.com/users/{user_id}/profile",
        description=(
            f'**{(latest_change and latest_change.get("rank")) or current_entry["rank"]}**  |  Current rank\n' #f'**{current_entry["rank"]}**  |  Current rank\n'
            "Career record for [Roblox"
            f" member](https://www.roblox.com/users/{user_id}/profile)\n"
            "First observed:"
            f' {f"<t:{first_tracked}:D> (<t:{first_tracked}:R>)" if first_tracked else "Date unavailable"}'
        ),
        color=discord.Color.from_rgb(37, 130, 91),
    )
    summary.set_author(
        name=f"{display_name}  |  {board_name}",
        url=f"https://www.roblox.com/users/{user_id}/profile",
        icon_url=avatar_url,
    )
    if avatar_url:
        summary.set_thumbnail(url=avatar_url)
    summary.add_field(name="Promotions", value=f"**{promotion_count}**", inline=True)
    summary.add_field(name="Demotions", value=f"**{demotion_count}**", inline=True)
    summary.add_field(
        name="Ranks Held", value=f"**{len(unique_ranks)}**", inline=True
    )
    summary.add_field(
        name="Changes Tracked",
        value=f"**{max(0, len(history) - 1)}**",
        inline=True,
    )
    summary.add_field(
        name="Total Observed Tenure",
        value=f"**{format_duration(total_tracked)}**",
        inline=True,
    )
    summary.add_field(
        name="Current rank tenure",
        value=(
            f"**{format_duration(now - current_start)}**"
            if current_start
            else "Unknown"
        ),
        inline=True,
    )
    summary.add_field(
        name="Longest observed rank",
        value=(
            f'**{longest_entry["rank"]}**\n{format_duration(longest_duration)}'
            if longest_entry
            else "Not enough date data"
        ),
        inline=True,
    )

    if rank_durations and total_tracked:
        max_rank_duration = max(rank_durations.values())
        tenure_lines = []
        for rank, duration in sorted(
            rank_durations.items(), key=lambda item: item[1], reverse=True
        )[:6]:
            filled = max(1, round(duration / max_rank_duration * 10))
            p_bar = "█" * filled + "░" * (10 - filled)
            percentage = round(duration / total_tracked * 100)
            tenure_lines.append(
                f"`{p_bar}` **{percentage}%**  {rank}  |"
                f"  {format_duration(duration)}"
            )
        summary.add_field(
            name="Time observed in each rank (top 6)",
            value="\n".join(tenure_lines),
            inline=False,
        )

    if latest_change:
        transition = (
            f'{latest_change.get("from_rank", "Previous rank")} ->'
            f' {latest_change["rank"]}'
        )
        change_time = latest_change.get("start")
        change_line = (
            f'Latest recorded event: **{latest_change["change"].title()}**\n{transition}'
        )
        if change_time:
            change_line += f"  |  <t:{change_time}:D>"
    else:
        change_line = (
            "No promotion or demotion details were saved in this history yet."
        )
    summary.add_field(
        name="Latest career milestone", value=change_line, inline=False
    )
    summary.add_field(
        name="Date precision",
        value=(
            "Dates show when data was obtained or observed across multiple"
            " sources (Trello and Discord Announcements), not the exact Roblox"
            " event time."
        ),
        inline=False,
    )
    summary.set_footer(
        text=(
            f"Washiez Career Tracker ({board_name})  |  {len(history)} rank"
            " records  |  Older history may be incomplete | Dates are"
            f" observation times |  Data for {display_name} from {board_name}."
            " Experimental. Copyright of Data by Trello Board owner,"
            " contributors or other entities. **/career_stats originally"
            " developed by bleuetor.** & modified for Rankspy (Washiez Variant)"
            " by Washiez Wiki: Bot Developers."
        )
    )

    embeds = [summary]
    history_pages = [
        history[index : index + 5] for index in range(0, len(history), 5)
    ]
    for page_index, page in enumerate(history_pages):
        timeline = discord.Embed(
            title="Career Timeline & Rank History",
            url=f"https://www.roblox.com/users/{user_id}/profile",
            description=(
                f'**{display_name}**  |  {current_entry["rank"]}\nChronological'
                " rank record, compiled from multiple sources."
            ),
            color=discord.Color.from_rgb(37, 130, 91),
        )
        if avatar_url:
            timeline.set_thumbnail(url=avatar_url)
        for index, entry in enumerate(page, start=page_index * 5 + 1):
            start = entry.get("start")
            end = entry.get("end")
            if start is None:
                duration_text = "Duration unavailable"
                start_text = "Already in this rank before tracking began"
            else:
                duration_text = format_duration((end or now) - start)
                start_text = f"FIRST OBSERVED  <t:{start}:F>  (<t:{start}:R>)"
            change = entry.get("change")
            from_rank = entry.get("from_rank")
            if change and from_rank:
                event_line = (
                    f'**{change.title()}**  |  {from_rank} -> {entry["rank"]}'
                )
            elif start is None:
                event_line = "**Starting rank**  |  Date predates tracking"
            else:
                event_line = "**Rank observed**  |  Event type unavailable"
            end_text = (
                f"Next change detected  <t:{end}:F>"
                if end
                else "**Current rank**  |  Still active"
            )
            timeline.add_field(
                name=f'{index:02d}  /  {entry["rank"]}',
                value=(
                    f"{event_line}\n{start_text}\n{end_text}\nObserved tenure "
                    f" **{duration_text}**"
                ),
                inline=False,
            )
        timeline.set_footer(
            text=(
                f"WASHIEZ CAREER TRACKER ({board_name})  |  PAGE"
                f" {page_index + 1}/{len(history_pages)}  |  Dates are"
                " observation times"
            )
        )
        embeds.append(timeline)

    return embeds


class CareerStatsView(discord.ui.View):
    """Pycord View handling interactive pagination controls for career
    statistics embeds.

    :param embeds: List of prepared discord.Embed objects to traverse.
    :param owner_id: Discord User ID permitted to operate the buttons.
    """

    def __init__(self, embeds: list[discord.Embed], owner_id: int):
        super().__init__(timeout=180)
        self.embeds = embeds
        self.owner_id = owner_id
        self.page = 0
        self.previous_button.disabled = True
        self.overview_button.disabled = True
        self.next_button.disabled = len(embeds) <= 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Validate that the interaction author matches the component command
        requester.

        :param interaction: Pycord interaction context.
        :returns: True if user is owner, False otherwise.
        """
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who requested these stats can change pages.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous_button(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        """Navigate to the previous embed page.

        :param button: Button component instance triggered.
        :param interaction: Pycord interaction context.
        """
        self.page = max(0, self.page - 1)
        self.previous_button.disabled = self.page == 0
        self.overview_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(self.embeds) - 1
        await interaction.response.edit_message(
            embed=self.embeds[self.page], view=self
        )

    @discord.ui.button(label="Overview", style=discord.ButtonStyle.secondary)
    async def overview_button(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        """Return to the primary summary embed page.

        :param button: Button component instance triggered.
        :param interaction: Pycord interaction context.
        """
        self.page = 0
        self.previous_button.disabled = True
        self.overview_button.disabled = True
        self.next_button.disabled = len(self.embeds) <= 1
        await interaction.response.edit_message(
            embed=self.embeds[self.page], view=self
        )

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next_button(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        """Navigate to the next embed page.

        :param button: Button component instance triggered.
        :param interaction: Pycord interaction context.
        """
        self.page = min(len(self.embeds) - 1, self.page + 1)
        self.previous_button.disabled = self.page == 0
        self.overview_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(self.embeds) - 1
        await interaction.response.edit_message(
            embed=self.embeds[self.page], view=self
        )


def register_career_stats_command(bot: discord.Bot, load_data=None):
    """Register the /careerstats slash command onto the provided Pycord bot
    instance.

    :param bot: Active discord.Bot or discord.Cog instance.
    :param load_data: Optional legacy parameter for backward compatibility.
    """

    @bot.slash_command(
        name="careerstats",
        description="View a Roblox member career history and promotions.",
    )
    async def career_stats_command(
        ctx: discord.ApplicationContext, roblox_user: str
    ):
        """Command execution callback for displaying career statistics.

        :param ctx: Application Context for the slash command invocation.
        :param roblox_user: Target Roblox username or numeric user ID string.
        """
        await ctx.defer()
        logger.info(
            f"Command /careerstats invoked by {ctx.author} for target:"
            f" {roblox_user}"
        )

        try:
            user = await fetch_roblox_user(roblox_user)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(
                f"Network error fetching Roblox user {roblox_user}: {e}"
            )
            await ctx.respond(
                "Could not reach Roblox right now. Please try again later."
            )
            return

        if not user:
            logger.warning(f"Roblox user not found: {roblox_user}")
            await ctx.respond(
                "Roblox user not found. Provide a Roblox username or user ID."
            )
            return

        user_id = str(user["id"])
        user_name = user.get("username", roblox_user)
        display_name = user.get("name", user.get("username", roblox_user))

        records = []
        trello_record = None
        announce_record = None

        # 1. Try fetching from Trello
        try:
            trello_record = await get_trello_record(user_name)
            if trello_record and trello_record.get("history"):
                logger.info(
                    f"Successfully retrieved Trello record for {display_name}."
                )
        except Exception as e:
            logger.error(
                f"Error fetching Trello record for {display_name}: {e}"
            )

        # 2. Try fetching from Announcements
        try:
            logger.info(
                "Fetching announcement history for user ID"
                f" {user_id} in guild {ctx.guild.id}"
            )
            announce_data = await get_single_user_dict_from_announcements(
                bot,
                int(user_id),
                ctx.guild.id,
                1276397232341520469,
                channel_id=ANNOUNCE_CHANNEL_ID,
                limit=1000,
            )
            if announce_data and isinstance(announce_data, dict):
                announce_record = build_record_from_announcement(announce_data)
                if announce_record and announce_record.get("history"):
                    logger.info(
                        "Successfully retrieved and parsed announcement record"
                        f" for {display_name}."
                    )
        except Exception as e:
            logger.error(
                f"Error fetching announcement record for {display_name}: {e}"
            )

        if trello_record:
            records.append(trello_record)
        if announce_record:
            records.append(announce_record)

        if not records or not any(r.get("history") for r in records):
            logger.warning(
                "No career history collected across any sources for"
                f" {display_name} ({user_id})."
            )
            await ctx.respond(
                "No career history has been collected for"
                f" **{display_name}** yet."
            )
            return

        avatar_url = await fetch_roblox_avatar(user_id)
        embeds = build_career_embeds(display_name, user_id, records, avatar_url)
        view = CareerStatsView(embeds, ctx.author.id)
        await ctx.respond(embed=embeds[0], view=view)


def setup(bot: discord.Bot):
    """Load the careerstats extension into the bot.

    :param bot: Active discord.Bot instance.
    """
    register_career_stats_command(bot)
    logger.info("CareerStats extension loaded successfully.")