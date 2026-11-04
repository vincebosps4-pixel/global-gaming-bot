"""Persistent tickets, giveaways and boost acknowledgements for one community."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import tasks

from storage import Store

LOG = logging.getLogger('lounge')
BLUE, PINK = 0x00BFFF, 0xFF2D95
NO_MENTIONS = discord.AllowedMentions.none()
PANEL_ID = 1567624646944235632
GIVEAWAY_ID = 1567624640912822423
BOOST_ID = 1567624635183530118
SUPPORT_NAME = '🛡️ Support Team'

# Explicit IDs prevent renaming another server or a channel with a similar name.
CHANNEL_STYLE = {
    1567600695744667728: '👋・welcome', 1567600702174535760: '📜・rules',
    1567600708012744704: '📣・announcements', 1567599948680401102: '💬・general',
    1567600218910761040: '🌐・international-chat', 1567600290235031613: '😂・memes-and-clips',
    1567600312477552823: '✨・introductions', 1567624652367335475: '📸・media',
    1567600414130569216: '💬・chat', 1567600440932303048: '🔎・looking-for-group',
    1567600509790191759: '💬・chat', 1567600514961510533: '🔎・builds-and-lfg',
    1567600562604744714: '💬・chat', 1567600567444971650: '🔎・looking-for-team',
    1567600615750770819: '💬・chat', 1567600625024372827: '🔎・games-and-lfg',
    1567622680448860395: '💬・chat', 1567622687826780321: '🔎・looking-for-group',
    1567622888507310151: '💬・chat', 1567623771865747708: '📰・news',
    BOOST_ID: '💎・server-boosts', GIVEAWAY_ID: '🎉・giveaways', PANEL_ID: '🎫・open-ticket',
}
VOICE_STYLE = {
    'General': '🔊・General', 'Chill Room': '🌙・Chill Room', 'Stream Lounge': '📺・Stream Lounge',
    'Fortnite Duos': '🔊・Duos', 'Fortnite Squads': '🔊・Squads',
    'Minecraft Survival': '🔊・Survival', 'Minecraft Creative': '🔊・Creative',
    'Rocket League Duos': '🔊・Duos', 'Rocket League Trios': '🔊・Trios',
    'Roblox Party 1': '🔊・Party 1', 'Roblox Party 2': '🔊・Party 2',
    'COD Squad': '🔊・Squad', 'COD Warzone': '🔊・Warzone', 'GTA VI Lounge': '🔊・Lounge',
    'Lounge': '🔊・Lounge',
}


def safe_text(text: str) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(text.strip()))


def ticket_overwrites(guild, staff, bot_member, owner=None, *, closed=False):
    result = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        staff: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                           embed_links=True),
        bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                                embed_links=True),
    }
    if owner is not None:
        result[owner] = discord.PermissionOverwrite(
            view_channel=True, send_messages=not closed, read_message_history=True,
            attach_files=not closed, embed_links=not closed,
            create_public_threads=False, create_private_threads=False, create_instant_invite=False,
            send_messages_in_threads=False, mention_everyone=False,
        )
    return result


def giveaway_embed(row, count: int) -> discord.Embed:
    ended = row['state'] in ('ended','cancelled')
    title = '🎉 Giveaway' if not ended else ('🏆 Giveaway results' if row['state']=='ended' else '🎟️ Giveaway cancelled')
    embed = discord.Embed(title=title, description='**'+safe_text(row['prize'])+'**', colour=PINK if ended else BLUE)
    embed.add_field(name='Closes', value=f"<t:{row['ends']}:F> · <t:{row['ends']}:R>", inline=False)
    embed.add_field(name='Winners', value=str(row['winners_count']))
    embed.add_field(name='Entries', value=str(count))
    embed.add_field(name='How to enter', value='Use **Enter / leave** below. One entry per member. No payment or boost required. Click again to leave.', inline=False)
    embed.add_field(name='Rules', value=safe_text(row['rules']), inline=False)
    if row['state']=='ended':
        winners = json.loads(row['winners'])
        embed.add_field(name='Selected winners', value=', '.join(f'<@{uid}>' for uid in winners) if winners else 'No entries were received.', inline=False)
        embed.add_field(name='Claim your prize', value='Contact the server owner through a ticket. Never share passwords or login codes, and never pay a claim fee.', inline=False)
    elif row['state']=='cancelled':
        embed.add_field(name='Status', value='Cancelled by a server manager. No winners were drawn.', inline=False)
    embed.set_footer(text=f"Global Gaming Lounge • giveaway:{row['id']}")
    return embed


class SafeView(discord.ui.View):
    async def on_error(self, interaction, error, item):
        LOG.warning('Interaction could not finish: %s', type(error).__name__)
        text = 'This action could not finish. Please try again or contact the server owner.'
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)


class TicketModal(discord.ui.Modal, title='Contact the support team'):
    subject = discord.ui.TextInput(label='What do you need help with?', min_length=3, max_length=100)
    details = discord.ui.TextInput(label='Details (never include passwords or codes)', style=discord.TextStyle.paragraph, min_length=5, max_length=1800)

    def __init__(self, features):
        super().__init__()
        self.features = features

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            channel = await self.features.open_ticket(interaction, str(self.subject), str(self.details))
            await interaction.followup.send(f'Your private ticket: {channel.mention}', ephemeral=True)
        except (ValueError, discord.HTTPException) as exc:
            msg = str(exc) if isinstance(exc,ValueError) else 'Ticket creation could not be confirmed. Please try again; existing tickets will be reused.'
            await interaction.followup.send(msg, ephemeral=True)


class TicketPanel(SafeView):
    def __init__(self, features):
        super().__init__(timeout=None)
        self.features = features

    @discord.ui.button(label='Open a ticket', emoji='🎫', style=discord.ButtonStyle.primary, custom_id='gg:ticket:open:v1')
    async def open(self, interaction, button):
        if interaction.guild_id != self.features.guild_id or interaction.channel_id != PANEL_ID:
            await interaction.response.send_message('Use the ticket panel in Global Gaming.', ephemeral=True)
            return
        await interaction.response.send_modal(TicketModal(self.features))


class TicketControls(SafeView):
    def __init__(self, features):
        super().__init__(timeout=None)
        self.features = features

    @discord.ui.button(label='Close ticket', emoji='🔒', style=discord.ButtonStyle.secondary, custom_id='gg:ticket:close:v1')
    async def close_ticket(self, interaction, button):
        await self.features.change_ticket(interaction, closed=True)

    @discord.ui.button(label='Reopen ticket', emoji='🔓', style=discord.ButtonStyle.secondary, custom_id='gg:ticket:reopen:v1')
    async def reopen_ticket(self, interaction, button):
        await self.features.change_ticket(interaction, closed=False)


class GiveawayEntry(SafeView):
    def __init__(self, features, *, disabled=False):
        super().__init__(timeout=None)
        self.features = features
        self.enter.disabled = disabled

    @discord.ui.button(label='Enter / leave', emoji='🎉', style=discord.ButtonStyle.primary, custom_id='gg:giveaway:entry:v1')
    async def enter(self, interaction, button):
        f = self.features
        if interaction.guild_id != f.guild_id or interaction.channel_id != GIVEAWAY_ID or interaction.user.bot:
            await interaction.response.send_message('This giveaway is for Global Gaming members.', ephemeral=True)
            return
        row = f.store.giveaway_for_message(interaction.message.id)
        if row is None:
            await interaction.response.send_message('This giveaway is not accepting entries.', ephemeral=True)
            return
        status = f.store.toggle_entry(row['id'], interaction.user.id)
        await interaction.response.send_message({'entered':'You are entered! Click again if you want to leave.', 'left':'You have left the giveaway.', 'closed':'Entries are closed.'}[status], ephemeral=True)
        # Refresh counts in the periodic worker; avoid a message edit per click.
        f.dirty_giveaways.add(row['id'])


class GiveawayPreview(SafeView):
    def __init__(self, features, owner, prize, minutes, winners, rules):
        super().__init__(timeout=300)
        self.features, self.owner = features, owner
        self.prize, self.minutes, self.winners, self.rules = prize, minutes, winners, rules
        self.used = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner or not self.features.is_manager(interaction):
            await interaction.response.send_message('Only the author with Manage Server permission may publish this giveaway.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='Publish giveaway', style=discord.ButtonStyle.success)
    async def publish(self, interaction, button):
        if self.used:
            await interaction.response.send_message('This preview has already been handled.', ephemeral=True)
            return
        self.used = True
        await interaction.response.defer(ephemeral=True)
        f = self.features
        gid = f.store.create_giveaway(GIVEAWAY_ID, self.owner, self.prize, self.rules, self.winners, int(time.time())+self.minutes*60)
        try:
            await f.recover_giveaway(f.store.giveaway(gid))
            row = f.store.giveaway(gid)
            await interaction.edit_original_response(content=f"Published: https://discord.com/channels/{f.guild_id}/{GIVEAWAY_ID}/{row['message']}",embed=None,view=None)
        except discord.HTTPException:
            await interaction.edit_original_response(content='Publishing is queued. The bot will retry automatically; check the giveaway channel before creating another.',embed=None,view=None)
        self.stop()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        self.used = True
        await interaction.response.edit_message(content='Cancelled. Nothing was posted.',embed=None,view=None)
        self.stop()


class CancelGiveaway(SafeView):
    def __init__(self, features, owner, giveaway):
        super().__init__(timeout=120)
        self.features, self.owner, self.giveaway = features, owner, giveaway

    @discord.ui.button(label='Confirm cancellation',style=discord.ButtonStyle.danger)
    async def cancel(self, interaction, button):
        if interaction.user.id != self.owner or not self.features.is_manager(interaction):
            await interaction.response.send_message('Only the requesting server manager may confirm.',ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        row = self.features.store.finish(self.giveaway,cancel=True)
        await self.features.refresh_giveaway(row)
        await interaction.edit_original_response(content='Giveaway closed. Its message and entry records were kept.',view=None)
        self.stop()


class CommunityFeatures:
    def __init__(self, bot, guild_id, data_dir):
        self.bot, self.guild_id = bot, guild_id
        self.data_dir = Path(data_dir)
        self.store = Store(self.data_dir / 'community.sqlite3')
        self.ticket_lock = asyncio.Lock()
        self.giveaway_lock = asyncio.Lock()
        self.dirty_giveaways = set()

    def is_manager(self, interaction):
        return interaction.guild_id == self.guild_id and interaction.permissions.manage_guild

    def staff_role(self, guild):
        configured = os.getenv('SUPPORT_ROLE_ID','').strip()
        roles = [r for r in guild.roles if str(r.id)==configured] if configured else [r for r in guild.roles if r.name==SUPPORT_NAME]
        if len(roles)!=1 or roles[0].is_default() or roles[0].managed:
            raise ValueError('The support role is missing or ambiguous. Ask the owner to configure SUPPORT_ROLE_ID.')
        return roles[0]

    async def channel(self, channel_id):
        ch = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        if not isinstance(ch,discord.TextChannel) or ch.guild.id!=self.guild_id:
            raise ValueError('The configured channel is not in Global Gaming.')
        return ch

    def register(self):
        self.bot.add_view(TicketPanel(self))
        self.bot.add_view(TicketControls(self))
        self.bot.add_view(GiveawayEntry(self))
        guild = discord.Object(id=self.guild_id)

        @self.bot.tree.command(name='setup_community',description='Set up the ticket panel and community channel style.',guild=guild)
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.check(self.is_manager)
        async def setup(interaction):
            await interaction.response.defer(ephemeral=True)
            await self.setup()
            await interaction.followup.send('Channel style and private ticket panel are ready.',ephemeral=True)

        @self.bot.tree.command(name='giveaway',description='Preview a free community giveaway before publishing it.',guild=guild)
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.check(self.is_manager)
        @app_commands.describe(prize='The real prize you will supply',minutes='Duration in minutes (1 minute to 30 days)',winners='Number of winners',rules='Eligibility and claim rules. Entry must be free.')
        async def giveaway(interaction: discord.Interaction, prize: app_commands.Range[str,1,200], minutes: app_commands.Range[int,1,43200], winners: app_commands.Range[int,1,10]=1, rules: app_commands.Range[str,1,900]='Open to server members. One entry each. No payment or boost required. Winners contact the owner through a ticket.'):
            row = dict(id=0,prize=prize,rules=rules,winners_count=winners,ends=int(time.time())+minutes*60,state='open')
            await interaction.response.send_message('Private preview. Publish only when the prize and rules are confirmed. The timer starts when you publish.',embed=giveaway_embed(row,0),view=GiveawayPreview(self,interaction.user.id,prize,minutes,winners,rules),ephemeral=True)

        @self.bot.tree.command(name='giveaway_cancel',description='Cancel an active giveaway after confirmation; keep its message.',guild=guild)
        @app_commands.guild_only()
        @app_commands.default_permissions(manage_guild=True)
        @app_commands.check(self.is_manager)
        async def giveaway_cancel(interaction:discord.Interaction, message_id:str):
            row = self.store.giveaway_for_message(int(message_id)) if message_id.isdigit() else None
            if not row or row['state']!='open':
                await interaction.response.send_message('No active giveaway found for that message ID.',ephemeral=True)
                return
            await interaction.response.send_message('Cancel **'+safe_text(row['prize'])+'**? No winners will be drawn. Its message and entry records remain.',view=CancelGiveaway(self,interaction.user.id,row['id']),ephemeral=True)

        @self.bot.tree.command(name='community_help',description='Find tickets, role choices and community features.',guild=guild)
        @app_commands.guild_only()
        async def help_command(interaction):
            embed = discord.Embed(title='🌍 Global Gaming help',colour=BLUE,description=f'**Tickets:** <#{PANEL_ID}>\n**Giveaways:** <#{GIVEAWAY_ID}>\n**Boosts:** <#{BOOST_ID}>\n**Roles:** Open Channels & Roles; every question is optional.')
            if self.is_manager(interaction):
                embed.add_field(name='Staff commands',value='`/announce` · `/giveaway` · `/giveaway_cancel` · `/setup_embeds` · `/setup_community` · `/bot_status`',inline=False)
            await interaction.response.send_message(embed=embed,ephemeral=True)

    async def setup(self):
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            raise ValueError('Global Gaming is unavailable.')
        me = guild.me
        if not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
            raise ValueError('Manage Channels and Manage Roles are required for private ticket channels; Administrator is not required.')
        if not self.store.get('channel_style_v1'):
            for cid,name in CHANNEL_STYLE.items():
                ch = await self.channel(cid)
                if ch.name != name:
                    await ch.edit(name=name,reason='Owner requested emoji channel names without repeated game titles')
            for ch in guild.voice_channels:
                if ch.name in VOICE_STYLE:
                    await ch.edit(name=VOICE_STYLE[ch.name],reason='Owner requested matching voice channel names')
            self.store.put('channel_style_v1','done')
        # Staff-only news; retain existing bot and owner access.
        news = await self.channel(1567623771865747708)
        overwrite = news.overwrites_for(guild.default_role)
        overwrite.send_messages = False
        overwrite.create_public_threads = False
        overwrite.create_private_threads = False
        overwrite.send_messages_in_threads = False
        await news.set_permissions(guild.default_role,overwrite=overwrite,reason='Keep official news staff-only')
        await news.set_permissions(me,view_channel=True,send_messages=True,embed_links=True,read_message_history=True,reason='Allow Global Gaming news embeds')
        await self.ticket_category(guild)
        await self.publish_panel()

    async def ticket_category(self, guild):
        staff = self.staff_role(guild)
        cid = self.store.get('ticket_category')
        category = guild.get_channel(int(cid)) if cid else None
        if category is not None and not isinstance(category,discord.CategoryChannel):
            raise ValueError('The ticket category setting is invalid.')
        if category is None or len(category.channels)>=48:
            category = await guild.create_category('🎫 PRIVATE TICKETS',overwrites=ticket_overwrites(guild,staff,guild.me),reason='Private support tickets requested by owner')
            self.store.put('ticket_category',category.id)
        return category

    async def publish_panel(self):
        ch = await self.channel(PANEL_ID)
        embed = discord.Embed(title='🎫 How can we help?',colour=PINK,description='Use **Open a ticket** for a question, a report or help with the community. Tell us what happened and the support team will reply when available.')
        embed.add_field(name='🔒 Private support',value='Your ticket is visible to you, the Support Team, server administrators and this bot. Never include passwords, login codes or payment details.',inline=False)
        embed.add_field(name='🩷 Keep things tidy',value='One open ticket per member. Closing a ticket makes it read-only; messages are kept and staff can reopen it.',inline=False)
        embed.set_footer(text='Global Gaming Lounge • ticket-panel:v1')
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        async for message in ch.history(limit=None):
            if message.author.id==self.bot.user.id and any(e.footer.text==embed.footer.text for e in message.embeds):
                await message.edit(embed=embed,view=TicketPanel(self),allowed_mentions=NO_MENTIONS)
                return
        await ch.send(embed=embed,view=TicketPanel(self),allowed_mentions=NO_MENTIONS)

    async def recover_tickets(self, guild):
        # A crash between channel creation and database commit must not create a second ticket.
        pending=self.store.pending_tickets()
        channels=await guild.fetch_channels() if pending else []
        for row in pending:
            marker = f"gg-ticket:v1:{row['id']}:{row['owner']}"
            matches = [ch for ch in channels if getattr(ch,'topic',None)==marker]
            if len(matches)==1:
                self.store.ticket_state(row['id'],'open',matches[0].id)
            elif not matches:
                self.store.ticket_state(row['id'],'failed')
            else:
                raise ValueError('Duplicate ticket metadata: ask the owner to inspect private tickets.')

    async def open_ticket(self, interaction, subject, details):
        if interaction.guild_id!=self.guild_id or interaction.channel_id!=PANEL_ID or interaction.user.bot:
            raise ValueError('Use the ticket panel in Global Gaming.')
        async with self.ticket_lock:
            guild=interaction.guild
            await self.recover_tickets(guild)
            existing=self.store.open_ticket(interaction.user.id)
            if existing:
                try:
                    ch=await self.channel(existing['channel'])
                    await self.ticket_header(ch,existing['id'],interaction.user.id,subject,details)
                    return ch
                except discord.NotFound:
                    self.store.ticket_state(existing['id'],'missing')
            category=await self.ticket_category(guild)
            tid=self.store.reserve_ticket(interaction.user.id)
            try:
                ch=await guild.create_text_channel(f'🎫・ticket-{tid:04}',category=category,
                    topic=f'gg-ticket:v1:{tid}:{interaction.user.id}',
                    overwrites=ticket_overwrites(guild,self.staff_role(guild),guild.me,interaction.user),
                    reason='Member requested a private support ticket')
            except Exception:
                # Keep 'creating': a timeout may mean Discord created the channel.
                raise
            self.store.ticket_state(tid,'open',ch.id)
            await self.ticket_header(ch,tid,interaction.user.id,subject,details)
            return ch

    async def ticket_header(self,ch,tid,owner,subject,details):
        marker=f'Global Gaming Lounge • ticket:{tid}'
        async for message in ch.history(limit=None):
            if message.author.id==self.bot.user.id and any(e.footer.text==marker for e in message.embeds):
                return
        embed=discord.Embed(title='🎫 '+safe_text(subject),description=safe_text(details),colour=BLUE if tid%2 else PINK)
        embed.add_field(name='Member',value=f'<@{owner}>')
        embed.add_field(name='Privacy',value='Visible to you, the Support Team, administrators and this bot. Close when resolved; the conversation remains available.',inline=False)
        embed.set_footer(text=marker)
        await ch.send(embed=embed,view=TicketControls(self),allowed_mentions=NO_MENTIONS)

    async def change_ticket(self, interaction, *, closed):
        row=self.store.ticket(interaction.channel_id)
        if interaction.guild_id!=self.guild_id or row is None:
            await interaction.response.send_message('This is not a managed ticket.',ephemeral=True)
            return
        staff=self.staff_role(interaction.guild)
        staff_access=interaction.permissions.administrator or staff in interaction.user.roles
        if not staff_access and (not closed or interaction.user.id!=row['owner']):
            await interaction.response.send_message('Only the ticket owner can close it. Support staff can close or reopen it.',ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.ticket_lock:
            row=self.store.ticket(interaction.channel_id)
            other=self.store.open_ticket(row['owner'])
            if not closed and other and other['id']!=row['id']:
                await interaction.followup.send('This member already has another open ticket.',ephemeral=True)
                return
            owner=interaction.guild.get_member(row['owner'])
            if owner is None:
                try:
                    owner=await interaction.guild.fetch_member(row['owner'])
                except discord.NotFound:
                    await interaction.followup.send('The ticket owner has left the server. Staff can keep this ticket as a record.',ephemeral=True)
                    return
            await interaction.channel.edit(name=f"{'🔒' if closed else '🎫'}・ticket-{row['id']:04}",
                overwrites=ticket_overwrites(interaction.guild,staff,interaction.guild.me,owner,closed=closed),reason='Ticket closed' if closed else 'Ticket reopened')
            self.store.ticket_state(row['id'],'closed' if closed else 'open')
            await interaction.followup.send('Ticket closed and made read-only. Messages were kept.' if closed else 'Ticket reopened.',ephemeral=True)

    async def recover_giveaway(self, row):
        async with self.giveaway_lock:
            row=self.store.giveaway(row['id'])
            if row['state']!='draft':
                return
            ch=await self.channel(row['channel'])
            marker=f"Global Gaming Lounge • giveaway:{row['id']}"
            message=None
            async for old in ch.history(limit=None):
                if old.author.id==self.bot.user.id and any(e.footer.text==marker for e in old.embeds):
                    message=old
                    break
            if message is None:
                message=await ch.send(embed=giveaway_embed(row,0),view=GiveawayEntry(self,disabled=True),allowed_mentions=NO_MENTIONS)
            self.store.activate(row['id'],message.id)
            await self.refresh_giveaway(self.store.giveaway(row['id']))

    async def refresh_giveaway(self, row):
        ch=await self.channel(row['channel'])
        message=await ch.fetch_message(row['message'])
        if message.author.id!=self.bot.user.id:
            raise ValueError('The giveaway message is not owned by this bot.')
        ended=row['state'] in ('ended','cancelled')
        await message.edit(embed=giveaway_embed(row,len(self.store.entries(row['id']))),view=GiveawayEntry(self,disabled=ended),allowed_mentions=NO_MENTIONS)
        if ended:
            self.store.published(row['id'])

    @tasks.loop(seconds=15,reconnect=True)
    async def worker(self):
        if (self.data_dir/'stop.request').exists():
            asyncio.create_task(self.bot.close())
            return
        for row in self.store.pending_giveaways():
            try:
                if row['state']=='draft':
                    await self.recover_giveaway(row)
                else:
                    if row['state']=='open':
                        row=self.store.finish(row['id'])
                    await self.refresh_giveaway(row)
            except (discord.HTTPException,ValueError) as exc:
                LOG.warning('Giveaway retry pending (%s): %s',row['id'],type(exc).__name__)
        dirty,self.dirty_giveaways=self.dirty_giveaways,set()
        for gid in dirty:
            try:
                row=self.store.giveaway(gid)
                if row and row['state']=='open':
                    await self.refresh_giveaway(row)
            except (discord.HTTPException,ValueError):
                self.dirty_giveaways.add(gid)
        # Health marker lets the Windows supervisor detect a working connection.
        if self.bot.is_ready():
            (self.data_dir/'healthy').write_text(str(time.time()),encoding='ascii')

    @worker.before_loop
    async def before_worker(self):
        await self.bot.wait_until_ready()

    async def boost_message(self,message):
        kinds={discord.MessageType.premium_guild_subscription,discord.MessageType.premium_guild_tier_1,
               discord.MessageType.premium_guild_tier_2,discord.MessageType.premium_guild_tier_3}
        if not message.guild or message.guild.id!=self.guild_id or message.type not in kinds:
            return
        if not self.store.claim_boost(message.id):
            return
        try:
            ch=await self.channel(BOOST_ID)
            embed=discord.Embed(title='💎 Thank you for boosting!',description=f'<@{message.author.id}>, thank you for supporting Global Gaming! 🩷',colour=PINK)
            embed.set_footer(text='Global Gaming Lounge • Boosts are always optional')
            await ch.send(embed=embed,allowed_mentions=NO_MENTIONS)
        except discord.HTTPException:
            self.store.retry_boost(message.id)
            raise

    async def shutdown(self):
        self.worker.cancel()
        task=self.worker.get_task()
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.store.close()
