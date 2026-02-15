-- DB FUNCTION: get_active_member_snapshots
-- Returns a list of active members and their latest snapshots

CREATE OR REPLACE FUNCTION get_active_member_snapshots()
RETURNS TABLE (
  id UUID,
  date_joined TIMESTAMPTZ,
  current_rank_id BIGINT,
  latest_db_xp BIGINT,
  total_level SMALLINT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    m.id,
    m.date_joined,
    m.current_rank_id,
    s.total_xp AS latest_db_xp,
    s.total_level
  FROM
    public.members m
  -- LEFT JOIN so we still get members with NO snapshot
  LEFT JOIN LATERAL (
    -- This subquery gets only the *most recent* snapshot
    -- for each member.
    SELECT snap.total_xp, snap.total_level
    FROM public.wom_snapshots snap
    WHERE snap.member_id = m.id
    ORDER BY snap.snapshot_date DESC
    LIMIT 1
  ) s ON true
  WHERE
    m.status = 'Active';
END;
$$;


-- DB FUNCTION: get_member_info
-- Returns a single member's info based on their RSN 

DECLARE
  v_member_id UUID;
BEGIN
  -- 1. Find the member_id from *any* of their RSNs (case-insensitive)
  SELECT member_id INTO v_member_id
  FROM public.member_rsns
  WHERE rsn ILIKE rsn_query
  LIMIT 1;

  -- 2. If found, fetch and return their details
  IF v_member_id IS NOT NULL THEN
    RETURN QUERY
    SELECT
      -- Get primary RSN (fallback to query if missing, though unlikely)
      COALESCE(
        (SELECT rsn FROM public.member_rsns pr WHERE pr.member_id = v_member_id AND pr.is_primary = true LIMIT 1),
        rsn_query
      ) AS primary_rsn,
      
      -- logic to show "NOT IN CLAN" if they are inactive
      CASE
        WHEN m.status = 'Inactive' THEN 'NOT IN CLAN'
        ELSE r.name
      END AS rank_name,
      
      m.date_joined,
      
      -- DIRECTLY SELECT THE CACHED TOTAL
      m.total_ep,
      
      -- Aggregate the 5 most recent non-primary RSNs
      (
        SELECT array_agg(past_rsns.rsn)
        FROM (
          SELECT rsn
          FROM public.member_rsns pn
          WHERE pn.member_id = v_member_id AND pn.is_primary = false
          ORDER BY pn.date_changed DESC
          LIMIT 5
        ) AS past_rsns
      ) AS past_names,
      
      m.discord_id,

      -- Get the most recent WOM snapshot date
      (
        SELECT snapshot_date
        FROM public.wom_snapshots ws
        WHERE ws.member_id = v_member_id
        ORDER BY snapshot_date DESC
        LIMIT 1
      ) AS latest_wom_snapshot,

      -- Get the most recent event point transaction date
      (
        SELECT date_enacted
        FROM public.event_point_transactions ept
        WHERE ept.member_id = v_member_id
        AND ept.modification > 0
        ORDER BY date_enacted DESC
        LIMIT 1
      ) AS latest_ep_transaction
    FROM
      public.members AS m
    -- Left join rank because inactive members might not have a valid rank_id
    LEFT JOIN public.ranks AS r ON m.current_rank_id = r.id
    WHERE
      m.id = v_member_id;
  END IF;
END;

-- DB FUNCTION: get_rank_history
-- Returns a single member's rank history based on their member_id 

DECLARE
    target_member_id uuid;
    target_primary_rsn text;
BEGIN
    -- Find the member_id and primary_rsn based on the input RSN (which could be a past name)
    SELECT m.id, mr_primary.rsn INTO target_member_id, target_primary_rsn
    FROM member_rsns mr_query
    JOIN members m ON mr_query.member_id = m.id
    JOIN member_rsns mr_primary ON m.id = mr_primary.member_id
    WHERE mr_query.rsn ILIKE rsn_query
      AND mr_primary.is_primary = TRUE
    LIMIT 1;
    
    -- If no member found, return empty
    IF target_member_id IS NULL THEN
        RETURN;
    END IF;

    -- Return the rank history
    RETURN QUERY
    SELECT 
        target_primary_rsn::text,
        rh.date_enacted,
        COALESCE(r_prev.name, 'N/A')::text, -- Cast to text
        r_new.name::text -- Cast to text
    FROM rank_history rh
    LEFT JOIN ranks r_prev ON rh.previous_rank_id = r_prev.id
    JOIN ranks r_new ON rh.new_rank_id = r_new.id
    WHERE rh.member_id = target_member_id
    ORDER BY rh.date_enacted DESC
    LIMIT limit_count;
END;

-- DB FUNCTION: update_member_ep_on_transaction
-- Updates a member's total EP when a transaction is inserted or updated

BEGIN
    -- If inserting or updating, update the member associated with the NEW record
    IF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        UPDATE public.members
        SET total_ep = (
            SELECT COALESCE(SUM(modification), 0)
            FROM public.event_point_transactions
            WHERE member_id = NEW.member_id
        )
        WHERE id = NEW.member_id;
    END IF;

    -- If deleting or updating, update the member associated with the OLD record
    -- (In case member_id changed, though unlikely, or row deleted)
    IF (TG_OP = 'DELETE' OR TG_OP = 'UPDATE') THEN
        IF (TG_OP = 'UPDATE' AND NEW.member_id = OLD.member_id) THEN
            -- Already handled above
            RETURN NULL;
        END IF;
        
        UPDATE public.members
        SET total_ep = (
            SELECT COALESCE(SUM(modification), 0)
            FROM public.event_point_transactions
            WHERE member_id = OLD.member_id
        )
        WHERE id = OLD.member_id;
    END IF;

    RETURN NULL;
END;
