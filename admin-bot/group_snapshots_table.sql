-- Create table to track historical WOM group data snapshots
-- Run this in Supabase SQL Editor

CREATE TABLE public.group_snapshots (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  snapshot_data jsonb NOT NULL,
  timestamp timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT group_snapshots_pkey PRIMARY KEY (id)
);

-- Create index on timestamp for efficient querying
CREATE INDEX idx_group_snapshots_timestamp ON public.group_snapshots(timestamp DESC);

-- Add comment for documentation
COMMENT ON TABLE public.group_snapshots IS 'Stores historical snapshots of WOM group data for tracking and debugging';
COMMENT ON COLUMN public.group_snapshots.snapshot_data IS 'Complete JSON response from WOM API group endpoint';
COMMENT ON COLUMN public.group_snapshots.timestamp IS 'When this snapshot was captured';
