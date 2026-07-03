-- Records each run of chat-log-receiver's daily dedup sweep (see chat-log-receiver/db.py
-- sweep_duplicates), so removed-duplicate counts are visible without digging through Railway logs.
-- Run this in Supabase SQL Editor.

CREATE TABLE public.dedup_sweep_runs (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  ran_at timestamp with time zone NOT NULL DEFAULT now(),
  rows_deleted integer NOT NULL,
  CONSTRAINT dedup_sweep_runs_pkey PRIMARY KEY (id)
);

COMMENT ON TABLE public.dedup_sweep_runs IS 'One row per run of the chat-log-receiver dedup sweep, recording how many duplicate chat_log_entries rows it removed.';

ALTER TABLE public.dedup_sweep_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY chat_log_receiver_service_access ON public.dedup_sweep_runs
  FOR ALL
  TO chat_log_receiver
  USING (true)
  WITH CHECK (true);

-- The RLS policy above only governs which rows are visible/writable -- it does not substitute
-- for command-level privileges, which must be granted separately.
GRANT SELECT, INSERT ON public.dedup_sweep_runs TO chat_log_receiver;
