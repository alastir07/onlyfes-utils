-- 1. Create the new membership_events table
CREATE TABLE public.membership_events (
  id bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
  member_id uuid NOT NULL,
  event_type character varying NOT NULL CHECK (event_type IN ('join', 'leave')),
  event_date timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT membership_events_pkey PRIMARY KEY (id),
  CONSTRAINT membership_events_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(id)
);

-- 2. Backfill existing active members with a 'join' event
INSERT INTO public.membership_events (member_id, event_type, event_date)
SELECT id, 'join', date_joined
FROM public.members
WHERE status = 'Active';

-- 3. Create helper function to calculate days in clan
CREATE OR REPLACE FUNCTION calculate_days_in_clan(p_member_id uuid)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
  total_days integer := 0;
  v_join_date timestamptz;
  event_rec record;
BEGIN
  FOR event_rec IN
    SELECT event_type, event_date
    FROM public.membership_events
    WHERE member_id = p_member_id
    ORDER BY event_date ASC
  LOOP
    IF event_rec.event_type = 'join' THEN
      v_join_date := event_rec.event_date;
    ELSIF event_rec.event_type = 'leave' THEN
      IF v_join_date IS NOT NULL THEN
        total_days := total_days + EXTRACT(EPOCH FROM (event_rec.event_date - v_join_date))/86400;
        v_join_date := NULL;
      END IF;
    END IF;
  END LOOP;
  
  -- Add time since the last 'join' if they are currently active (no matching 'leave')
  IF v_join_date IS NOT NULL THEN
    total_days := total_days + EXTRACT(EPOCH FROM (NOW() - v_join_date))/86400;
  END IF;
  
  RETURN total_days;
END;
$$;

-- 4. Create check_rankups RPC
CREATE OR REPLACE FUNCTION get_eligible_promotions()
RETURNS TABLE (
  member_id uuid,
  rsn character varying,
  current_rank_id bigint,
  days_in_clan integer
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT 
    m.id,
    mr.rsn,
    m.current_rank_id,
    calculate_days_in_clan(m.id) AS days_in_clan
  FROM public.members m
  JOIN public.member_rsns mr ON m.id = mr.member_id AND mr.is_primary = true
  WHERE m.status = 'Active' AND m.current_rank_id IN (10, 11);
END;
$$;
