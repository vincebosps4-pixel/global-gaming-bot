"""Global Gaming Lounge community bot. Python 3.12+."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
LOG = logging.getLogger("lounge")
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", "1567599947279376416"))
CHANNELS = {
    "welcome": 1567600695744667728,
    "rules": 1567600702174535760,
    "announcements": 1567600708012744704,
    "general": 1567599948680401102,
    "international-chat": 1567600218910761040,
    "introductions": 1567600312477552823,
    "fortnite-looking-for-group": 1567600440932303048,
    "minecraft-builds-and-lfg": 1567600514961510533,
    "rocket-league-looking-for-team": 1567600567444971650,
    "roblox-games-and-lfg": 1567600625024372827,
    "cod-chat": 1567622680448860395,
    "cod-looking-for-group": 1567622687826780321,
    "gta-vi-chat": 1567622888507310151,
    "gta-vi-news": 1567623771865747708,
    "server-boosts": 1567624635183530118,
    "giveaways": 1567624640912822423,
    "media": 1567624652367335475,
}
GUILD = discord.Object(id=GUILD_ID)
NO_MENTIONS = discord.AllowedMentions.none()


def template_embeds() -> dict[str, discord.Embed]:
    welcome = discord.Embed(
        title="🌍 Welcome to Global Gaming Lounge!",
        description="**Find your squad. Meet new friends. Make yourself at home.**\n\n"
        "🎮 Fortnite  •  ⛏️ Minecraft  •  🚗 Rocket League  •  🧱 Roblox\n"
        "🎖️ Call of Duty  •  🌴 GTA VI news & discussion\n\n"
        "**13+ community** · Meet Discord's minimum age for your country.",
        colour=0x00BFFF,
    )
    welcome.add_field(name="🚀 Start here", value=(
        "**1.** Read <#1567600702174535760>.\n"
        "**2.** Introduce yourself in <#1567600312477552823>.\n"
        "**3.** Chat in <#1567599948680401102> or <#1567600218910761040>.\n"
        "**4.** Find teammates in your game's group channel, then join a voice room."
    ), inline=False)
    welcome.add_field(name="🌐 A global community", value=(
        "English is our shared language in general and game chats. All languages are "
        "welcome in international-chat and in voice when your group agrees. "
        "Be welcoming to learners!"
    ), inline=False)
    welcome.add_field(name="🔊 Play or just hang out", value=(
        "Try General, Chill Room or Stream Lounge. New player or experienced gamer, "
        "there is a place for you here."
    ), inline=False)
    welcome.add_field(name="🎨 Make it yours", value=(
        "Use **Channels & Roles** to choose your games, country and devices. "
        "Every choice is optional, and you can change your answers later."
    ), inline=False)

    rules = discord.Embed(title="📜 Community Rules", colour=0xFF2D95,
                          description="**Keep the lounge friendly, fair and fun.**")
    rules_list = [
        ("1 · Respect everyone", "No harassment, hate speech, discrimination, threats or bullying. Stop banter when someone asks."),
        ("2 · Keep it safe for work", "No sexual content, graphic violence or disturbing material, including profiles, voice and streams."),
        ("3 · Protect privacy", "Do not share private information or conversations without permission. Never request passwords or login codes."),
        ("4 · No spam or scams", "No flooding, mass pings, suspicious links, unsolicited advertising or promotional DMs to members."),
        ("5 · Play fair", "No cheats, account theft, exploit sales or real-money/account trading. Follow each game's rules."),
        ("6 · Use the right space", "English in general and game chats; all languages in international-chat. Agree on a language in voice."),
        ("7 · Respect voice rooms", "No screaming or disruptive soundboards. Ask before recording others."),
        ("8 · Follow Discord's rules", "Meet Discord's age requirements and follow its [Guidelines](https://discord.com/guidelines) and [Terms](https://discord.com/terms)."),
        ("9 · Contact staff privately", "Report problems to the owner or moderators. No public arguments or moderation evasion. Responses may range from reminders to bans, depending on severity."),
    ]
    for title, body in rules_list:
        rules.add_field(name=title, value=body, inline=False)

    news = discord.Embed(title="📣 Community Updates", colour=0x00BFFF,
                        description="**Welcome to the start of Global Gaming Lounge!**\n\n"
                        "Explore Fortnite, Minecraft, Rocket League, Roblox and Call of Duty, "
                        "plus GTA VI news and discussion. "
                        "Say hello, find teammates and help build a friendly international community.")
    news.add_field(name="📅 Game nights", value="Confirmed events and community news will be posted here. Event times will include a timezone.", inline=False)
    news.add_field(name="💡 Your ideas", value="Share your ideas for game nights in <#1567599948680401102>.", inline=False)
    general = discord.Embed(
        title="👋 Welcome to the lounge!",
        description="Our shared English chat for gaming, everyday conversation and making friends. "
        "**All skill levels are welcome.**",
    )
    general.add_field(name="🌍 More languages", value="Want to chat in another language? Head to <#1567600218910761040>.", inline=False)
    general.add_field(name="🎮 Start the conversation", value="What are you playing today — Fortnite, Minecraft, Rocket League, Roblox or Call of Duty? Or join the GTA VI conversation!", inline=False)

    international = discord.Embed(
        title="🌐 All languages welcome!",
        description="Say hello in your language, meet players from around the world and help each other understand. "
        "Add a short English translation when you want to include everyone — automatic translations may miss context.",
    )
    international.add_field(name="💬 Keep everyone included", value="English is the shared language in general and game chats. In voice, agree on a language with the group. All community rules apply in every language.", inline=False)
    international.add_field(name="👋 Say hello", value="Hello • Hallo • Hola • Bonjour • Olá • Ciao • مرحبًا • こんにちは • 안녕하세요 • 你好", inline=False)

    introductions = discord.Embed(
        title="✨ Introduce yourself",
        description="Tell us your **nickname**, **favourite games** and the **languages you speak**. "
        "You can also share your gaming region and when you usually play.",
    )
    introductions.add_field(name="🔒 Keep personal details private", value="There is no need to share your real name, exact age, address or school.", inline=False)
    introductions.add_field(name="💬 Example", value="Hey, I’m Alex! I play Fortnite and Roblox, speak English and Dutch, and usually play on EU evenings.", inline=False)

    fortnite = discord.Embed(
        title="🎮 Find your Fortnite squad",
        description="Post your **region**, **mode** (Build / Zero Build / Creative), **casual or ranked**, "
        "**rank** if relevant, **language** and **how many teammates** you need.",
    )
    fortnite.add_field(name="📋 Example", value="EU | Zero Build | Casual | English/Dutch | Need 2 | Playing now", inline=False)
    fortnite.add_field(name="🔊 Party up", value="Agree on a party first, then meet in **Duos** or **Squads** in the Fortnite category.", inline=False)

    minecraft = discord.Embed(
        title="⛏️ Share builds & find Minecraft friends",
        description="Post screenshots of your builds or find a group. Include **Java or Bedrock**, **version**, "
        "**Survival or Creative**, **region**, **language** and **when you want to play**.",
    )
    minecraft.add_field(name="📋 Example", value="Bedrock | Survival | EU | English | Looking for a relaxed group tonight", inline=False)
    minecraft.add_field(name="🔒 Share safely", value="Only share a server address if you are allowed to invite others. Never post private home-server details.", inline=False)

    rocket = discord.Embed(
        title="🚗 Find your Rocket League team",
        description="Share your **region**, **rank**, **2v2 or 3v3**, **casual or ranked**, **language** and **availability**.",
    )
    rocket.add_field(name="📋 Example", value="EU | Gold II | 2v2 | Ranked | English | Playing now", inline=False)
    rocket.add_field(name="🤝 Be a great teammate", value="Be honest about your rank, encourage teammates and use the **Duos** or **Trios** in the Rocket League category voice room.", inline=False)

    roblox = discord.Embed(
        title="🧱 Discover Roblox games & find a party",
        description="Share the **experience name**, an **official Roblox game link** if useful, your **language** "
        "and **how many players** you need.",
    )
    roblox.add_field(name="📋 Example", value="Looking for 3 people | English/Dutch | Playing now", inline=False)
    roblox.add_field(name="🔊 Join your party", value="Use **Party 1** or **Party 2** in the Roblox category once your group is ready.", inline=False)
    roblox.add_field(name="🛡️ Play safely", value="No account trading, free-Robux scams or requests for login details.", inline=False)

    cod_chat = discord.Embed(
        title="🎖️ Welcome to the Call of Duty lounge",
        description="Talk loadouts, compare strategies and share your best moments. "
        "Mention the **Call of Duty title** and **mode** you are discussing so everyone can join in.",
    )
    cod_chat.add_field(name="🤝 Find your squad", value="Looking for teammates? Post in <#1567622687826780321>, then join **Squad** or **Warzone** in the Call of Duty category.", inline=False)
    cod_chat.add_field(name="🎮 Good games, good vibes", value="English is the shared language here. Keep it friendly, play fair and keep media safe for work.", inline=False)

    cod_lfg = discord.Embed(
        title="🎯 Find your Call of Duty squad",
        description="Share your **game/title**, **mode**, **region**, **platform**, "
        "**casual or ranked**, **language**, **open spots** and **when you are playing**. "
        "Add your rank if it matters to your group.",
    )
    cod_lfg.add_field(name="📋 Example", value="Warzone | Battle Royale | EU | PC, crossplay on | Casual | English | Need 2 | Playing now", inline=False)
    cod_lfg.add_field(name="🔊 Ready up", value="Agree on a party first, then meet in **Squad** or **Warzone** in the Call of Duty category. Respect teammates of every skill level.", inline=False)

    gta_chat = discord.Embed(
        title="🌴 Welcome to the GTA VI lounge",
        description="Talk trailers, characters, locations and what you are excited to explore. "
        "This is our home for **GTA VI news and discussion**.",
    )
    gta_chat.add_field(name="📰 News or theory?", value="Find official updates in <#1567623771865747708>. Label theories and rumours clearly, and use spoiler tags for story details.", inline=False)
    gta_chat.add_field(name="🔊 Hang out", value="Meet in **Lounge** in the GTA VI category for a chat. Keep posts and streams safe for work; our community rules still apply.", inline=False)

    gta_news = discord.Embed(
        title="📰 GTA VI • Official updates",
        description="A place for staff to share confirmed trailers, announcements and updates "
        "with a link to the original source.",
    )
    gta_news.add_field(name="🌴 Follow the source", value="Visit the [official Rockstar Games GTA VI page](https://www.rockstargames.com/VI). Release and platform information can change; check the source for the latest details.", inline=False)
    gta_news.add_field(name="💬 Discuss the news", value="Share reactions and clearly labelled theories in <#1567622888507310151>. News is posted by staff when available.", inline=False)

    boosts = discord.Embed(
        title="💎 Support the lounge",
        description="Enjoying the community? **Server Boosts are completely optional.** "
        "You are welcome here whether you boost or not.",
    )
    boosts.add_field(name="✨ How to boost", value="Open the server menu and choose **Server Boost**. Discord shows the price, subscription terms and available server perks before you decide.", inline=False)
    boosts.add_field(name="🩷 Thank you, boosters", value="Discord manages the **Server Booster** role for active boosters. Boosting does not grant moderation powers or special treatment in giveaways.", inline=False)
    boosts.add_field(name="🔒 Use Discord's own checkout", value="Staff will never ask you to send payment details, passwords or login codes in a message.", inline=False)

    giveaways = discord.Embed(
        title="🎉 Community giveaways",
        description="Future giveaways will be posted here by staff. "
        "Each giveaway will clearly show the **prize**, **closing time**, **number of winners** "
        "and any **eligibility rules** before entries open.",
    )
    giveaways.add_field(name="🎟️ Watch for an active giveaway", value="This is an information post, not an active giveaway. Entry instructions will appear on each announced giveaway.", inline=False)
    giveaways.add_field(name="🛡️ Stay safe", value="Do not pay to claim a prize or share passwords or login codes. Check unexpected prize messages with the server owner.", inline=False)

    media = discord.Embed(
        title="📸 Your gaming highlights",
        description="Share your **clips**, **screenshots**, **builds**, **fan art** and favourite gaming moments. "
        "Add the game name and a short caption so everyone knows what they are seeing.",
    )
    media.add_field(name="✨ Give credit", value="Share your own work or content you have permission to post. Credit the original creator when appropriate; no stolen art or spam advertising.", inline=False)
    media.add_field(name="🩷 Keep it comfortable", value="No graphic or sexual content. Use spoiler tags for story spoilers, and get permission before sharing other people's voices, faces or private messages.", inline=False)

    result = {
        "welcome": welcome, "rules": rules, "announcements": news,
        "general": general, "international-chat": international,
        "introductions": introductions, "fortnite-looking-for-group": fortnite,
        "minecraft-builds-and-lfg": minecraft,
        "rocket-league-looking-for-team": rocket, "roblox-games-and-lfg": roblox,
        "cod-chat": cod_chat, "cod-looking-for-group": cod_lfg,
        "gta-vi-chat": gta_chat, "gta-vi-news": gta_news,
        "server-boosts": boosts, "giveaways": giveaways, "media": media,
    }
    for index, (key, embed) in enumerate(result.items()):
        embed.colour = discord.Colour(0x00BFFF if index % 2 == 0 else 0xFF2D95)
        embed.set_footer(text=f"Global Gaming Lounge • {key} • All languages. All skill levels.")
    return result


def announcement_embed(title: str, body: str, colour: str) -> discord.Embed:
    if not 1 <= len(title.strip()) <= 256 or not 1 <= len(body.strip()) <= 4000:
        raise ValueError("Use a title of 1–256 characters and text of 1–4000 characters.")
    colour = colour.strip().removeprefix("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", colour):
        raise ValueError("Use a six-digit colour such as #00BFFF.")
    embed = discord.Embed(title=title.strip(), description=body.strip(), colour=int(colour, 16))
    embed.set_footer(text="Global Gaming Lounge • Announcement")
    if len(embed) > 6000:
        raise ValueError("The embed is too long.")
    return embed


def is_manager(interaction: discord.Interaction) -> bool:
    return interaction.guild_id == GUILD_ID and interaction.permissions.manage_guild


async def upsert_embed(channel, bot_id: int, embed: discord.Embed) -> str:
    """Recover the existing bot message from Discord, even after a host restart.

    No local database and no access to other people's message contents are needed.
    History errors propagate: never post a duplicate just because a read failed.
    """
    async for message in channel.history(limit=None):
        if message.author.id != bot_id:
            continue
        if any(e.footer.text == embed.footer.text for e in message.embeds):
            await message.edit(embed=embed, allowed_mentions=NO_MENTIONS)
            return "updated"
    await channel.send(embed=embed, allowed_mentions=NO_MENTIONS)
    return "created"


class LoungeBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True  # System boost events; no message-content intent.
        super().__init__(intents=intents, allowed_mentions=NO_MENTIONS)
        self.tree = app_commands.CommandTree(self)
        self.publish_lock = asyncio.Lock()
        self.initial_setup_attempted = False
        self.community = None
        self.instance_lock = None

    async def setup_hook(self):
        if self.user.id != 1567606693674885302:
            raise ValueError("Use the token for the Global Gaming application.")
        from community import CommunityFeatures
        from instance_lock import InstanceLock
        data_dir = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
        self.instance_lock = InstanceLock(data_dir/'bot.lock')
        self.community = CommunityFeatures(self, GUILD_ID, data_dir)
        self.community.register()
        await self.tree.sync(guild=GUILD)

    async def destination(self, name: str) -> discord.TextChannel:
        channel = self.get_channel(CHANNELS[name]) or await self.fetch_channel(CHANNELS[name])
        if not isinstance(channel, discord.TextChannel) or channel.guild.id != GUILD_ID:
            raise ValueError("The configured channel is not a text channel in the intended server.")
        member = channel.guild.me
        if member is None:
            raise ValueError("The bot is not a member of this server.")
        perms = channel.permissions_for(member)
        required = ("view_channel", "send_messages", "embed_links", "read_message_history")
        missing = [name for name in required if not getattr(perms, name)]
        if missing:
            raise ValueError(f"Missing channel permissions in #{channel.name}: {', '.join(missing)}")
        return channel

    async def publish_templates(self) -> str:
        async with self.publish_lock:
            result = []
            for name, embed in template_embeds().items():
                try:
                    embed.set_author(name=self.user.display_name, icon_url=self.user.display_avatar.url)
                    embed.set_thumbnail(url=self.user.display_avatar.url)
                    channel = await self.destination(name)
                    status = await upsert_embed(channel, self.user.id, embed)
                    result.append(f"#{name}: {status}")
                except (discord.HTTPException, ValueError) as exc:
                    # Don't include HTTP bodies or credentials in logs/responses.
                    detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
                    result.append(f"#{name}: NOT published ({detail})")
            return "\n".join(result)

    async def on_ready(self):
        LOG.info("Connected as %s", self.user)
        if not self.initial_setup_attempted:
            self.initial_setup_attempted = True
            once = os.getenv("PUBLISH_ONCE", "false").lower() == "true"
            try:
                if getattr(self, 'community', None) is not None:
                    await self.community.recover_tickets(self.get_guild(GUILD_ID))
                    if os.getenv("AUTO_SETUP", "true").lower() == "true":
                        try:
                            await self.community.setup()
                            LOG.info("Community setup ready: channel style and ticket panel.")
                        except (discord.HTTPException, ValueError) as exc:
                            LOG.warning("Community setup pending: %s", str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
                    if not once and not self.community.worker.is_running():
                        self.community.worker.start()
                if once or os.getenv("AUTO_SETUP", "true").lower() == "true":
                    LOG.info("Template setup:\n%s", await self.publish_templates())
            finally:
                if once:
                    await self.close()

    async def on_message(self, message):
        if self.community is not None:
            await self.community.boost_message(message)

    async def close(self):
        if self.community is not None:
            community, self.community = self.community, None
            await community.shutdown()
        await super().close()
        if self.instance_lock is not None:
            self.instance_lock.close()
            self.instance_lock = None


bot = LoungeBot()


class PublishPreview(discord.ui.View):
    def __init__(self, owner_id: int, embed: discord.Embed):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.embed = embed
        self.lock = asyncio.Lock()
        self.used = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id or not is_manager(interaction):
            await interaction.response.send_message("Only the authorised server manager can use this preview.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Publish announcement", style=discord.ButtonStyle.success)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            if self.used:
                await interaction.response.send_message("This preview has already been handled.", ephemeral=True)
                return
            self.used = True
            await interaction.response.defer(ephemeral=True)
            try:
                channel = await bot.destination("announcements")
                sent = await channel.send(embed=self.embed, allowed_mentions=NO_MENTIONS)
                await interaction.edit_original_response(content=f"Published: {sent.jump_url}", embed=None, view=None)
            except (discord.HTTPException, ValueError):
                await interaction.edit_original_response(content="Publishing could not be confirmed. Check #announcements before creating a new preview. Check the bot's channel permissions too.", embed=None, view=None)
            self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with self.lock:
            if self.used:
                await interaction.response.send_message("This preview has already been handled.", ephemeral=True)
                return
            self.used = True
            await interaction.response.edit_message(content="Cancelled. Nothing was posted.", embed=None, view=None)
            self.stop()


class AnnouncementForm(discord.ui.Modal, title="Create an announcement"):
    headline = discord.ui.TextInput(label="Title", max_length=256)
    body = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, max_length=4000)
    colour = discord.ui.TextInput(label="Colour (hex)", default="#00BFFF", min_length=6, max_length=7)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_manager(interaction):
            await interaction.response.send_message("Manage Server permission is required.", ephemeral=True)
            return
        try:
            embed = announcement_embed(str(self.headline), str(self.body), str(self.colour))
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(content="Preview — only you can see this. Publish within 5 minutes.", embed=embed, view=PublishPreview(interaction.user.id, embed), ephemeral=True)


@bot.tree.command(name="setup_embeds", description="Place or update the community and gaming-information embeds.", guild=GUILD)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.check(is_manager)
async def setup_embeds(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await interaction.followup.send(await bot.publish_templates(), ephemeral=True)


@bot.tree.command(name="announce", description="Create a coloured announcement with a private preview.", guild=GUILD)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.check(is_manager)
async def announce(interaction: discord.Interaction):
    await interaction.response.send_modal(AnnouncementForm())


@bot.tree.command(name="bot_status", description="Check community features and channel permissions.", guild=GUILD)
@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
@app_commands.check(is_manager)
async def bot_status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    lines = ["Global Gaming Lounge community bot is online."]
    if bot.community:
        lines.append("Giveaway timer: " + ("running" if bot.community.worker.is_running() else "not running"))
        try:
            bot.community.staff_role(interaction.guild)
            lines.append("Support role: ready")
        except ValueError:
            lines.append("Support role: needs configuration")
        for perm in ("manage_channels", "manage_roles"):
            lines.append(perm + ": " + ("ready" if getattr(interaction.guild.me.guild_permissions,perm) else "missing"))
    for name in CHANNELS:
        try:
            await bot.destination(name)
            lines.append(f"#{name}: ready")
        except (discord.HTTPException, ValueError):
            lines.append(f"#{name}: check channel access and permissions")
    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.error
async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    message = "This command requires Manage Server permission in Global Gaming Lounge." if isinstance(error, app_commands.CheckFailure) else "The command could not finish. Check the bot permissions and try again."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)
    LOG.warning("Command error: %s", type(error).__name__)


if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set DISCORD_BOT_TOKEN in your hosting secrets or .env first. Never paste it into chat.")
    logging.basicConfig(level=logging.INFO)
    bot.run(token)
