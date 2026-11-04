import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from bot import CHANNELS, GUILD_ID, LoungeBot, PublishPreview, announcement_embed, is_manager, template_embeds, upsert_embed


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
