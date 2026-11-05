"""Persistent tickets, giveaways and boost acknowledgements for one community."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

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
CREATOR_GROUP = '🎬 Content Creators'
CREATOR_PLATFORMS = {
    'TikTok': ('🎵 TikTok Creator','https://www.tiktok.com/@'),
    'YouTube': ('▶️ YouTube Creator','https://www.youtube.com/@'),
    'Twitch': ('🟣 Twitch Creator','https://www.twitch.tv/'),
    'Instagram': ('📸 Instagram Creator','https://www.instagram.com/'),
}

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
        bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                                embed_links=True),
    }
    if staff is not None:
        result[staff] = discord.PermissionOverwrite(view_channel=True,send_messages=True,
                                                   read_message_history=True,embed_links=True)
    if owner is not None:
        # At channel creation Discord rejects even DENY bits the bot itself lacks.
        # Ordinary members inherit disabled permissions when the bot lacks them too.
        owner_access = discord.PermissionOverwrite(view_channel=True, send_messages=not closed, read_message_history=True)
        for permission in ('create_public_threads','create_private_threads','create_instant_invite',
                           'send_messages_in_threads','mention_everyone'):
            if getattr(bot_member.guild_permissions,permission):
                setattr(owner_access,permission,False)
        result[owner] = owner_access
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
            if isinstance(exc,discord.HTTPException):
                LOG.warning('Ticket action failed: status=%s code=%s',exc.status,exc.code)
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

    @discord.ui.button(label='Apply for Creator', emoji='🎬', style=discord.ButtonStyle.secondary, custom_id='gg:creator:open:v1')
    async def creator(self, interaction, button):
        if not self.features.creators.at_panel(interaction):
            await interaction.response.send_message('Open the ticket panel in Global Gaming.',ephemeral=True)
            return
        await interaction.response.send_message('Which account would you like the owner to verify?',
            view=CreatorPlatformPicker(self.features.creators,interaction.user.id),ephemeral=True)


class TicketControls(SafeView):
    def __init__(self, features, *, closed=False):
        super().__init__(timeout=None)
        self.features = features
        self.close_ticket.disabled = closed
        self.reopen_ticket.disabled = not closed

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


def creator_application_input(handle, followers):
    handle = unicodedata.normalize('NFC',handle.strip().removeprefix('@'))
    valid_char = lambda ch: ch in '._-' or unicodedata.category(ch)[0] in 'LNM'
    if not 1 <= len(handle) <= 64 or not all(valid_char(ch) for ch in handle) or not any(ch.isalnum() for ch in handle):
        raise ValueError('Enter the account handle, for example @yourname, without a profile link or spaces.')
    if not re.fullmatch(r'[0-9]{1,12}',followers.strip()):
        raise ValueError('Enter the number of followers or subscribers in digits, for example 1250.')
    return handle,int(followers.strip())


def creator_embed(row, owner):
    platform = row['platform']
    base = CREATOR_PLATFORMS[platform][1]
    url = base + quote(row['handle'],safe='')
    embed = discord.Embed(title='🎬 Creator application',colour=PINK,
        description=f"<@{row['member']}> applied for **{platform} Creator**.")
    embed.add_field(name=f'{platform} account',value=f"[@{safe_text(row['handle'])}]({url})")
    embed.add_field(name='Reported followers / subscribers',value=f"{row['followers']:,}")
    if row['state']=='pending':
        embed.add_field(name='Your verification keyword',value=f"\u0060{row['keyword']}\u0060 · expires <t:{row['expires']}:R>",inline=False)
        embed.add_field(name='Prove that you control this account',
            value=f"Temporarily put the keyword in that account’s bio or channel description and tell <@{owner}> when it is visible. "
                  f"Alternatively, ask the owner here which inbox to use, then send the keyword **from the linked {platform} account**. "
                  "If DMs are unavailable, use the bio option. You may remove the keyword after the review.",inline=False)
        embed.add_field(name='Owner review',value='Open the linked profile and check the exact keyword there, or check the sender of the social DM. A Discord message or a screenshot alone does not establish account ownership. Only the server owner can approve.',inline=False)
    else:
        status={'approved':'Approved · creator roles granted','approving':'Verified by the owner · role assignment in progress. The owner can retry if interrupted.',
                'declined':'Declined by the server owner','withdrawn':'Withdrawn by the applicant'}[row['state']]
        embed.add_field(name='Decision',value=status,inline=False)
    embed.set_footer(text=f"Global Gaming • creator:{row['id']}")
    return embed


class CreatorApplication(discord.ui.Modal, title='Apply for a creator role'):
    handle = discord.ui.TextInput(label='Account handle',placeholder='@yourname',max_length=65)
    followers = discord.ui.TextInput(label='Followers / subscribers (digits only)',placeholder='1250',max_length=12)

    def __init__(self, desk, platform, applicant):
        super().__init__()
        self.desk,self.platform,self.applicant = desk,platform,applicant

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id!=self.applicant or not self.desk.at_panel(interaction):
            await interaction.followup.send('Use the ticket panel with your own account.',ephemeral=True)
            return
        try:
            handle,count=creator_application_input(str(self.handle),str(self.followers))
            channel=await self.desk.apply(interaction,self.platform,handle,count)
            note=f'Continue in your private creator ticket: {channel.mention}. One application at a time.'
        except ValueError as exc:
            note=str(exc)
        except (discord.HTTPException,OSError):
            note='The ticket could not be confirmed. Apply again to recover your existing application.'
        await interaction.followup.send(note,ephemeral=True,allowed_mentions=NO_MENTIONS)


class CreatorPlatformPicker(SafeView):
    def __init__(self, desk, applicant):
        super().__init__(timeout=180)
        self.desk,self.applicant=desk,applicant

    @discord.ui.select(placeholder='Choose your platform',options=[discord.SelectOption(label=p) for p in CREATOR_PLATFORMS])
    async def platform(self, interaction, select):
        if interaction.user.id!=self.applicant or not self.desk.at_panel(interaction):
            await interaction.response.send_message('Open your own creator application.',ephemeral=True)
            return
        await interaction.response.send_modal(CreatorApplication(self.desk,select.values[0],self.applicant))


class CreatorReview(SafeView):
    def __init__(self, desk, row):
        super().__init__(timeout=180)
        self.desk,self.rid,self.keyword=desk,row['id'],row['keyword']

    @discord.ui.button(label='I verified this account · grant roles',style=discord.ButtonStyle.success)
    async def approve(self, interaction, button):
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            note=await self.desk.approve(interaction,self.rid,self.keyword)
        except ValueError as exc:
            note=str(exc)
        except (discord.HTTPException,OSError):
            note='Role assignment or the ticket update could not be confirmed. Use Owner review again to check or finish this request.'
        await interaction.edit_original_response(content=note,allowed_mentions=NO_MENTIONS)
        self.stop()


class CreatorControls(SafeView):
    def __init__(self,desk,state='pending'):
        super().__init__(timeout=None)
        self.desk=desk
        self.review.disabled=state not in ('pending','approving')
        for b in (self.decline,self.renew,self.withdraw):
            b.disabled=state!='pending'

    @discord.ui.button(label='Owner review',style=discord.ButtonStyle.success,custom_id='gg:creator:review:v1')
    async def review(self,i,button): await self.desk.action(i,'review')

    @discord.ui.button(label='Decline',style=discord.ButtonStyle.danger,custom_id='gg:creator:decline:v1')
    async def decline(self,i,button): await self.desk.action(i,'decline')

    @discord.ui.button(label='New keyword',style=discord.ButtonStyle.secondary,custom_id='gg:creator:renew:v1')
    async def renew(self,i,button): await self.desk.action(i,'renew')

    @discord.ui.button(label='Withdraw',style=discord.ButtonStyle.secondary,custom_id='gg:creator:withdraw:v1')
    async def withdraw(self,i,button): await self.desk.action(i,'withdraw')


class CreatorDesk:
    def __init__(self, features):
        self.f=features
        self.store=features.store
        self.lock=asyncio.Lock()

    def at_panel(self,i):
        return i.guild_id==self.f.guild_id and i.channel_id==PANEL_ID and not i.user.bot

    def roles(self,guild,platform):
        result=[]
        for name,group in ((CREATOR_PLATFORMS[platform][0],False),(CREATOR_GROUP,True)):
            key='creator_role_id:'+name
            saved=self.store.get(key)
            matches=[r for r in guild.roles if str(r.id)==saved] if saved else [r for r in guild.roles if r.name==name]
            if len(matches)!=1:
                raise ValueError(f'The owner must check the creator role {name}.')
            role=matches[0]
            if (role.name!=name or role.managed or role.is_default() or not role.is_assignable() or
                    role.permissions.value or role.mentionable or role.hoist!=group or
                    any(ch.overwrites_for(role).pair()[0].value for ch in guild.channels)):
                raise ValueError(f'The owner must check the position, display and permissions of {name} before granting it.')
            if not saved:
                self.store.put(key,role.id)
            result.append(role)
        return result

    async def put_card(self,ch,row):
        allowed={row['member'],ch.guild.owner_id,self.f.bot.user.id}
        if (ch.overwrites_for(ch.guild.default_role).view_channel is not False or
                any(target.id not in allowed and access.view_channel is True for target,access in ch.overwrites.items())):
            raise ValueError('The owner must restore the private creator ticket permissions before continuing.')
        message=None
        if row['message']:
            try: message=await ch.fetch_message(row['message'])
            except discord.NotFound: pass
        marker=f"Global Gaming • creator:{row['id']}"
        if message is None:
            async for item in ch.history(limit=None):
                if item.author.id==self.f.bot.user.id and any(e.footer.text==marker for e in item.embeds):
                    message=item
                    break
        payload=dict(embed=creator_embed(row,ch.guild.owner_id),view=CreatorControls(self,row['state']),allowed_mentions=NO_MENTIONS)
        if message:
            if message.author.id!=self.f.bot.user.id:
                raise ValueError('The creator ticket card is invalid. Contact the owner.')
            await message.edit(**payload)
        else:
            message=await ch.send(**payload)
        self.store.creator_location(row['id'],ch.id,message.id)

    async def apply(self,i,platform,handle,count):
        if platform not in CREATOR_PLATFORMS or not self.at_panel(i):
            raise ValueError('Use the Global Gaming ticket panel.')
        async with self.lock:
            row=self.store.pending_creator(i.user.id)
            if row is None:
                platform_role,_=self.roles(i.guild,platform)
                if platform_role in i.user.roles:
                    raise ValueError('You already have the creator role for this platform.')
                row=self.store.new_creator(i.user.id,platform,handle,count)
            ch=None
            topic=f"gg-creator:v1:{row['id']}:{i.user.id}"
            if row['channel']:
                try: ch=await self.f.channel(row['channel'])
                except discord.NotFound: pass
            if ch is None:
                matches=[c for c in await i.guild.fetch_channels() if getattr(c,'topic',None)==topic]
                if len(matches)>1:
                    raise ValueError('The owner must check duplicate creator tickets.')
                if matches:
                    ch=matches[0]
                else:
                    ch=await i.guild.create_text_channel(f"🎬・creator-{row['id']:04}",category=await self.f.ticket_category(i.guild),
                        topic=topic,overwrites=ticket_overwrites(i.guild,None,i.guild.me,i.user),reason='Private creator application')
                self.store.creator_location(row['id'],ch.id)
                row=self.store.creator_request(row['id'])
            await self.put_card(ch,row)
            return ch

    async def action(self,i,action):
        row=self.store.creator_for_channel(i.channel_id)
        if i.guild_id!=self.f.guild_id or not row or row['message']!=i.message.id:
            await i.response.send_message('Use the card in its original creator ticket.',ephemeral=True)
            return
        expected=i.guild.owner_id if action in ('review','decline') else row['member']
        if i.user.id!=expected:
            await i.response.send_message('Only the server owner can review; only the applicant can renew or withdraw.',ephemeral=True)
            return
        await i.response.defer(ephemeral=True,thinking=True)
        async with self.lock:
            row=self.store.creator_request(row['id'])
            if row['state']!='pending' and not (row['state']=='approving' and action=='review'):
                await self.put_card(i.channel,row)
                await i.edit_original_response(content=f"This application is {row['state']}.")
                return
            if action=='review':
                await i.edit_original_response(content=f"Verify **{row['platform']}** account **@{safe_text(row['handle'])}**. "
                    f"Confirm only after you personally saw \u0060{row['keyword']}\u0060 on that profile or received it directly from that account. "
                    "Approval grants Content Creators and the selected platform role.",view=CreatorReview(self,row),allowed_mentions=NO_MENTIONS)
                return
            if action=='renew': self.store.renew_creator(row['id'])
            else: self.store.creator_decision(row['id'],'pending','declined' if action=='decline' else 'withdrawn',i.user.id)
            await self.put_card(i.channel,self.store.creator_request(row['id']))
            await i.edit_original_response(content='Creator ticket updated.')

    async def approve(self,i,rid,keyword):
        if i.guild_id!=self.f.guild_id or i.user.id!=i.guild.owner_id:
            raise ValueError('Only the Global Gaming server owner can grant creator roles.')
        async with self.lock:
            row=self.store.creator_request(rid)
            if not row or row['channel']!=i.channel_id or row['keyword']!=keyword:
                raise ValueError('This review is stale. Open Owner review on the current card.')
            if row['state']=='approved':
                await self.put_card(i.channel,row)
                return 'This application is already approved.'
            if row['state'] not in ('pending','approving'):
                raise ValueError('This request has already been closed.')
            if row['state']=='pending' and row['expires']<=int(time.time()):
                raise ValueError('The keyword has expired. Ask the applicant to choose New keyword and verify again.')
            roles=self.roles(i.guild,row['platform'])
            try: member=await i.guild.fetch_member(row['member'])
            except discord.NotFound:
                raise ValueError('The applicant must be a current server member.') from None
            if row['state']=='pending':
                try: self.store.creator_decision(rid,'pending','approving',i.user.id)
                except sqlite3.IntegrityError:
                    raise ValueError('That platform account is already attached to a verified or in-progress application.') from None
            # Each role add is idempotent. Keep the owner-confirmed state on a partial network failure.
            await member.add_roles(*roles,reason=f"Creator account verified by guild owner; application {rid}")
            self.store.creator_decision(rid,'approving','approved',i.user.id)
            await self.put_card(i.channel,self.store.creator_request(rid))
            return f"Approved. Content Creators and {row['platform']} Creator were granted."


class CommunityFeatures:
    def __init__(self, bot, guild_id, data_dir):
        self.bot, self.guild_id = bot, guild_id
        self.data_dir = Path(data_dir)
        self.store = Store(self.data_dir / 'community.sqlite3')
        self.creators = CreatorDesk(self)
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
        self.bot.add_view(CreatorControls(self.creators))
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
            embed.add_field(name='Player pass',value='Use /profile to customize your gamer card, earn optional chat levels and badges, or share your card.',inline=False)
            embed.add_field(name='Content creators',value=f'Choose **Apply for Creator** in <#{PANEL_ID}> to verify a TikTok, YouTube, Twitch or Instagram account with the server owner.',inline=False)
            if self.is_manager(interaction):
                embed.add_field(name='Staff commands',value='`/announce` · `/welcome_preview` · `/welcome_member` · `/giveaway` · `/giveaway_cancel` · `/setup_embeds` · `/setup_community` · `/bot_status`',inline=False)
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
        embed.add_field(name='🎬 Creator applications',value='Choose **Apply for Creator**, pick TikTok, YouTube, Twitch or Instagram, and enter your @handle and follower or subscriber count. Your separate private creator ticket is visible to you, the server owner, administrators and this bot. The owner checks your account and grants the roles.',inline=False)
        embed.add_field(name='🩷 Keep things tidy',value='You can have one open support ticket and one pending creator application. Support tickets become read-only when closed.',inline=False)
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
            # Keep the channel name stable; Discord heavily rate-limits name changes.
            await interaction.channel.edit(overwrites=ticket_overwrites(interaction.guild,staff,interaction.guild.me,owner,closed=closed),reason='Ticket closed' if closed else 'Ticket reopened')
            self.store.ticket_state(row['id'],'closed' if closed else 'open')
            marker=f"Global Gaming Lounge • ticket:{row['id']}"
            async for message in interaction.channel.history(limit=None):
                if message.author.id==self.bot.user.id and any(e.footer.text==marker for e in message.embeds):
                    embed=message.embeds[0]
                    for index in reversed(range(len(embed.fields))):
                        if embed.fields[index].name=='Status':
                            embed.remove_field(index)
                    embed.add_field(name='Status',value='🔒 Closed — read-only for the ticket owner.' if closed else '🔓 Open — the support team can help here.',inline=False)
                    await message.edit(embed=embed,view=TicketControls(self,closed=closed),allowed_mentions=NO_MENTIONS)
                    break
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
