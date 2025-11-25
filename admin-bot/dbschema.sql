-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.clan_bank_transactions (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  transaction_type USER-DEFINED NOT NULL,
  asset_type USER-DEFINED NOT NULL,
  amount bigint NOT NULL,
  gp_value_at_time_m real,
  member_id uuid,
  recorded_by_member_id uuid,
  transaction_date timestamp with time zone NOT NULL,
  notes text,
  CONSTRAINT clan_bank_transactions_pkey PRIMARY KEY (id),
  CONSTRAINT clan_bank_transactions_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(id),
  CONSTRAINT clan_bank_transactions_recorded_by_member_id_fkey FOREIGN KEY (recorded_by_member_id) REFERENCES public.members(id)
);
CREATE TABLE public.group_snapshots (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  snapshot_data jsonb NOT NULL,
  timestamp timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT group_snapshots_pkey PRIMARY KEY (id)
);
CREATE TABLE public.discipline_records (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  member_id uuid NOT NULL,
  discipline_type USER-DEFINED NOT NULL,
  date_issued timestamp with time zone NOT NULL DEFAULT now(),
  expiration_date timestamp with time zone,
  issued_by_member_id uuid,
  reasoning text,
  CONSTRAINT discipline_records_pkey PRIMARY KEY (id),
  CONSTRAINT discipline_records_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(id),
  CONSTRAINT discipline_records_issued_by_member_id_fkey FOREIGN KEY (issued_by_member_id) REFERENCES public.members(id)
);
CREATE TABLE public.event_point_transactions (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  member_id uuid NOT NULL,
  modification integer NOT NULL CHECK (modification <> 0),
  date_enacted timestamp with time zone NOT NULL DEFAULT now(),
  enacted_by_member_id uuid,
  reason character varying,
  CONSTRAINT event_point_transactions_pkey PRIMARY KEY (id),
  CONSTRAINT event_point_transactions_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(id),
  CONSTRAINT event_point_transactions_enacted_by_member_id_fkey FOREIGN KEY (enacted_by_member_id) REFERENCES public.members(id)
);
CREATE TABLE public.member_rsns (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  member_id uuid NOT NULL,
  rsn character varying NOT NULL UNIQUE,
  is_primary boolean NOT NULL DEFAULT true,
  date_changed timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT member_rsns_pkey PRIMARY KEY (id),
  CONSTRAINT member_rsns_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(id)
);
CREATE TABLE public.members (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  discord_id bigint UNIQUE,
  wom_id integer,
  date_joined timestamp with time zone,
  current_rank_id bigint,
  status USER-DEFINED DEFAULT 'Active'::member_status,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  total_ep bigint DEFAULT 0,
  CONSTRAINT members_pkey PRIMARY KEY (id),
  CONSTRAINT members_current_rank_id_fkey FOREIGN KEY (current_rank_id) REFERENCES public.ranks(id)
);
CREATE TABLE public.rank_history (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  member_id uuid NOT NULL,
  previous_rank_id bigint,
  new_rank_id bigint,
  date_enacted timestamp with time zone NOT NULL DEFAULT now(),
  enacted_by_member_id uuid,
  CONSTRAINT rank_history_pkey PRIMARY KEY (id),
  CONSTRAINT rank_history_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(id),
  CONSTRAINT rank_history_previous_rank_id_fkey FOREIGN KEY (previous_rank_id) REFERENCES public.ranks(id),
  CONSTRAINT rank_history_new_rank_id_fkey FOREIGN KEY (new_rank_id) REFERENCES public.ranks(id),
  CONSTRAINT rank_history_enacted_by_member_id_fkey FOREIGN KEY (enacted_by_member_id) REFERENCES public.members(id)
);
CREATE TABLE public.ranks (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  name character varying NOT NULL UNIQUE,
  rank_type USER-DEFINED NOT NULL,
  hierarchy_level smallint UNIQUE,
  req_months_in_clan smallint,
  req_total_level smallint,
  notes text,
  CONSTRAINT ranks_pkey PRIMARY KEY (id)
);
CREATE TABLE public.wom_snapshots (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  member_id uuid NOT NULL,
  snapshot_date timestamp with time zone NOT NULL DEFAULT now(),
  total_xp bigint,
  total_level smallint,
  ehp real,
  ehb real,
  full_json_payload jsonb,
  CONSTRAINT wom_snapshots_pkey PRIMARY KEY (id),
  CONSTRAINT wom_snapshots_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(id)
);