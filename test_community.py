import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from community import CommunityFeatures, GiveawayEntry, GiveawayPreview, TicketControls, TicketPanel, giveaway_embed, ticket_overwrites
from storage import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'data.sqlite3'
        self.s=Store(self.path)

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def giveaway(self):
        gid=self.s.create_giveaway(1,2,'A real prize','Free entry.',2,100)
        self.s.activate(gid,20)
        return gid

    def test_entries_unique_toggle_and_deadline(self):
        gid=self.giveaway()
        self.assertEqual(self.s.toggle_entry(gid,7,now=99),'entered')
        self.assertEqual(self.s.toggle_entry(gid,7,now=99),'left')
        self.assertEqual(self.s.toggle_entry(gid,7,now=99),'entered')
        self.assertEqual(self.s.toggle_entry(gid,7,now=100),'closed')
        self.assertEqual(self.s.entries(gid),[7])

    def test_draw_persisted_across_restart_and_retry(self):
        gid=self.giveaway()
        for uid in range(20):
            self.s.toggle_entry(gid,uid,now=90)
        first=self.s.finish(gid,now=100)
        import json
        winners=json.loads(first['winners'])
        self.assertEqual(len(set(winners)),2)
        self.s.close()
        self.s=Store(self.path)
        self.assertEqual(self.s.finish(gid,now=110)['winners'],first['winners'])
        self.assertEqual(self.s.toggle_entry(gid,99,now=110),'closed')
        self.assertEqual(self.s.giveaway(gid)['published'],0)
        self.s.published(gid)
        self.assertEqual(self.s.giveaway(gid)['published'],1)

    def test_cannot_end_early_and_cancel_never_draws(self):
        gid=self.giveaway()
        self.s.toggle_entry(gid,3,now=90)
        with self.assertRaises(ValueError):
            self.s.finish(gid,now=99)
        self.assertEqual(self.s.finish(gid,cancel=True)['winners'],'[]')
        self.assertEqual(self.s.giveaway(gid)['state'],'cancelled')

    def test_empty_and_undersubscribed_giveaways(self):
        gid=self.giveaway()
        self.assertEqual(self.s.finish(gid,now=100)['winners'],'[]')
        gid=self.s.create_giveaway(1,2,'Prize','Free',10,100)
        self.s.activate(gid,21)
        self.s.toggle_entry(gid,99,now=90)
        self.assertEqual(self.s.finish(gid,now=100)['winners'],'[99]')

    def test_one_open_ticket_and_closed_history_retained(self):
        import sqlite3
        tid=self.s.reserve_ticket(7)
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.reserve_ticket(7)
        self.s.ticket_state(tid,'open',100)
        self.s.ticket_state(tid,'closed')
        self.assertIsNotNone(self.s.ticket(100))
        self.s.reserve_ticket(7)
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.ticket_state(tid,'open')

    def test_boost_event_is_deduplicated(self):
        self.assertTrue(self.s.claim_boost(1))
        self.assertFalse(self.s.claim_boost(1))
        self.s.retry_boost(1)
        self.assertTrue(self.s.claim_boost(1))

    def test_backup_is_readable(self):
        gid=self.giveaway()
        backup=Path(self.tmp.name)/'backup.sqlite3'
        self.s.backup(backup)
        other=Store(backup)
        self.assertEqual(other.giveaway(gid)['message'],20)
        other.close()


class PrivacyTests(unittest.TestCase):
    def test_private_acl_has_only_explicit_participants(self):
        everyone,staff,bot,owner=object(),object(),object(),object()
        guild=SimpleNamespace(default_role=everyone)
        perms=ticket_overwrites(guild,staff,bot,owner)
        self.assertEqual(set(perms),{everyone,staff,bot,owner})
        self.assertFalse(perms[everyone].view_channel)
        self.assertTrue(perms[owner].send_messages)
        self.assertFalse(perms[owner].create_private_threads)
        self.assertIsNone(perms[owner].manage_roles)
        closed=ticket_overwrites(guild,staff,bot,owner,closed=True)
        self.assertTrue(closed[owner].view_channel)
        self.assertFalse(closed[owner].send_messages)

    def test_long_giveaway_fits_embed_and_mentions_escaped(self):
        row=dict(id=1,prize='@everyone '+('*'*190),rules='@here '+('x'*890),ends=123,winners_count=10,state='ended',winners='[12,13]')
        embed=giveaway_embed(row,30)
        self.assertLess(len(embed),6000)
        for field in embed.fields:
            self.assertLessEqual(len(field.value),1024)
        self.assertNotIn('@everyone',embed.description)


class FeatureTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.bot=SimpleNamespace(add_view=Mock(),tree=discord.app_commands.CommandTree(discord.Client(intents=discord.Intents.none())))
        self.f=CommunityFeatures(self.bot,42,self.tmp.name)

    async def asyncTearDown(self):
        await self.f.shutdown()
        self.tmp.cleanup()

    async def test_persistent_buttons_and_commands_register(self):
        for view in (TicketPanel(self.f),TicketControls(self.f),GiveawayEntry(self.f)):
            self.assertTrue(view.is_persistent())
        self.f.register()
        commands=self.bot.tree.get_commands(guild=discord.Object(id=42))
        self.assertEqual({c.name for c in commands},{'setup_community','giveaway','giveaway_cancel','community_help'})
        for command in commands:
            if command.name!='community_help':
                self.assertTrue(command.default_permissions.manage_guild)
                self.assertTrue(command.checks)

    async def test_ticket_recovery_finds_created_channel_after_crash(self):
        tid=self.f.store.reserve_ticket(7)
        channel=SimpleNamespace(id=100,topic=f'gg-ticket:v1:{tid}:7')
        await self.f.recover_tickets(SimpleNamespace(fetch_channels=AsyncMock(return_value=[channel])))
        self.assertEqual(self.f.store.open_ticket(7)['channel'],100)

    async def test_non_owner_cannot_close_or_reopen_ticket(self):
        tid=self.f.store.reserve_ticket(7)
        self.f.store.ticket_state(tid,'open',100)
        role=object()
        self.f.staff_role=lambda guild:role
        interaction=SimpleNamespace(guild_id=42,channel_id=100,guild=object(),user=SimpleNamespace(id=8,roles=[]),permissions=SimpleNamespace(administrator=False),response=SimpleNamespace(send_message=AsyncMock(),defer=AsyncMock()))
        for closed in (True,False):
            await self.f.change_ticket(interaction,closed=closed)
        self.assertEqual(interaction.response.send_message.await_count,2)
        interaction.response.defer.assert_not_awaited()

    async def test_preview_rechecks_author_and_server_permissions(self):
        preview=GiveawayPreview(self.f,7,'Prize',10,1,'Free')
        i=SimpleNamespace(guild_id=42,user=SimpleNamespace(id=7),permissions=SimpleNamespace(manage_guild=False),response=SimpleNamespace(send_message=AsyncMock()))
        self.assertFalse(await preview.interaction_check(i))
        i.permissions.manage_guild=True
        self.assertTrue(await preview.interaction_check(i))
        i.user.id=8
        self.assertFalse(await preview.interaction_check(i))

    async def test_giveaway_network_retry_uses_same_message_and_winners(self):
        gid=self.f.store.create_giveaway(1,7,'Prize','Free',1,100)
        self.f.store.activate(gid,20)
        self.f.store.toggle_entry(gid,7,now=90)
        row=self.f.store.finish(gid,now=100)
        message=SimpleNamespace(author=SimpleNamespace(id=99),edit=AsyncMock())
        channel=SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        self.bot.user=SimpleNamespace(id=99)
        self.f.channel=AsyncMock(return_value=channel)
        await self.f.refresh_giveaway(row)
        await self.f.refresh_giveaway(row)
        self.assertEqual(message.edit.await_count,2)
        self.assertEqual(self.f.store.giveaway(gid)['winners'],'[7]')
        self.assertEqual(self.f.store.giveaway(gid)['published'],1)


if __name__=='__main__':
    unittest.main()
