-- Fixes chat_log_entries dedup: client_message_id and message_timestamp are generated
-- independently by each staff client (client_message_id is RuneLite's local per-client
-- message counter, not a server-assigned id), so different clients witnessing the same
-- real chat message never agree on either value and the old unique constraint never caught
-- cross-client duplicates. Dedup now happens app-side in chat-log-receiver/db.py, matching
-- on (chat_name, sender, message) within a short window of message_timestamp.
-- Run this once in the Supabase SQL Editor after deploying the updated chat-log-receiver.

ALTER TABLE public.chat_log_entries DROP CONSTRAINT IF EXISTS chat_log_entries_dedup;

CREATE INDEX IF NOT EXISTS idx_chat_log_entries_dedup_lookup
  ON public.chat_log_entries(chat_name, sender, message, message_timestamp);

COMMENT ON COLUMN public.chat_log_entries.client_message_id IS 'The id field from the plugin payload -- RuneLite''s local per-client message counter, not a server-assigned id. Not usable for dedup: different clients witnessing the same real chat message generate unrelated values for it. See chat-log-receiver/db.py for the actual dedup logic (content + timestamp window).';

-- One-off backfill: remove existing duplicate rows accumulated under the old (broken) dedup,
-- keeping the earliest id in each (chat_name, sender, message) cluster whose message_timestamps
-- fall within a 2-second bucket of each other.
DELETE FROM public.chat_log_entries
WHERE id IN (
  SELECT id FROM (
    SELECT id,
      row_number() OVER (
        PARTITION BY chat_name, sender, message,
          date_bin('2 seconds', message_timestamp, TIMESTAMPTZ '2000-01-01')
        ORDER BY id
      ) AS rn
    FROM public.chat_log_entries
  ) ranked
  WHERE rn > 1
);
