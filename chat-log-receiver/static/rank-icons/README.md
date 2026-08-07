# Rank icons

Vendored from the [OSRS Wiki's Clan rank icons category](https://oldschool.runescape.wiki/w/Category:Clan_rank_icons), licensed [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/). Only the 24 rank icons matching this clan's `ranks` table are included, not the full wiki set.

Filenames are `normalize_string(ranks.name) + ".png"` (lowercase, spaces/underscores/hyphens/periods stripped — same normalization as `rsn.py`), so a rank name from the DB maps directly to its icon file with no separate lookup table, e.g. `"Deputy Owner"` -> `deputyowner.png`, `"TzKal"` -> `tzkal.png`.
