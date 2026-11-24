from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class PostgresRepository:
    """Each service owns its database and uses the same small storage contract."""

    def __init__(self, url, kind, request_url=None):
        self.url = url
        self.request_url = request_url or url
        self.kind = kind

    async def connect(self, *, startup=False):
        return await psycopg.AsyncConnection.connect(
            self.url if startup else self.request_url, connect_timeout=2, row_factory=dict_row
        )

    async def initialize(self):
        async with await self.connect(startup=True) as db:
            await db.execute("""CREATE TABLE IF NOT EXISTS records (
                id uuid PRIMARY KEY, payload jsonb NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )""")
            if self.kind == "user":
                await db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS records_email
                    ON records (lower(payload->>'email'))""")

    @staticmethod
    def record(row):
        return {"id": row["id"], **row["payload"]} if row else None

    async def ready(self):
        async with await self.connect() as db:
            await db.execute("SELECT 1")

    async def create(self, payload):
        async with await self.connect() as db:
            cur = await db.execute("INSERT INTO records(id,payload) VALUES (%s,%s) RETURNING id,payload",
                                   (uuid4(), Jsonb(payload)))
            return self.record(await cur.fetchone())

    async def list(self, limit, offset):
        async with await self.connect() as db:
            cur = await db.execute("SELECT id,payload FROM records ORDER BY created_at,id LIMIT %s OFFSET %s",
                                   (limit, offset))
            return [self.record(row) for row in await cur.fetchall()]

    async def get(self, key):
        async with await self.connect() as db:
            cur = await db.execute("SELECT id,payload FROM records WHERE id=%s", (key,))
            return self.record(await cur.fetchone())

    async def update(self, key, payload):
        async with await self.connect() as db:
            cur = await db.execute("UPDATE records SET payload=%s WHERE id=%s RETURNING id,payload",
                                   (Jsonb(payload), key))
            return self.record(await cur.fetchone())

    async def delete(self, key):
        async with await self.connect() as db:
            cur = await db.execute("DELETE FROM records WHERE id=%s", (key,))
            return cur.rowcount == 1
