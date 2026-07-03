-- Create table to store clan chat messages submitted remotely by staff via the
-- chat-logger RuneLite plugin, collected by the chat-log-receiver service.
-- Run this in Supabase SQL Editor.

CREATE TABLE public.chat_log_entries (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  client_message_id bigint NOT NULL,
  chat_name character varying NOT NULL,
  chat_type character varying NOT NULL,
  sender character varying NOT NULL,
  rank integer NOT NULL,
  message text NOT NULL,
  message_timestamp timestamp with time zone NOT NULL,
  received_at timestamp with time zone NOT NULL DEFAULT now(),
  submitted_by character varying,
  member_id uuid,
  CONSTRAINT chat_log_entries_pkey PRIMARY KEY (id),
  CONSTRAINT chat_log_entries_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(id),
  CONSTRAINT chat_log_entries_dedup UNIQUE (chat_name, client_message_id, sender, message_timestamp)
);

CREATE INDEX idx_chat_log_entries_message_timestamp ON public.chat_log_entries(message_timestamp DESC);
CREATE INDEX idx_chat_log_entries_member_id ON public.chat_log_entries(member_id);
CREATE INDEX idx_chat_log_entries_sender ON public.chat_log_entries(sender);

COMMENT ON TABLE public.chat_log_entries IS 'Clan/friends chat messages submitted remotely by the chat-logger RuneLite plugin, collected by chat-log-receiver for staff moderation review.';
COMMENT ON COLUMN public.chat_log_entries.client_message_id IS 'The id field from the plugin payload. Not globally unique on its own (multiple clients may submit the same logical message) -- see chat_log_entries_dedup.';
COMMENT ON COLUMN public.chat_log_entries.chat_type IS 'Plugin currently always sends CLAN due to a client-side bug; use chat_name to distinguish channels instead.';
COMMENT ON COLUMN public.chat_log_entries.message_timestamp IS 'UTC timestamp captured client-side by the plugin when the message was received.';
COMMENT ON COLUMN public.chat_log_entries.received_at IS 'Server receipt time, for debugging submission lag/gaps.';
COMMENT ON COLUMN public.chat_log_entries.member_id IS 'Resolved by normalizing sender and matching against member_rsns (current or past RSNs). Null if no match found.';

-- Row Level Security
-- First table in this project to enable RLS (no existing precedent elsewhere; other tables are out of scope).
--
-- Supabase's default `postgres` connection role has BYPASSRLS, so RLS would be a no-op against it.
-- chat-log-receiver instead connects using a dedicated non-bypass role (see chat_log_receiver_role.sql)
-- created specifically so this policy has teeth. The policy is intentionally permissive (single trusted
-- backend service, no per-row tenancy) -- RLS here exists to satisfy Supabase's advisor and to ensure that
-- if this table's credentials ever leaked to a lower-trust context (e.g. queried via PostgREST/anon key),
-- access would be denied by default rather than open, since no anon/authenticated policy is defined.
ALTER TABLE public.chat_log_entries ENABLE ROW LEVEL SECURITY;

CREATE POLICY chat_log_receiver_service_access ON public.chat_log_entries
  FOR ALL
  TO chat_log_receiver
  USING (true)
  WITH CHECK (true);
