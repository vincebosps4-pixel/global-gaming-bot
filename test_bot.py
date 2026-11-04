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
        self.assertEqual(len(templates), 17)
        self.assertEqual([e.colour.value for e in templates.values()], ([0x00BFFF, 0xFF2D95] * 9)[:17])
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


if __name__ == "__main__":
    unittest.main()
