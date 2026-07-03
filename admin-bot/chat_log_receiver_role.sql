-- Create a dedicated Postgres role for the chat-log-receiver service.
-- Run this in Supabase SQL Editor BEFORE chat_log_entries_table.sql (which grants this role
-- access via a Row Level Security policy).
--
-- Supabase's default `postgres` connection role has BYPASSRLS, so RLS policies are a no-op
-- against it. This role deliberately does NOT have BYPASSRLS, so the policy on
-- chat_log_entries actually applies. Supabase's dashboard only shows a connection string for
-- the built-in `postgres` user, so the connection string for this role must be assembled
-- manually: replace the user in the pooler connection string Supabase shows you with
-- `chat_log_receiver` and this password.
--
-- Set a strong password before running -- this is a placeholder.
CREATE ROLE chat_log_receiver WITH LOGIN PASSWORD 'CHANGE_ME' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;

GRANT USAGE ON SCHEMA public TO chat_log_receiver;
GRANT SELECT, INSERT ON public.chat_log_entries TO chat_log_receiver;

-- Needed for member resolution (sender -> member_id lookup on insert); read-only.
GRANT SELECT ON public.member_rsns TO chat_log_receiver;
GRANT SELECT ON public.members TO chat_log_receiver;
GRANT SELECT ON public.ranks TO chat_log_receiver;
