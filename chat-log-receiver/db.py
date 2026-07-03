import asyncpg

from config import SUPABASE_DB_URL
from rsn import normalize_string

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(SUPABASE_DB_URL, min_size=1, max_size=5)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def resolve_member_ids(conn: asyncpg.Connection, senders: list[str]) -> dict[str, str]:
    """Maps each distinct normalized sender name to a member_id, via member_rsns (current or past RSNs)."""
    normalized_to_original: dict[str, str] = {}
    for sender in senders:
        normalized_to_original[normalize_string(sender)] = sender

    if not normalized_to_original:
        return {}

    rows = await conn.fetch(
        """
        SELECT member_id, rsn
        FROM public.member_rsns
        WHERE lower(replace(replace(replace(replace(rsn, ' ', ''), '_', ''), '-', ''), '.', ''))
            = ANY($1::text[])
        """,
        list(normalized_to_original.keys()),
    )

    result: dict[str, str] = {}
    for row in rows:
        normalized_rsn = normalize_string(row["rsn"])
        original_sender = normalized_to_original.get(normalized_rsn)
        if original_sender is not None:
            result[original_sender] = str(row["member_id"])
    return result


# client_message_id and message_timestamp are generated independently by each staff client
# (client_message_id is RuneLite's local per-client message counter, not a server-assigned id),
# so different clients witnessing the same real chat message never agree on either value.
# Dedup instead treats two rows as the same message if they share (chat_name, sender, message)
# and their message_timestamp falls within this window of each other.
DEDUP_WINDOW = "2 seconds"


async def _is_duplicate(conn: asyncpg.Connection, chat_name: str, sender: str, message: str, timestamp) -> bool:
    return await conn.fetchval(
        f"""
        SELECT EXISTS (
            SELECT 1 FROM public.chat_log_entries
            WHERE chat_name = $1 AND sender = $2 AND message = $3
                AND message_timestamp BETWEEN $4::timestamptz - interval '{DEDUP_WINDOW}'
                                           AND $4::timestamptz + interval '{DEDUP_WINDOW}'
        )
        """,
        chat_name,
        sender,
        message,
        timestamp,
    )


async def insert_entries(entries: list[dict]) -> int:
    """Bulk inserts chat entries with member resolution and dedup. Returns count of rows actually inserted."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            senders = [e["sender"] for e in entries]
            member_map = await resolve_member_ids(conn, senders)

            inserted = 0
            accepted_in_batch: list[tuple] = []
            for e in entries:
                chat_name, sender, message, timestamp = e["chatName"], e["sender"], e["message"], e["timestamp"]

                if await _is_duplicate(conn, chat_name, sender, message, timestamp):
                    continue
                if any(
                    a_chat_name == chat_name
                    and a_sender == sender
                    and a_message == message
                    and abs((a_timestamp - timestamp).total_seconds()) <= 2
                    for a_chat_name, a_sender, a_message, a_timestamp in accepted_in_batch
                ):
                    continue

                await conn.execute(
                    """
                    INSERT INTO public.chat_log_entries
                        (client_message_id, chat_name, chat_type, sender, rank, message, message_timestamp, member_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    e["id"],
                    chat_name,
                    e["chatType"],
                    sender,
                    e["rank"],
                    message,
                    timestamp,
                    member_map.get(sender),
                )
                accepted_in_batch.append((chat_name, sender, message, timestamp))
                inserted += 1

            return inserted
