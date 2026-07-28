-- Run this in Supabase SQL Editor
-- Updates the `ranks` table to match the new In-Game Ranking System
-- posted in #1059343869994610699 (thread 1419388228883976353, msg 1521701917972234322).
--
-- Changes vs. previous requirements:
--   Onyx:        1900 -> 2000 total level; manual criteria simplified (drops the
--                "Hard CAs OR 3x Skill Masteries" alternative -> just "Hard CAs")
--   Zenyte:      months unchanged at 6; 2000 -> 2200 total level; drops
--                "All Completed Hard Diaries" and "Hard CAs" since its own
--                "Achievement Diary Cape (t)" and "Elite CAs" supersede them
--   Maxed:       months unchanged at 6; 2000 -> 2376 total level (max total level)
--   TzKal:       months unchanged at 6; drops "1500 Combat Points"; drops
--                "Hard CAs" since its own "Master CAs" supersedes it
--   Myth:        8 -> 6 months (max of Maxed/TzKal/Zenyte, all 6mo); total level
--                unchanged at 2376; inherited diary/CA requirements collapse to
--                the single strictest tier in each category -> Achievement Diary
--                Cape (t) (from Zenyte) subsumes "All Completed Hard Diaries",
--                and Master CAs (from TzKal) subsumes both "Hard CAs" and
--                "Elite CAs" (from Zenyte); drops the tiered "Music Cape (t)"
--                requirement -> just "Music Cape"; adds "1000 Collection Logs"
--   Diamond/Dragonstone: months/total level unchanged, manual criteria reworded
--                to match new phrasing (adds "Easy/Medium CAs")
--   Sapphire/Emerald/Ruby: unchanged

UPDATE public.ranks SET
  req_months_in_clan = 3,
  req_total_level = 1500,
  notes = '3 Months Member, 1500 Total Level, All Completed Easy Diaries, Easy CAs.',
  manual_criteria = 'All Completed Easy Diaries, Easy CAs'
WHERE name = 'Diamond';

UPDATE public.ranks SET
  req_months_in_clan = 4,
  req_total_level = 1750,
  notes = '4 Months Member, 1750 Total Level, All Completed Medium Diaries, Medium CAs.',
  manual_criteria = 'All Completed Medium Diaries, Medium CAs'
WHERE name = 'Dragonstone';

UPDATE public.ranks SET
  req_months_in_clan = 5,
  req_total_level = 2000,
  notes = '5 Months Member, 2000 Total Level, All Completed Hard Diaries, Hard CAs, Quest Point Cape.',
  manual_criteria = 'All Completed Hard Diaries, Hard CAs, Quest Point Cape'
WHERE name = 'Onyx';

UPDATE public.ranks SET
  req_months_in_clan = 6,
  req_total_level = 2200,
  notes = '6 Months Member, 2200 Total Level, Quest Point Cape, Achievement Diary Cape (t), Elite CAs.',
  manual_criteria = 'Quest Point Cape, Achievement Diary Cape (t), Elite CAs'
WHERE name = 'Zenyte';

UPDATE public.ranks SET
  req_months_in_clan = 6,
  req_total_level = 2376,
  notes = 'Elite Skiller. 6 Months Member, 2376 Total Level, All Completed Hard Diaries, Hard CAs, Quest Point Cape, Maxed Overall.',
  manual_criteria = 'All Completed Hard Diaries, Hard CAs, Quest Point Cape, Maxed Overall'
WHERE name = 'Maxed';

UPDATE public.ranks SET
  req_months_in_clan = 6,
  req_total_level = 2000,
  notes = 'Elite PvMer. 6 Months Member, 2000 Total Level, All Completed Hard Diaries, Quest Point Cape, Dizana''s Quiver, Infernal Cape, Master CAs.',
  manual_criteria = 'All Completed Hard Diaries, Quest Point Cape, Dizana''s Quiver, Infernal Cape, Master CAs'
WHERE name = 'TzKal';

UPDATE public.ranks SET
  req_months_in_clan = 6,
  req_total_level = 2376,
  notes = 'Living Legend. 6 Months Member, 2376 Total Level, Maxed Overall, Quest Point Cape, Achievement Diary Cape (t), Dizana''s Quiver, Infernal Cape, Master CAs, Music Cape, 1000 Collection Logs.',
  manual_criteria = 'Maxed Overall, Quest Point Cape, Achievement Diary Cape (t), Dizana''s Quiver, Infernal Cape, Master CAs, Music Cape, 1000 Collection Logs'
WHERE name = 'Myth';
