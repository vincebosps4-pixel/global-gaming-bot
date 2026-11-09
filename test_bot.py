import unittest
import asyncio
import io
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from bot import CHANNELS, GUILD_ID, LoungeBot, PublishPreview, announcement_embed, is_manager, template_embeds, upsert_embed, welcome_card, welcome_payload
from storage import Store
from bot import ProfilePanel, eligible_chat, gamer_card, pass_file, player_sheet, profile
from PIL import Image


class WelcomeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store_path = Path(self.temp.name) / "data.sqlite3"
        self.store = Store(self.store_path)
        avatar = SimpleNamespace(read=AsyncMock(side_effect=OSError("avatar unavailable")))
        avatar.with_size = lambda size: avatar
        avatar.with_format = lambda fmt: avatar
        self.member = SimpleNamespace(id=42, bot=False, guild=SimpleNamespace(id=GUILD_ID),
            joined_at=datetime(2026, 11, 4, tzinfo=timezone.utc), display_name="Player One", mention="<@42>", display_avatar=avatar)
        self.channel = SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(id=99)),
            guild=SimpleNamespace(me=object()), permissions_for=lambda member: SimpleNamespace(attach_files=True))
        self.client = SimpleNamespace(community=SimpleNamespace(store=self.store),
            welcome_slots=asyncio.Semaphore(2), destination=AsyncMock(return_value=self.channel))
        self.client.send_member_welcome = LoungeBot.send_member_welcome.__get__(self.client)
        self.client.give_join_badge = AsyncMock()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    async def test_join_once_across_duplicate_events_and_restart_then_rejoin(self):
        await asyncio.gather(LoungeBot.on_member_join(self.client,self.member), LoungeBot.on_member_join(self.client,self.member))
        self.channel.send.assert_awaited_once()
        self.store.close()
        self.store = Store(self.store_path)
        self.client.community.store = self.store
        await LoungeBot.on_member_join(self.client,self.member)
        self.channel.send.assert_awaited_once()
        self.member.joined_at += timedelta(days=1)
        await LoungeBot.on_member_join(self.client,self.member)
        self.assertEqual(self.channel.send.await_count,2)

    async def test_manual_welcome_after_offline_join_deduplicates_gateway_delivery(self):
        from bot import welcome_member
        self.assertTrue(welcome_member.default_permissions.manage_guild)
        self.assertIn(is_manager, welcome_member.checks)
        interaction = SimpleNamespace(response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
        with patch("bot.bot", self.client):
            await welcome_member.callback(interaction,self.member)
        await LoungeBot.on_member_join(self.client,self.member)
        self.channel.send.assert_awaited_once()
        self.assertIn("Welcome posted", interaction.followup.send.await_args.args[0])

    async def test_bots_other_servers_and_one_shot_publish_do_not_get_welcomes(self):
        self.member.bot = True
        await LoungeBot.on_member_join(self.client,self.member)
        self.member.bot = False
        self.member.guild.id = 1
        await LoungeBot.on_member_join(self.client,self.member)
        self.member.guild.id = GUILD_ID
        with patch.dict("os.environ", {"PUBLISH_ONCE":"true"}):
            await LoungeBot.on_member_join(self.client,self.member)
        self.client.destination.assert_not_awaited()
        self.channel.send.assert_not_awaited()

    async def test_upload_permission_failure_does_not_consume_join(self):
        self.channel.permissions_for = lambda member: SimpleNamespace(attach_files=False)
        await LoungeBot.on_member_join(self.client,self.member)
        self.channel.send.assert_not_awaited()
        self.assertFalse(self.store.has_welcome(42,self.member.joined_at.isoformat()))

    async def test_ambiguous_send_error_does_not_send_twice(self):
        self.channel.send.side_effect = OSError("transport disconnected after send")
        await LoungeBot.on_member_join(self.client,self.member)
        await LoungeBot.on_member_join(self.client,self.member)
        self.channel.send.assert_awaited_once()

    async def test_forbidden_can_retry_after_permissions_fixed(self):
        self.channel.send.side_effect = discord.Forbidden(SimpleNamespace(status=403,reason="Forbidden"),"Missing permissions")
        await LoungeBot.on_member_join(self.client,self.member)
        self.channel.send.side_effect = None
        await LoungeBot.on_member_join(self.client,self.member)
        self.assertEqual(self.channel.send.await_count,2)

    async def test_private_preview_preserves_name_disables_mentions_and_links_correct_guild(self):
        self.member.display_name = "**@everyone** 測試"
        payload = await welcome_payload(self.member)
        try:
            self.assertLess(len(payload['embed']),6000)
            self.assertIn("測試",payload['embed'].title)
            self.assertFalse(payload['allowed_mentions'].everyone)
            self.assertFalse(payload['allowed_mentions'].users)
            self.assertFalse(payload['allowed_mentions'].roles)
            self.assertTrue(all(str(GUILD_ID) in b.url for b in payload['view'].children))
            self.assertEqual(payload['embed'].image.url,"attachment://welcome.png")
            self.assertEqual(payload['file'].filename,"welcome.png")
            self.channel.send.assert_not_awaited()
        finally:
            payload['file'].close()
            payload['view'].stop()

    async def test_card_is_valid_and_uses_avatar_with_long_international_names(self):
        avatar = io.BytesIO()
        Image.new('RGB',(50,50),'red').save(avatar,format='PNG')
        for name in ('Player One','VeryLongPlayerName'*8,'日本語 العربية 🎮','\n\u202e'):
            raw = welcome_card(name,avatar.getvalue())
            self.assertLess(len(raw),1_000_000)
            with Image.open(io.BytesIO(raw)) as card:
                self.assertEqual(card.size,(1200,450))
                self.assertEqual(card.getpixel((204,242)),(255,0,0))
        with Image.open(io.BytesIO(welcome_card('Player',b'broken avatar'))) as fallback:
            self.assertEqual(fallback.size,(1200,450))

    async def test_only_members_intent_added_without_message_content_or_presence(self):
        client = LoungeBot()
        try:
            self.assertTrue(client.intents.members)
            self.assertFalse(client.intents.message_content)
            self.assertFalse(client.intents.presences)
        finally:
            await client.close()


class TemplatesTest(unittest.TestCase):
    def test_embeds_fit_discord_limits(self):
        templates = template_embeds()
        self.assertEqual(set(templates), set(CHANNELS))
        self.assertEqual(len(templates), 24)
        self.assertEqual([e.colour.value for e in templates.values()], [0x00BFFF, 0xFF2D95] * 12)
        for chat, group in (("fortnite-chat", "fortnite-looking-for-group"),
                            ("minecraft-chat", "minecraft-builds-and-lfg"),
                            ("rocket-league-chat", "rocket-league-looking-for-team"),
                            ("roblox-chat", "roblox-games-and-lfg"), ("memes-and-clips", "media")):
            self.assertIn(f"<#{CHANNELS[group]}>", templates[chat].description)
        for embed in templates.values():
            self.assertLessEqual(len(embed), 6000)
            self.assertLessEqual(len(embed.title), 256)
            self.assertLessEqual(len(embed.description), 4096)
            self.assertLessEqual(len(embed.fields), 25)
            for field in embed.fields:
                self.assertLessEqual(len(field.name), 256)
                self.assertLessEqual(len(field.value), 1024)
            self.assertEqual(discord.Embed.from_dict(embed.to_dict()).to_dict(), embed.to_dict())

    def test_permission_and_guild_checks(self):
        def interaction(guild_id, manage):
            return SimpleNamespace(guild_id=guild_id, permissions=SimpleNamespace(manage_guild=manage))
        self.assertTrue(is_manager(interaction(GUILD_ID, True)))
        self.assertFalse(is_manager(interaction(GUILD_ID, False)))
        self.assertFalse(is_manager(interaction(123, True)))
        self.assertFalse(is_manager(interaction(None, True)))

    def test_custom_embed_validation(self):
        self.assertEqual(announcement_embed("Title", "Body", "#5865F2").colour.value, 0x5865F2)
        for title, body, colour in [("", "Body", "5865F2"), ("T"*257, "B", "5865F2"),
                                    ("T", "B"*4001, "5865F2"), ("T", "B", "red")]:
            with self.assertRaises(ValueError):
                announcement_embed(title, body, colour)


class FakeChannel:
    def __init__(self, messages=(), fail=False):
        self.messages = list(messages)
        self.fail = fail
        self.send = AsyncMock(side_effect=self.add_message)

    async def add_message(self, *, embed, allowed_mentions):
        message = SimpleNamespace(author=SimpleNamespace(id=7), embeds=[embed], edit=AsyncMock())
        self.messages.append(message)
        return message

    async def history(self, *, limit):
        if self.fail:
            raise RuntimeError("simulated history failure")
        for message in reversed(self.messages):
            yield message


class PublishingTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_shot_disconnects_after_publishing(self):
        client = SimpleNamespace(user="Global Gaming", initial_setup_attempted=False,
                                 publish_templates=AsyncMock(return_value="published"), close=AsyncMock())
        with patch.dict("os.environ", {"PUBLISH_ONCE": "true", "AUTO_SETUP": "false"}):
            await LoungeBot.on_ready(client)
            await LoungeBot.on_ready(client)
        client.publish_templates.assert_awaited_once()
        client.close.assert_awaited_once()

    async def test_wrong_application_cannot_sync_commands(self):
        client = SimpleNamespace(user=SimpleNamespace(id=1), tree=SimpleNamespace(sync=AsyncMock()))
        with self.assertRaises(ValueError):
            await LoungeBot.setup_hook(client)
        client.tree.sync.assert_not_awaited()

    async def test_second_run_updates_instead_of_duplicates(self):
        channel = FakeChannel()
        embed = template_embeds()["welcome"]
        self.assertEqual(await upsert_embed(channel, 7, embed), "created")
        self.assertEqual(await upsert_embed(channel, 7, embed), "updated")
        channel.send.assert_awaited_once()
        channel.messages[0].edit.assert_awaited_once()
        self.assertFalse(channel.send.call_args.kwargs["allowed_mentions"].everyone)

    async def test_never_edits_human_or_unrelated_messages(self):
        embed = template_embeds()["rules"]
        human = SimpleNamespace(author=SimpleNamespace(id=99), embeds=[embed], edit=AsyncMock())
        other = SimpleNamespace(author=SimpleNamespace(id=7), embeds=[discord.Embed(title="Other")], edit=AsyncMock())
        channel = FakeChannel([human, other])
        self.assertEqual(await upsert_embed(channel, 7, embed), "created")
        human.edit.assert_not_awaited()
        other.edit.assert_not_awaited()

    async def test_failed_history_read_does_not_post_duplicate(self):
        channel = FakeChannel(fail=True)
        with self.assertRaises(RuntimeError):
            await upsert_embed(channel, 7, template_embeds()["welcome"])
        channel.send.assert_not_awaited()

    async def test_preview_rechecks_author_and_permissions(self):
        view = PublishPreview(42, template_embeds()["welcome"])
        interaction = SimpleNamespace(user=SimpleNamespace(id=43), guild_id=GUILD_ID,
                                      permissions=SimpleNamespace(manage_guild=True),
                                      response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await view.interaction_check(interaction))
        interaction.user.id = 42
        interaction.permissions.manage_guild = False
        self.assertFalse(await view.interaction_check(interaction))
        interaction.permissions.manage_guild = True
        self.assertTrue(await view.interaction_check(interaction))
        view.stop()


class PlayerPassTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/"community.sqlite3"
        self.store = Store(self.path)
        self.member = SimpleNamespace(id=17, bot=False, display_name="Very Long Player 名",
            roles=[SimpleNamespace(name=s) for s in ("🎮 Fortnite","🖥️ PC","🇳🇱 Netherlands","🛡️ Moderator")])
        self.channel = SimpleNamespace(id=CHANNELS["general"],send=AsyncMock())
        perms = SimpleNamespace(view_channel=True,send_messages=True,attach_files=True)
        self.i = SimpleNamespace(user=self.member,guild_id=GUILD_ID,channel_id=self.channel.id,channel=self.channel,
            permissions=perms,app_permissions=perms,response=SimpleNamespace(send_message=AsyncMock(),defer=AsyncMock()),
            edit_original_response=AsyncMock())

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_opt_in_limits_duplicate_restart_day_boundary_and_pause(self):
        clock = 86400*5
        self.assertFalse(self.store.award_chat_xp(17,clock))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM gamer_profiles").fetchone()[0],0)
        self.store.profile_preference(17,tracking=True)
        for n in range(10):
            self.assertTrue(self.store.award_chat_xp(17,clock+n*180))
            self.assertFalse(self.store.award_chat_xp(17,clock+n*180+179))
        self.store.close()
        self.store = Store(self.path)
        self.assertFalse(self.store.award_chat_xp(17,clock+3600))
        sheet = player_sheet(self.member,self.store.profile(17))
        self.assertEqual((sheet["xp"],sheet["details"]["Badges"]),(100,["First Level-Up"]))
        self.assertTrue(self.store.award_chat_xp(17,clock+86400))
        self.assertFalse(self.store.award_chat_xp(17,clock))
        self.store.profile_preference(17,tracking=False)
        self.assertFalse(self.store.award_chat_xp(17,clock+86400*2))
        self.assertEqual(self.store.profile(17)["xp"],110)

    async def test_only_social_human_messages_count_without_inspecting_content(self):
        msg = SimpleNamespace(guild=SimpleNamespace(id=GUILD_ID),channel=self.channel,
                              author=self.member,type=discord.MessageType.reply,webhook_id=None)
        self.assertTrue(eligible_chat(msg))
        for key,bad in (("guild",None),("guild",SimpleNamespace(id=8)),("webhook_id",42),
                        ("author",SimpleNamespace(bot=True)),("channel",SimpleNamespace(id=5)),
                        ("type",discord.MessageType.premium_guild_subscription)):
            old = getattr(msg,key)
            setattr(msg,key,bad)
            self.assertFalse(eligible_chat(msg))
            setattr(msg,key,old)

    async def test_hidden_fields_excluded_from_card_alt_and_avatar_fetch(self):
        p=ProfilePanel(self.store,17,self.channel.id)
        self.store.profile_preference(17,fields=6)
        await p.draw(self.member)  # No display_avatar provided: hidden avatar must never be fetched.
        self.assertEqual(p.sheet["details"],{"Games":["Fortnite"],"Devices":["PC"]})
        self.assertIsNone(p.sheet["xp"])
        with Image.open(io.BytesIO(p.raw)) as im:
            self.assertEqual(im.size,(1000,416))
        self.store.profile_preference(17,fields=0)
        await p.draw(self.member)
        f=pass_file(p.raw,p.sheet)
        try:
            self.assertEqual(f.description,"Global Gaming player pass: Very Long Player 名")
        finally:
            f.close()
        p.stop()

    async def test_private_by_default_shared_once_and_only_by_owner(self):
        self.store.profile_preference(17,fields=0)
        with patch("bot.bot.community", SimpleNamespace(store=self.store)):
            await profile.callback(self.i)
        self.i.response.defer.assert_awaited_once_with(ephemeral=True,thinking=True)
        self.channel.send.assert_not_awaited()
        p=self.i.edit_original_response.await_args.kwargs["view"]
        self.assertTrue(await p.interaction_check(self.i))
        other=SimpleNamespace(**{**vars(self.i),"user":SimpleNamespace(id=18)})
        self.assertFalse(await p.interaction_check(other))
        self.store.profile_preference(17,fields=2)
        await p.share.callback(self.i)
        self.channel.send.assert_not_awaited()
        await p.refresh(self.i)
        self.i.permissions.attach_files=False
        await p.share.callback(self.i)
        self.channel.send.assert_not_awaited()
        self.i.permissions.attach_files=True
        await p.share.callback(self.i)
        await p.share.callback(self.i)
        self.channel.send.assert_awaited_once()
        p.stop()


class MemberBadgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from bot import MEMBER_ROLE_ID
        self.guild = SimpleNamespace(id=GUILD_ID, unavailable=False, channels=[],
            me=SimpleNamespace(guild_permissions=discord.Permissions(manage_roles=True)))
        self.role = SimpleNamespace(id=MEMBER_ROLE_ID, guild=self.guild, is_assignable=lambda: True,
                                    permissions=discord.Permissions.none())
        self.guild.get_role = lambda key: self.role if key == MEMBER_ROLE_ID else None
        self.member = SimpleNamespace(guild=self.guild, roles=[], bot=False, pending=False, add_roles=AsyncMock())
        self.client = SimpleNamespace(member_badge=LoungeBot.member_badge, give_member_badge=LoungeBot.give_member_badge,
            wait_until_ready=AsyncMock(), get_guild=lambda key: self.guild, member_role_lock=asyncio.Lock())
        self.client.give_join_badge = LoungeBot.give_join_badge.__get__(self.client)
        self.client.check_member_roles = LoungeBot.check_member_roles.__get__(self.client)

    async def test_join_screening_and_repeated_checks(self):
        self.member.pending = True
        await self.client.give_join_badge(self.member)
        self.member.add_roles.assert_not_awaited()
        self.member.pending = False
        await LoungeBot.on_member_update(self.client, SimpleNamespace(pending=True), self.member)
        self.member.add_roles.assert_awaited_once_with(self.role, reason="Global Gaming membership", atomic=True)
        self.member.roles.append(self.role)
        await self.client.give_join_badge(self.member)
        self.member.add_roles.assert_awaited_once()

    async def test_backfill_handles_offline_joins_and_skips_bots(self):
        robot = SimpleNamespace(bot=True, add_roles=AsyncMock())
        async def members(limit):
            self.assertIsNone(limit)
            for member in (robot, self.member):
                yield member
        self.guild.fetch_members = members
        await LoungeBot.sync_member_roles.coro(self.client)
        self.member.add_roles.assert_awaited_once()
        robot.add_roles.assert_not_awaited()
        self.assertIn("Assigned 1; already Member 0", self.client.member_role_status)

    async def test_gateway_delivers_screening_completion_after_join(self):
        # Exercise discord.py's actual event parser: the old empty cache silently
        # discarded this update, even though direct callback tests passed.
        client = LoungeBot()
        state = client._connection
        guild = discord.Guild(data={"id": str(GUILD_ID), "name": "Global Gaming"}, state=state)
        state._add_guild(guild)
        events = []
        state.dispatch = lambda name, *args: events.append((name, args))
        user = {"id": "42", "username": "test", "discriminator": "0", "avatar": None}
        state.parse_guild_member_add({"guild_id": str(GUILD_ID), "user": user, "roles": [],
                                     "joined_at": "2026-11-09T00:00:00+00:00", "pending": True, "flags": 0})
        state.parse_guild_member_update({"guild_id": str(GUILD_ID), "user": user,
                                        "roles": [], "pending": False, "flags": 0})
        updates = [args for name, args in events if name == "member_update"]
        self.assertEqual(len(updates), 1)
        before, after = updates[0]
        self.assertTrue(before.pending)
        self.assertFalse(after.pending)
        client.give_join_badge = AsyncMock()
        await client.on_member_update(before, after)
        client.give_join_badge.assert_awaited_once_with(after)

    async def test_pending_members_are_not_granted_a_role_by_backfill(self):
        self.member.pending = True
        async def members(limit):
            yield self.member
        self.guild.fetch_members = members
        await self.client.check_member_roles(self.guild)
        self.member.add_roles.assert_not_awaited()
        self.assertIn("awaiting screening 1", self.client.member_role_status)

    async def test_forbidden_member_does_not_block_next_member(self):
        other = SimpleNamespace(bot=False, pending=False, roles=[], add_roles=AsyncMock())
        self.member.add_roles.side_effect = discord.Forbidden(
            SimpleNamespace(status=403, reason="Forbidden"), {"code": 50013, "message": "Missing Permissions"})
        async def members(limit):
            yield self.member
            yield other
        self.guild.fetch_members = members
        await self.client.check_member_roles(self.guild)
        other.add_roles.assert_awaited_once()
        self.assertIn("Assigned 1", self.client.member_role_status)
        self.assertIn("Discord refused 1", self.client.member_role_status)

    async def test_failure_diagnostic_and_recovery(self):
        self.role.is_assignable = lambda: False
        async def members(limit):
            yield self.member
        self.guild.fetch_members = members
        await self.client.check_member_roles(self.guild)
        self.assertIn("above Member", self.client.member_role_status)
        self.member.add_roles.assert_not_awaited()
        self.role.is_assignable = lambda: True
        await self.client.check_member_roles(self.guild)
        self.member.add_roles.assert_awaited_once()
        self.assertIn("Assigned 1", self.client.member_role_status)

    async def test_member_badge_cannot_grant_extra_access(self):
        self.role.permissions = discord.Permissions(manage_messages=True)
        with self.assertRaises(ValueError):
            LoungeBot.member_badge(self.guild)
        self.role.permissions = discord.Permissions.none()
        self.guild.channels.append(SimpleNamespace(id=123, overwrites_for=lambda role: discord.PermissionOverwrite(view_channel=True)))
        with self.assertRaises(ValueError):
            LoungeBot.member_badge(self.guild)


class PromotionAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_target_bots_blocked_outside_private_channel_and_read_back(self):
        from unittest.mock import Mock
        from bot import BUMP_NAME, enforce_promotion_channels
        from bot import DIRECTORY_APPS
        role = Mock(name="promotion-role", managed=False, tags=None)
        role.name = "Promotion Bots"
        everyone, me = Mock(), Mock(id=99)
        member = Mock(id=10, bot=True, roles=[role], guild_permissions=discord.Permissions.none())
        async def fetch_member(bot_id):
            return member if bot_id == DIRECTORY_APPS[0] else SimpleNamespace(bot=True, roles=[])
        guild = SimpleNamespace(id=GUILD_ID, me=me, default_role=everyone, roles=[role], fetch_member=fetch_member,
                                role_member_counts=AsyncMock(return_value={role: 1}))
        bump = Mock(spec=discord.TextChannel, id=42, category_id=None)
        bump.name = BUMP_NAME
        bump.overwrites_for.side_effect = lambda target: discord.PermissionOverwrite(view_channel=target is role)
        bump.permissions_for.return_value = discord.Permissions(view_channel=True, send_messages=True)
        general = Mock(spec=discord.TextChannel, id=43, category_id=None)
        permissions = {role: discord.PermissionOverwrite(create_instant_invite=True),
                       member: discord.PermissionOverwrite(send_messages=True, view_channel=True)}
        general.overwrites_for.side_effect = lambda target: discord.PermissionOverwrite.from_pair(*permissions[target].pair())
        def access(target):
            if target is me:
                return discord.Permissions(manage_roles=True, view_channel=True)
            return discord.Permissions(view_channel=True, send_messages=permissions[member].send_messages is not False,
                send_messages_in_threads=permissions[role].send_messages_in_threads is not False)
        general.permissions_for.side_effect = access
        async def change(target, *, overwrite, reason):
            permissions[target] = overwrite
        general.set_permissions = AsyncMock(side_effect=change)
        guild.fetch_channels = AsyncMock(return_value=[bump, general])
        result = await enforce_promotion_channels(guild)
        self.assertIn("still post: 0", result)
        self.assertEqual([call.args[0] for call in general.set_permissions.await_args_list], [role, member])
        bump.set_permissions.assert_not_called()
        self.assertTrue(permissions[role].create_instant_invite)
        self.assertTrue(permissions[member].view_channel)
        await enforce_promotion_channels(guild)
        self.assertEqual(general.set_permissions.await_count, 2)
        guild.role_member_counts.return_value = {role: 2}
        with self.assertRaisesRegex(ValueError, "unverified members"):
            await enforce_promotion_channels(guild)
        self.assertEqual(general.set_permissions.await_count, 2)


if __name__ == "__main__":
    unittest.main()
