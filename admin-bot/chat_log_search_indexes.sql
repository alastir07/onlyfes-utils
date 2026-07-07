-- Supports phase 2 (staff search UI) plain/regex text search over chat_log_entries.message.
-- A plain btree index doesn't help substring/regex search; trigram indexing does.
-- Run this in Supabase SQL Editor.

CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA extensions;

CREATE INDEX idx_chat_log_entries_message_trgm ON public.chat_log_entries USING gin (message gin_trgm_ops);
