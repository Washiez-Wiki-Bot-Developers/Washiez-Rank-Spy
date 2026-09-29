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
"""
import asyncio
import time

import aiohttp
import discord


async def fetch_roblox_user(identifier):
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
            return result.get('data', [None])[0]

async def fetch_roblox_avatar(user_id):
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
                return result.get('data', [{}])[0].get('imageUrl')
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None


def format_duration(seconds):
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


def build_career_embeds(display_name, user_id, record, avatar_url=None):
    history = record['history']
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
    rank_durations = {}
    for entry, duration in durations:
        rank_durations[entry['rank']] = rank_durations.get(entry['rank'], 0) + duration

    latest_change = next(
        (entry for entry in reversed(history) if entry.get('change')),
        None
    )
    promotion_count = record.get('promotions', 0)
    demotion_count = sum(entry.get('change') == 'demotion' for entry in history)

    summary = discord.Embed(
        title='CAREER DOSSIER',
        url=f'https://www.roblox.com/users/{user_id}/profile',
        description=(
            f'**{current_entry["rank"]}**  |  Current rank\n'
            f'Career record for [Roblox member](https://www.roblox.com/users/{user_id}/profile)\n'
            f'First observed: {f"<t:{first_tracked}:D> (<t:{first_tracked}:R>)" if first_tracked else "Date unavailable"}'
        ),
        color=discord.Color.from_rgb(37, 130, 91)
    )
    summary.set_author(
        name=f'{display_name}  |  WASHIEZ',
        url=f'https://www.roblox.com/users/{user_id}/profile',
        icon_url=avatar_url
    )
    if avatar_url:
        summary.set_thumbnail(url=avatar_url)
    summary.add_field(name='PROMOTIONS', value=f'**{promotion_count}**', inline=True)
    summary.add_field(name='DEMOTIONS RECORDED', value=f'**{demotion_count}**', inline=True)
    summary.add_field(name='RANKS HELD', value=f'**{len(unique_ranks)}**', inline=True)
    summary.add_field(name='CHANGES TRACKED', value=f'**{max(0, len(history) - 1)}**', inline=True)
    summary.add_field(name='TOTAL OBSERVED TENURE', value=f'**{format_duration(total_tracked)}**', inline=True)
    summary.add_field(
        name='CURRENT RANK TENURE',
        value=f'**{format_duration(now - current_start)}**' if current_start else 'Unknown',
        inline=True
    )
    summary.add_field(
        name='LONGEST OBSERVED RANK',
        value=(f'**{longest_entry["rank"]}**\n{format_duration(longest_duration)}'
               if longest_entry else 'Not enough date data'),
        inline=True
    )

    if rank_durations and total_tracked:
        max_rank_duration = max(rank_durations.values())
        tenure_lines = []
        for rank, duration in sorted(rank_durations.items(), key=lambda item: item[1], reverse=True)[:6]:
            filled = max(1, round(duration / max_rank_duration * 10))
            bar = '\u2588' * filled + '\u2591' * (10 - filled)
            percentage = round(duration / total_tracked * 100)
            tenure_lines.append(
                f'`{bar}` **{percentage}%**  {rank}  |  {format_duration(duration)}'
            )
        summary.add_field(
            name='TIME OBSERVED BY RANK',
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
        name='LATEST CAREER MILESTONE',
        value=change_line,
        inline=False
    )
    summary.add_field(
        name='DATE PRECISION',
        value='Dates show when the bot observed a rank change, not the exact Roblox event time.',
        inline=False
    )
    summary.set_footer(
        text=f'WASHIEZ CAREER TRACKER  |  {len(history)} rank records  |  Older history may be incomplete'
    )

    embeds = [summary]
    history_pages = [history[index:index + 5] for index in range(0, len(history), 5)]
    for page_index, page in enumerate(history_pages):
        timeline = discord.Embed(
            title='CAREER TIMELINE',
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
            end_text = f'NEXT CHANGE DETECTED  <t:{end}:F>' if end else '**CURRENT RANK**  |  Still active'
            timeline.add_field(
                name=f'{index:02d}  /  {entry["rank"]}',
                value=f'{event_line}\n{start_text}\n{end_text}\nObserved tenure  **{duration_text}**',
                inline=False
            )
        timeline.set_footer(
            text=f'WASHIEZ CAREER TRACKER  |  PAGE {page_index + 1}/{len(history_pages)}  |  Dates are observation times'
        )
        embeds.append(timeline)

    return embeds


class CareerStatsView(discord.ui.View):
    def __init__(self, embeds, owner_id):
        super().__init__(timeout=180)
        self.embeds = embeds
        self.owner_id = owner_id
        self.page = 0
        self.previous_button.disabled = True
        self.overview_button.disabled = True
        self.next_button.disabled = len(embeds) <= 1

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                'Only the person who requested these stats can change pages.',
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label='Previous', style=discord.ButtonStyle.secondary)
    async def previous_button(self, button, interaction):
        self.page = max(0, self.page - 1)
        self.previous_button.disabled = self.page == 0
        self.overview_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(self.embeds) - 1
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

    @discord.ui.button(label='Overview', style=discord.ButtonStyle.secondary)
    async def overview_button(self, button, interaction):
        self.page = 0
        self.previous_button.disabled = True
        self.overview_button.disabled = True
        self.next_button.disabled = len(self.embeds) <= 1
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)

    @discord.ui.button(label='Next', style=discord.ButtonStyle.primary)
    async def next_button(self, button, interaction):
        self.page = min(len(self.embeds) - 1, self.page + 1)
        self.previous_button.disabled = self.page == 0
        self.overview_button.disabled = self.page == 0
        self.next_button.disabled = self.page == len(self.embeds) - 1
        await interaction.response.edit_message(embed=self.embeds[self.page], view=self)


def register_career_stats_command(bot, load_data):
    @bot.slash_command(
        name='careerstats',
        description='View a Roblox member career history and promotions.'
    )
    async def career_stats_command(ctx: discord.ApplicationContext, roblox_user: str):
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
        data = await load_data()
        record = data.get('career_stats', {}).get(user_id)
        if not record or not record.get('history'):
            await ctx.respond(
                f'No career history has been collected for **{user.get("name", roblox_user)}** yet.'
            )
            return

        display_name = user.get('name', user.get('username', roblox_user))
        avatar_url = await fetch_roblox_avatar(user_id)
        embeds = build_career_embeds(display_name, user_id, record, avatar_url)
        view = CareerStatsView(embeds, ctx.author.id)
        await ctx.respond(embed=embeds[0], view=view)