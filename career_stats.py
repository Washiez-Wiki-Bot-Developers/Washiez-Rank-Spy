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
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import logging

import aiohttp
import discord

import roblox
from trello import BOARD_NAME_MAP, fetch_cards, parse_card, parse_us_numeric_date

TEAM_SECTIONS = ('Entry Team', 'Supervision Team', 'Management Team', 'Corporate Team')

# Optional, lowest -> highest, e.g. {'Trainee': 0, 'Staff': 1}. Empty = no demotions detected.
RANK_ORDER: Dict[str, int] = {}

_record_cache: OrderedDict[Tuple[Tuple[str, ...], str], Tuple[float, Dict[str, Any]]] = OrderedDict()
_CACHE_MAX, _CACHE_TTL = 128, 300

logger = logging.getLogger(__name__)

async def fetch_roblox_user(identifier: str) -> Optional[Dict[str, Any]]:
    """
    Fetch Roblox user details by username or numeric User ID.

    :param identifier: Roblox username or string representation of User ID.
    :returns: Dictionary containing Roblox user info, or None if not found/error.
    """
    async with aiohttp.ClientSession() as session:
        if identifier.isdigit():
            url = f'https://users.roblox.com/v1/users/{identifier}'
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                return await response.json()

        url = 'https://users.roblox.com/v1/usernames/users'
        async with session.post(
            url,
            json={'usernames': [identifier], 'excludeBannedUsers': True}
        ) as response:
            if response.status != 200:
                return None
            result = await response.json()
            data = result.get('data', [])
            return data[0] if data else None


async def fetch_roblox_avatar(user_id: str) -> Optional[str]:
    """
    Fetch headshot thumbnail URL for a Roblox user ID.

    :param user_id: The numeric Roblox user ID.
    :returns: Direct image URL for the avatar, or None if fetch fails.
    """
    url = 'https://thumbnails.roblox.com/v1/users/avatar-headshot'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                params={
                    'userIds': user_id,
                    'size': '150x150',
                    'format': 'Png',
                    'isCircular': 'true'
                }
            ) as response:
                if response.status != 200:
                    return None
                result = await response.json()
                data = result.get('data', [{}])
                return data[0].get('imageUrl')
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


def _epoch(dt: Optional[datetime]) -> Optional[int]:
    """
    Convert datetime object to integer UTC epoch timestamp.

    :param dt: Datetime object to convert.
    :returns: Integer UTC timestamp, or None if input was None.
    """
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _rank_events(parsed: Dict[str, Any]):
    """
    Yields tuples of (rank_name, datetime_object, timestamp_epoch).
    Falls back to 'Final Date Parsed' from card title if rank date is missing/generic.
    """
    card_fallback_dt = parsed.get("Final Date Parsed")

    for section_name, section in parsed.items():
        if not isinstance(section, dict) or section_name in ("Username", "Final Date", "Final Date Parsed"):
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
    username: str,
    board_ids: Optional[List[str]] = None
) -> Optional[Dict[str, Any]]:
    """
    Retrieve user career record across Trello boards mapped in BOARD_NAME_MAP with local caching.
    Merges multiple cards across boards and tenures.

    :param username: Roblox username to look up.
    :param board_ids: Optional list of board IDs to check (defaults to all boards in BOARD_NAME_MAP).
    :returns: Prepared record dict with merged history and promotion stats, or None if not found.
    """
    if not board_ids:
        board_ids = list(BOARD_NAME_MAP.keys())

    cache_key = (tuple(board_ids), username.lower())
    hit = _record_cache.get(cache_key)
    if hit and hit[0] > time.time():
        _record_cache.move_to_end(cache_key)
        return hit[1]

    api_key = os.getenv('TRELLO_KEY')
    token = os.getenv('TRELLO_TOKEN')
    target = username.lower()

    matching_cards: List[Tuple[Dict[str, Any], str]] = []

    for board_id in board_ids:
        try:
            cards = await asyncio.to_thread(fetch_cards, board_id, api_key, token)
        except Exception:
            continue

        for card in cards:
            card_name_user = card['name'].split('|', 1)[0].strip().lower()
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
    """
    Format time duration in seconds into human readable short format (e.g. 1y 20d 4h 5m).

    :param seconds: Time duration in seconds.
    :returns: Formatted string representing elapsed time.
    """
    total_minutes = max(0, int(seconds // 60))
    total_days, remaining_minutes = divmod(total_minutes, 1440)
    years, days = divmod(total_days, 365)
    hours, minutes = divmod(remaining_minutes, 60)
    parts = []
    if years:
        parts.append(f'{years}y')
    if days or years:
        parts.append(f'{days}d')
    if hours or days or years:
        parts.append(f'{hours}h')
    if minutes or not parts:
        parts.append(f'{minutes}m')
    return ' '.join(parts)


def build_career_embeds(
    display_name: str,
    user_id: str,
    record: Dict[str, Any],
    avatar_url: Optional[str] = None
) -> List[discord.Embed]:
    """
    Construct Discord embeds containing career summary, statistics, and rank timeline pages.

    :param display_name: Member display name.
    :param user_id: Roblox numeric User ID string.
    :param record: Prepared Trello record dictionary.
    :param avatar_url: Optional Roblox avatar headshot URL.
    :returns: List of discord.Embed objects ready for pagination view.
    """
    history = record['history']
    board_name = record.get('board_name', 'WASHIEZ')
    now = int(time.time())
    
    current_entry = history[-1]
    current_start = current_entry.get('start')
    
    known_entries = [entry for entry in history if entry.get('start') is not None]
    
    durations = [
        (entry, max(0, (entry.get('end') or now) - entry['start']))
        for entry in known_entries
    ]
    total_tracked = sum(duration for _, duration in durations)
    longest_entry, longest_duration = max(durations, key=lambda item: item[1]) if durations else (None, 0)
    first_tracked = min((entry['start'] for entry in known_entries), default=None)
    unique_ranks = list(dict.fromkeys(entry['rank'] for entry in history))
    rank_durations: Dict[str, float] = {}
    
    for entry, duration in durations:
        rank_durations[entry['rank']] = rank_durations.get(entry['rank'], 0) + duration

    latest_change = next(
        (entry for entry in reversed(history) if entry.get('change')),
        None
    )
    promotion_count = record.get('promotions', 0)
    demotion_count = sum(entry.get('change') == 'demotion' for entry in history)

    summary = discord.Embed(
        title='Career Summary & Dossier',
        url=f'https://www.roblox.com/users/{user_id}/profile',
        description=(
            f'**{current_entry["rank"]}**  |  Current rank\n'
            f'Career record for [Roblox member](https://www.roblox.com/users/{user_id}/profile)\n'
            f'First observed: {f"<t:{first_tracked}:D> (<t:{first_tracked}:R>)" if first_tracked else "Date unavailable"}'
        ),
        color=discord.Color.from_rgb(37, 130, 91)
    )
    summary.set_author(
        name=f'{display_name}  |  {board_name}',
        url=f'https://www.roblox.com/users/{user_id}/profile',
        icon_url=avatar_url
    )
    if avatar_url:
        summary.set_thumbnail(url=avatar_url)
    summary.add_field(name='Promotions', value=f'**{promotion_count}**', inline=True)
    summary.add_field(name='Demotions', value=f'**{demotion_count}**', inline=True)
    summary.add_field(name='Ranks Held', value=f'**{len(unique_ranks)}**', inline=True)
    summary.add_field(name='Changes Tracked', value=f'**{max(0, len(history) - 1)}**', inline=True)
    summary.add_field(name='Total Observed Tenure', value=f'**{format_duration(total_tracked)}**', inline=True)
    summary.add_field(
        name='Current rank tenure',
        value=f'**{format_duration(now - current_start)}**' if current_start else 'Unknown',
        inline=True
    )
    summary.add_field(
        name='Longest observed rank',
        value=(f'**{longest_entry["rank"]}**\n{format_duration(longest_duration)}'
               if longest_entry else 'Not enough date data'),
        inline=True
    )

    if rank_durations and total_tracked:
        max_rank_duration = max(rank_durations.values())
        tenure_lines = []
        for rank, duration in sorted(rank_durations.items(), key=lambda item: item[1], reverse=True)[:6]:
            filled = max(1, round(duration / max_rank_duration * 10))
            p_bar = '█' * filled + '░' * (10 - filled)
            percentage = round(duration / total_tracked * 100)
            tenure_lines.append(
                f'`{p_bar}` **{percentage}%**  {rank}  |  {format_duration(duration)}'
            )
        summary.add_field(
            name='Time observed in each rank (top 6)',
            value='\n'.join(tenure_lines),
            inline=False
        )

    if latest_change:
        transition = f'{latest_change.get("from_rank", "Previous rank")} -> {latest_change["rank"]}'
        change_time = latest_change.get('start')
        change_line = f'Latest recorded event: **{latest_change["change"].title()}**\n{transition}'
        if change_time:
            change_line += f'  |  <t:{change_time}:D>'
    else:
        change_line = 'No promotion or demotion details were saved in this history yet.'
    summary.add_field(
        name='Latest career milestone',
        value=change_line,
        inline=False
    )
    summary.add_field(
        name='Date precision',
        value='Dates show when ~~the bot observed a rank change, and/or~~ date obtained that is most accurate with public data by Trello board contributors, not the exact Roblox event time.',
        inline=False
    )
    summary.set_footer(
        text=f'Washiez Career Tracker ({board_name})  |  {len(history)} rank records  |  Older history may be incomplete | Dates are observation times |  Data for {display_name} from {board_name}. Experimental. Copyright of Data by Trello Board owner, contributors or other entities. **/career_stats originally developed by bleuetor.** & modified for Rankspy (Washiez Variant) by Washiez Wiki: Bot Developers.'
    )

    embeds = [summary]
    history_pages = [history[index:index + 5] for index in range(0, len(history), 5)]
    for page_index, page in enumerate(history_pages):
        timeline = discord.Embed(
            title='Career Timeline & Rank History',
            url=f'https://www.roblox.com/users/{user_id}/profile',
            description=f'**{display_name}**  |  {current_entry["rank"]}\nChronological rank record, based on bot observations.',
            color=discord.Color.from_rgb(37, 130, 91)
        )
        if avatar_url:
            timeline.set_thumbnail(url=avatar_url)
        for index, entry in enumerate(page, start=page_index * 5 + 1):
            start = entry.get('start')
            end = entry.get('end')
            if start is None:
                duration_text = 'Duration unavailable'
                start_text = 'Already in this rank before tracking began'
            else:
                duration_text = format_duration((end or now) - start)
                start_text = f'FIRST OBSERVED  <t:{start}:F>  (<t:{start}:R>)'
            change = entry.get('change')
            from_rank = entry.get('from_rank')
            if change and from_rank:
                event_line = f'**{change.title()}**  |  {from_rank} -> {entry["rank"]}'
            elif start is None:
                event_line = '**Starting rank**  |  Date predates tracking'
            else:
                event_line = '**Rank observed**  |  Event type unavailable'
            end_text = f'Next change detected  <t:{end}:F>' if end else '**Current rank**  |  Still active'
            timeline.add_field(
                name=f'{index:02d}  /  {entry["rank"]}',
                value=f'{event_line}\n{start_text}\n{end_text}\nObserved tenure  **{duration_text}**',
                inline=False
            )
        timeline.set_footer(
            text=f'WASHIEZ CAREER TRACKER ({board_name})  |  PAGE {page_index + 1}/{len(history_pages)}  |  Dates are observation times'
        )
        embeds.append(timeline)

    return embeds


class CareerStatsView(discord.ui.View):
    """
    Pycord View handling interactive pagination controls for career statistics embeds.

    :param embeds: List of prepared discord.Embed objects to traverse.
    :param owner_id: Discord User ID permitted to operate the buttons.
    """
    def __init__(self, embeds: List[discord.Embed], owner_id: int):
        super().__init__(timeout=180)
        self.embeds = embeds
        self.owner_id = owner_id
        self.page = 0
        self.previous_button.disabled = True
        self.overview_button.disabled = True
        self.next_button.disabled = len(embeds) <= 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """
        Validate that the interaction author matches the component command requester.

        :param interaction: Pycord interaction context.
        :returns: True if user is owner, False otherwise.
        """
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                'Only the person who requested these stats can change pages.',
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.secondary)
    async def previous_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """
        Navigate to the previous embed page.

        :param button: Button component instance triggered.
        :param interaction: Pycord interaction context.
        """
        self.page = max(0, self.page - 1)
        self.previous_button.disabled = self.page == 0
        self.overview_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(self.embeds) - 1
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

    @discord.ui.button(label='Overview', style=discord.ButtonStyle.secondary)
    async def overview_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """
        Return to the primary summary embed page.

        :param button: Button component instance triggered.
        :param interaction: Pycord interaction context.
        """
        self.page = 0
        self.previous_button.disabled = True
        self.overview_button.disabled = True
        self.next_button.disabled = len(self.embeds) <= 1
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

    @discord.ui.button(label='Next', style=discord.ButtonStyle.primary)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """
        Navigate to the next embed page.

        :param button: Button component instance triggered.
        :param interaction: Pycord interaction context.
        """
        self.page = min(len(self.embeds) - 1, self.page + 1)
        self.previous_button.disabled = self.page == 0
        self.overview_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(self.embeds) - 1
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)


def register_career_stats_command(bot: discord.Bot, load_data=None):
    """
    Register the /careerstats slash command onto the provided Pycord bot instance.

    :param bot: Active discord.Bot or discord.Cog instance.
    :param load_data: Optional legacy parameter for backward compatibility.
    """
    @bot.slash_command(
        name='careerstats',
        description='View a Roblox member career history and promotions.'
    )
    async def career_stats_command(ctx: discord.ApplicationContext, roblox_user: str):
        """
        Command execution callback for displaying career statistics.

        :param ctx: Application Context for the slash command invocation.
        :param roblox_user: Target Roblox username or numeric user ID string.
        """
        await ctx.defer()
        try:
            user = await fetch_roblox_user(roblox_user)
        except (aiohttp.ClientError, asyncio.TimeoutError):
            await ctx.respond('Could not reach Roblox right now. Please try again later.')
            return

        if not user:
            await ctx.respond('Roblox user not found. Provide a Roblox username or user ID.')
            return

        user_id = str(user['id'])
        display_name = user.get('name', user.get('username', roblox_user))
        try:
            record = await get_trello_record(display_name)
        except Exception as e:
            await ctx.respond(f'Could not reach Trello right now. Please try again later. Error: {e}')
            logger.error(f'Error fetching Trello record for {display_name}: {e}')
            return

        if not record or not record.get('history'):
            await ctx.respond(
                f'No career history has been collected for **{display_name}** yet.'
            )
            return

        avatar_url = await fetch_roblox_avatar(user_id)
        embeds = build_career_embeds(display_name, user_id, record, avatar_url)
        view = CareerStatsView(embeds, ctx.author.id)
        await ctx.respond(embed=embeds[0], view=view)

def setup(bot: discord.Bot):
    """
    Setup function to register the career stats command with the bot.

    :param bot: Active discord.Bot instance.
    """
    register_career_stats_command(bot)