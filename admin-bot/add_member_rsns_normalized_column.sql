-- Adds a generated, indexed column mirroring Python's normalize_string()
-- (lower + strip spaces/underscores/dashes/dots) so RSN lookups can be
-- pushed server-side instead of fetching the whole member_rsns table and
-- normalizing in Python.
--
-- Not unique: normalize_string() collisions already exist in the table
-- (e.g. "Bonnie Moo" and "bonnie moo" as separate rows), so lookups on
-- this column can still return >1 row for those RSNs.
ALTER TABLE public.member_rsns
  ADD COLUMN normalized_rsn text
  GENERATED ALWAYS AS (
    lower(regexp_replace(rsn, '[ _\-.]', '', 'g'))
  ) STORED;

CREATE INDEX idx_member_rsns_normalized_rsn ON public.member_rsns (normalized_rsn);
