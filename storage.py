"""Durable metadata only. Ticket text stays in Discord, never in this database."""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tickets(
                id INTEGER PRIMARY KEY, owner INTEGER NOT NULL,
                channel INTEGER UNIQUE, state TEXT NOT NULL, created INTEGER NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS one_open_ticket
                ON tickets(owner) WHERE state IN ('creating','open');
            CREATE TABLE IF NOT EXISTS giveaways(
                id INTEGER PRIMARY KEY, channel INTEGER NOT NULL, message INTEGER UNIQUE,
                host INTEGER NOT NULL, prize TEXT NOT NULL, rules TEXT NOT NULL,
                winners_count INTEGER NOT NULL, ends INTEGER NOT NULL,
                state TEXT NOT NULL DEFAULT 'draft', winners TEXT NOT NULL DEFAULT '[]',
                published INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS entries(
                giveaway INTEGER NOT NULL REFERENCES giveaways(id), user INTEGER NOT NULL,
                PRIMARY KEY(giveaway,user));
            CREATE TABLE IF NOT EXISTS boost_events(id INTEGER PRIMARY KEY, handled INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS welcomes(
                member INTEGER PRIMARY KEY, joined TEXT NOT NULL,
                message INTEGER, created INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS creator_requests(
                id INTEGER PRIMARY KEY, member INTEGER NOT NULL, platform TEXT NOT NULL,
                handle TEXT NOT NULL, normalized TEXT NOT NULL, followers INTEGER NOT NULL,
                keyword TEXT NOT NULL UNIQUE, expires INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                channel INTEGER UNIQUE, message INTEGER, reviewer INTEGER);
            CREATE UNIQUE INDEX IF NOT EXISTS creator_pending ON creator_requests(member)
                WHERE state IN ('pending','approving');
            CREATE UNIQUE INDEX IF NOT EXISTS creator_verified_handle ON creator_requests(platform, normalized)
                WHERE state IN ('approving','approved');
            CREATE TABLE IF NOT EXISTS gamer_profiles(
                member INTEGER PRIMARY KEY, fields INTEGER NOT NULL DEFAULT 31,
                tracking INTEGER NOT NULL DEFAULT 0, xp INTEGER NOT NULL DEFAULT 0,
                last_award INTEGER NOT NULL DEFAULT -86400, day INTEGER NOT NULL DEFAULT -1,
                day_xp INTEGER NOT NULL DEFAULT 0);
        """)

    def profile(self, member: int):
        row = self.db.execute("SELECT fields,tracking,xp FROM gamer_profiles WHERE member=?", (member,)).fetchone()
        return dict(row) if row else dict(fields=31, tracking=0, xp=0)

    def profile_preference(self, member: int, *, fields=None, tracking=None):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO gamer_profiles(member) VALUES(?)", (member,))
            if fields is not None:
                if not 0 <= fields <= 31:
                    raise ValueError("Invalid profile fields")
                self.db.execute("UPDATE gamer_profiles SET fields=? WHERE member=?", (fields, member))
            if tracking is not None:
                self.db.execute("UPDATE gamer_profiles SET tracking=? WHERE member=?", (int(bool(tracking)), member))

    def award_chat_xp(self, member: int, timestamp: int) -> bool:
        # One atomic update: no record is created for someone who never opted in.
        day = timestamp // 86400
        with self.db:
            return self.db.execute("""
                UPDATE gamer_profiles SET xp=xp+10, last_award=?, day=?,
                    day_xp=CASE WHEN day=? THEN day_xp+10 ELSE 10 END
                WHERE member=? AND tracking=1 AND last_award<=?
                    AND (day<>? OR day_xp<100)
            """, (timestamp, day, day, member, timestamp - 180, day)).rowcount == 1

    def close(self):
        self.db.close()

    def creator_request(self, rid):
        return self.db.execute("SELECT * FROM creator_requests WHERE id=?", (rid,)).fetchone()

    def pending_creator(self, member):
        return self.db.execute("SELECT * FROM creator_requests WHERE member=? AND state IN ('pending','approving')", (member,)).fetchone()

    def creator_for_channel(self, channel):
        return self.db.execute("SELECT * FROM creator_requests WHERE channel=?", (channel,)).fetchone()

    @staticmethod
    def creator_challenge():
        return "GG-CREATOR-" + secrets.token_hex(5).upper(), int(time.time()) + 86400

    def new_creator(self, member, platform, handle, followers):
        with self.db:
            rid = self.db.execute("""INSERT INTO creator_requests
                (member,platform,handle,normalized,followers,keyword,expires) VALUES(?,?,?,?,?,?,?)""",
                (member,platform,handle,handle.casefold(),followers,*self.creator_challenge())).lastrowid
        return self.creator_request(rid)

    def creator_location(self, rid, channel, message=None):
        with self.db:
            self.db.execute("UPDATE creator_requests SET channel=?,message=? WHERE id=?", (channel,message,rid))

    def renew_creator(self, rid):
        with self.db:
            self.db.execute("UPDATE creator_requests SET keyword=?,expires=? WHERE id=? AND state='pending'",
                            (*self.creator_challenge(),rid))

    def creator_decision(self, rid, before, after, reviewer):
        with self.db:
            return self.db.execute("UPDATE creator_requests SET state=?,reviewer=? WHERE id=? AND state=?",
                                   (after,reviewer,rid,before)).rowcount == 1

    def get(self, key: str, default=None):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def put(self, key: str, value):
        with self.db:
            self.db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def ticket(self, channel: int):
        return self.db.execute("SELECT * FROM tickets WHERE channel=?", (channel,)).fetchone()

    def open_ticket(self, owner: int):
        return self.db.execute("SELECT * FROM tickets WHERE owner=? AND state IN ('creating','open')", (owner,)).fetchone()

    def reserve_ticket(self, owner: int) -> int:
        with self.db:
            return self.db.execute("INSERT INTO tickets(owner,state,created) VALUES(?,'creating',?)", (owner, int(time.time()))).lastrowid

    def ticket_state(self, ticket: int, state: str, channel=None):
        with self.db:
            self.db.execute("UPDATE tickets SET state=?, channel=COALESCE(?,channel) WHERE id=?", (state, channel, ticket))

    def pending_tickets(self):
        return self.db.execute("SELECT * FROM tickets WHERE state='creating'").fetchall()

    def create_giveaway(self, channel, host, prize, rules, count, ends):
        with self.db:
            return self.db.execute("INSERT INTO giveaways(channel,host,prize,rules,winners_count,ends) VALUES(?,?,?,?,?,?)", (channel,host,prize,rules,count,ends)).lastrowid

    def giveaway(self, giveaway: int):
        return self.db.execute("SELECT * FROM giveaways WHERE id=?", (giveaway,)).fetchone()

    def giveaway_for_message(self, message: int):
        return self.db.execute("SELECT * FROM giveaways WHERE message=?", (message,)).fetchone()

    def activate(self, giveaway: int, message: int):
        with self.db:
            self.db.execute("UPDATE giveaways SET state='open',message=? WHERE id=? AND state='draft'", (message,giveaway))

    def pending_giveaways(self):
        return self.db.execute("SELECT * FROM giveaways WHERE state='draft' OR (state IN ('ended','cancelled') AND published=0) OR (state='open' AND ends<=?)", (int(time.time()),)).fetchall()

    def entries(self, giveaway: int):
        return [r[0] for r in self.db.execute("SELECT user FROM entries WHERE giveaway=? ORDER BY user", (giveaway,))]

    def toggle_entry(self, giveaway: int, user: int, now=None):
        now = int(time.time()) if now is None else now
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.giveaway(giveaway)
            if not row or row['state'] != 'open' or row['ends'] <= now:
                return 'closed'
            if self.db.execute("SELECT 1 FROM entries WHERE giveaway=? AND user=?", (giveaway,user)).fetchone():
                self.db.execute("DELETE FROM entries WHERE giveaway=? AND user=?", (giveaway,user))
                return 'left'
            self.db.execute("INSERT INTO entries VALUES(?,?)", (giveaway,user))
            return 'entered'

    def finish(self, giveaway: int, *, cancel=False, now=None):
        """Persist the single draw BEFORE any network request. Retries reuse it."""
        now = int(time.time()) if now is None else now
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.giveaway(giveaway)
            if not row or row['state'] != 'open':
                return row
            if not cancel and row['ends'] > now:
                raise ValueError('This giveaway has not reached its closing time.')
            entrants = self.entries(giveaway)
            winners = [] if cancel else secrets.SystemRandom().sample(entrants, min(row['winners_count'],len(entrants)))
            self.db.execute("UPDATE giveaways SET state=?,winners=?,published=0 WHERE id=?", ('cancelled' if cancel else 'ended',json.dumps(winners),giveaway))
        return self.giveaway(giveaway)

    def published(self, giveaway: int):
        with self.db:
            self.db.execute("UPDATE giveaways SET published=1 WHERE id=?", (giveaway,))

    def claim_boost(self, message: int) -> bool:
        with self.db:
            cur = self.db.execute("INSERT OR IGNORE INTO boost_events VALUES(?,?)", (message,int(time.time())))
            return cur.rowcount == 1

    def retry_boost(self, message: int):
        with self.db:
            self.db.execute("DELETE FROM boost_events WHERE id=?", (message,))

    def backup(self, path: Path):
        with closing(sqlite3.connect(path)) as dest:
            self.db.backup(dest)

    def has_welcome(self, member: int, joined: str) -> bool:
        return self.db.execute("SELECT 1 FROM welcomes WHERE member=? AND joined=?", (member,joined)).fetchone() is not None

    def claim_welcome(self, member: int, joined: str) -> bool:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.has_welcome(member,joined):
                return False
            self.db.execute("INSERT INTO welcomes VALUES(?,?,NULL,?) ON CONFLICT(member) DO UPDATE SET joined=excluded.joined,message=NULL,created=excluded.created", (member,joined,int(time.time())))
            return True

    def retry_welcome(self, member: int, joined: str):
        with self.db:
            self.db.execute("DELETE FROM welcomes WHERE member=? AND joined=? AND message IS NULL", (member,joined))

    def complete_welcome(self, member: int, joined: str, message: int):
        with self.db:
            self.db.execute("UPDATE welcomes SET message=? WHERE member=? AND joined=?", (message,member,joined))
