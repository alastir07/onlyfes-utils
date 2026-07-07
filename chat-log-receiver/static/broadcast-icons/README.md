# Broadcast icons

Vendored from the [OSRS Wiki](https://oldschool.runescape.wiki/w/Ironman_Mode), licensed [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/). These are the ironman-mode chat badges that appear in clan broadcast messages (drops, XP milestones, quest completions, etc.) via the client's `<img=N>` tag syntax.

Filenames are `img<N>.png`, matching the `N` in the `<img=N>` tag emitted by the game client, so a tag maps directly to its icon file with no separate lookup table:

| Code | Mode |
|------|------|
| `img2` | Ironman |
| `img3` | Ultimate Ironman |
| `img10` | Hardcore Ironman |
| `img41` | Group Ironman |
| `img43` | Unranked Group Ironman |

Only the codes actually observed in this clan's chat logs are vendored; other `<img=N>` codes used by the client for other purposes are rendered as literal text if encountered.
