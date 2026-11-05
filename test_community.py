import asyncio
import tempfile
import unittest
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from community import CommunityFeatures, CreatorControls, CREATOR_PLATFORMS, CreatorDesk, creator_application_input, creator_embed, GiveawayEntry, GiveawayPreview, TicketControls, TicketPanel, giveaway_embed, ticket_overwrites
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
        everyone,staff,owner=object(),object(),object()
        bot=Mock(guild_permissions=discord.Permissions.all())
        guild=SimpleNamespace(default_role=everyone)
        perms=ticket_overwrites(guild,staff,bot,owner)
        self.assertEqual(set(perms),{everyone,staff,bot,owner})
        self.assertFalse(perms[everyone].view_channel)
        self.assertTrue(perms[owner].send_messages)
        self.assertFalse(perms[owner].create_private_threads)
        self.assertIsNone(perms[owner].manage_roles)
        # Discord only permits administrators to set MANAGE_ROLES overwrites at creation.
        # The bot inherits its approved guild permission instead.
        self.assertIsNone(perms[bot].manage_roles)
        closed=ticket_overwrites(guild,staff,bot,owner,closed=True)
        self.assertTrue(closed[owner].view_channel)
        self.assertFalse(closed[owner].send_messages)

    def test_ticket_creation_does_not_set_permissions_bot_lacks(self):
        everyone,staff,owner=object(),object(),object()
        bot=Mock(guild_permissions=discord.Permissions(view_channel=True,send_messages=True,read_message_history=True,embed_links=True,manage_channels=True,manage_roles=True))
        acl=ticket_overwrites(SimpleNamespace(default_role=everyone),staff,bot,owner)
        for overwrite in acl.values():
            allow,deny=overwrite.pair()
            self.assertEqual((allow.value|deny.value)&~bot.guild_permissions.value,0)

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
        for view in (TicketPanel(self.f),TicketControls(self.f),GiveawayEntry(self.f),CreatorControls(self.f.creators)):
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


class CreatorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'creator.sqlite3')
        self.desk=CreatorDesk(SimpleNamespace(guild_id=45,store=self.store))
        self.row=self.store.new_creator(23,'Twitch','CreW_23',1250)
        self.store.creator_location(self.row['id'],256,257)
        self.member=SimpleNamespace(add_roles=AsyncMock())
        self.guild=SimpleNamespace(owner_id=100,fetch_member=AsyncMock(return_value=self.member))
        self.i=SimpleNamespace(user=SimpleNamespace(id=100),guild=self.guild,guild_id=45,channel_id=256,
                               channel=SimpleNamespace(id=256),message=SimpleNamespace(id=257),
                               response=SimpleNamespace(send_message=AsyncMock()))
        self.desk.roles=Mock(return_value=['platform-role','group-role'])
        self.desk.put_card=AsyncMock()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def accept(self):
        return await self.desk.approve(self.i,self.row['id'],self.row['keyword'])

    async def test_only_server_owner_in_original_channel_can_grant(self):
        self.i.user.id=23
        with self.assertRaises(ValueError): await self.accept()
        await self.desk.action(self.i,'review')
        self.i.response.send_message.assert_awaited_once()
        self.i.user.id=100
        self.i.channel_id=1
        with self.assertRaises(ValueError): await self.accept()
        self.member.add_roles.assert_not_awaited()

    async def test_new_or_expired_word_cannot_be_used_for_approval(self):
        self.store.db.execute('UPDATE creator_requests SET expires=?',(int(time.time())-1,))
        with self.assertRaisesRegex(ValueError,'expired'): await self.accept()
        self.store.renew_creator(self.row['id'])
        with self.assertRaisesRegex(ValueError,'stale'): await self.accept()
        self.member.add_roles.assert_not_awaited()

    async def test_verified_request_survives_partial_failure_and_blocks_second_claim(self):
        self.member.add_roles.side_effect=OSError('interrupted')
        with self.assertRaises(OSError): await self.accept()
        self.assertEqual(self.store.creator_request(self.row['id'])['state'],'approving')
        self.member.add_roles.side_effect=None
        await self.accept()
        self.assertEqual(self.store.creator_request(self.row['id'])['state'],'approved')
        await self.accept()
        self.assertEqual(self.member.add_roles.await_count,2)
        other=self.store.new_creator(24,'Twitch','CREW_23',300)
        self.store.creator_location(other['id'],300,301)
        self.i.channel_id=300
        with self.assertRaisesRegex(ValueError,'already attached'):
            await self.desk.approve(self.i,other['id'],other['keyword'])
        self.assertEqual(self.member.add_roles.await_count,2)

    async def test_creator_acl_and_platform_input(self):
        bot=Mock(guild_permissions=discord.Permissions.all())
        everyone,applicant=object(),object()
        acl=ticket_overwrites(SimpleNamespace(default_role=everyone),None,bot,applicant)
        self.assertEqual(set(acl),{everyone,bot,applicant})
        self.assertFalse(acl[everyone].view_channel)
        self.assertEqual(creator_application_input(' @CreW_23 ','0001250'),('CreW_23',1250))
        for handle,count in [('https://not-a-profile','5'),('abc','1.1k'),('@everyone here','100')]:
            with self.assertRaises(ValueError): creator_application_input(handle,count)
        card=creator_embed(self.row,100)
        fields=' '.join(f.value for f in card.fields)
        self.assertIn('https://www.twitch.tv/CreW_23',fields)
        self.assertIn(self.row['keyword'],fields)

    async def test_creator_application_reuses_ticket_and_preserves_claimed_account(self):
        desk=self.desk
        user=Mock(id=29,bot=False,roles=[])
        everyone=Mock(id=45)
        me=Mock(id=61,guild_permissions=discord.Permissions.all())
        channel=Mock(id=259,mention='<#259>')
        guild=SimpleNamespace(owner_id=100,me=me,default_role=everyone,fetch_channels=AsyncMock(return_value=[]),
                             create_text_channel=AsyncMock(return_value=channel))
        i=SimpleNamespace(guild_id=45,channel_id=1567624646944235632,user=user,guild=guild)
        desk.f.ticket_category=AsyncMock(return_value=object())
        desk.f.channel=AsyncMock(return_value=channel)
        await desk.apply(i,'TikTok','actual_account',20)
        await desk.apply(i,'Instagram','different',500)
        self.assertEqual(guild.create_text_channel.await_count,1)
        self.assertEqual(set(guild.create_text_channel.await_args.kwargs['overwrites']),{everyone,me,user})
        saved=self.store.pending_creator(29)
        self.assertEqual((saved['platform'],saved['handle'],saved['followers'],saved['channel']),
                         ('TikTok','actual_account',20,259))

    async def test_rejects_unassignable_privileged_or_replaced_roles(self):
        def fake(rid,name,hoist):
            role=Mock(managed=False,mentionable=False,hoist=hoist,permissions=discord.Permissions.none())
            role.id,role.name=rid,name
            role.is_default.return_value=False
            role.is_assignable.return_value=True
            return role
        platform=fake(4,CREATOR_PLATFORMS['Twitch'][0],False)
        group=fake(5,'🎬 Content Creators',True)
        guild=SimpleNamespace(roles=[platform,group],channels=[])
        resolve=CreatorDesk.roles
        self.assertEqual(resolve(self.desk,guild,'Twitch'),[platform,group])
        group.permissions=discord.Permissions(manage_messages=True)
        with self.assertRaises(ValueError): resolve(self.desk,guild,'Twitch')
        group.permissions=discord.Permissions.none()
        group.id=6
        with self.assertRaises(ValueError): resolve(self.desk,guild,'Twitch')


if __name__=='__main__':
    unittest.main()
