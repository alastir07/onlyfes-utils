"""
One-off script: assign hunt-tX team Discord roles to a fixed roster.

Usage:
    python assign_hunt_teams.py            # dry run - prints match report only
    python assign_hunt_teams.py --apply    # actually applies role grants

Never removes roles. Only adds TeamN roles to users who match a roster name
with high confidence (exact match on normalized display name or username).
Ambiguous/unmatched names are reported and skipped.
"""

import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = "1054602579197300867"
API_BASE = "https://discord.com/api/v10"
HEADERS = {"Authorization": f"Bot {BOT_TOKEN}"}

TEAM_ROLE_IDS = {
    1: "1261439995198308452",
    2: "1261440067314909326",
    3: "1261440093999202314",
    4: "1261440109383778315",
    6: "1261440177105010829",
    7: "1261440141722124340",
    8: "1261440160281923614",
    9: "1261443802653130762",
    10: "1261444015883161762",
    11: "1261665876097368064",
    12: "1261686940797898857",
    13: "1261687312899903528",
}

# Manual overrides: roster name -> exact Discord user ID.
# Confirmed by hand for names that didn't exact-match a display name/username
# (typos, missing text, or trailing emoji breaking normalization).
MANUAL_OVERRIDES = {
    ("odins fe", 3): "1366444693721710836",       # Odins Reign | Odins Fe
    ("Wintersf1n", 6): "208950762603020288",       # wintersfin
    ("shmomboski", 6): "100112321027805184",       # BD Shmombo
    ("Peachn Cream", 11): "105758812564140032",    # PeachesN Cream
    ("fe scrammy", 11): "343340690194956289",      # ScrammyT
    ("Honey Iron", 12): "1306734249969193030",     # Honey Iron ✿
    ("suckonalemor", 13): "251788984622120963",    # SuckOnALemon
    ("pogerdito", 11): "1293910910255235146",      # Pogzard
}

ROSTER = {
    1: "KraggorFe,Sir Eggson,Whyte Tree,Iron Toms,Iron Nuro,Billie Jon,Miss Kora,Sawij23,mosi,BubbaChrist,ThugWorkout,Machine user",
    2: "Moldead,thefeodyssey,Yetzne,Gragitha,E425,fe kranteri,KnotMatt,routh hurwtz,acim clamsey,pelothefirst,IM MiniMars,major fumble",
    3: "Toter,gd0ng,BigOinker,Iron4Once,eblic,Parkerrr,bazathril,gregyy,xjeju,odins fe,xooona,hoggy woggy",
    4: "came in mouf,draven,kalphite24,NaCl Idiot,peachi,OSFeMale,nordicnoob,Leet,UltSurrender,Ellboy,Puddle Water,haearnstem",
    6: "Wintersf1n,Zaoirse,I TrainRNG,HNO 3,Postbiotics,Lico Doss,Adoluk,faithi2,TiniestDoggy,shmomboski,xsequoia,Phyeron",
    7: "Wapurn,fiylothnri,GI Madras,itax,davynotdavy,Mr Cerritos,SplashOnRat,EntroFe,IM crybaby,duffy,psib,rum ravager",
    8: "BIG DadBod,Zoooom,zomgrick,j xck,Pladask,Mr Fizzi,Beoform,ginormousd,big peets,uim menesus,Hyrulepanda,fe dallazr",
    9: "Yuschy,1TickNoose,Boolaa,Giga Aaron,Me pie,Crabimov,Kamlito,milbv,floradix,RelicBv,lil goblet,lantzeon",
    10: "IMattM,d26,stan lalisa,Sgt Nikolai,ddarren,raechele,t7f,GIM KingOfW,miketherake,Friggof,irons,im r108",
    11: "Corvids,GIM Raptoid,Buttery Nutz,Lost Boobs,Peachn Cream,Jollbo,Jern Bear,silene lydia,nexuscrux,Solo Godric,fe scrammy,pogerdito",
    12: "Kevinski,va1tz,aurora mey,Ala_chicken,Smrta xD,BigDaniel21,Honey Iron,Pod Racer,boomermyst,irongeroge,MaybeMax,foster_ch1ld",
    13: "BTW JJ,atacamajag,vibe coder,I See Uranus,Givr Budd,ItsXY,solo shiny,Iron Sorcom,Angel Ke,fiskefrank,Razzberrry,suckonalemor",
}


def normalize(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[\s_\-.]", "", s)
    return s


def discord_request(method, url, **kwargs):
    for attempt in range(2):
        resp = requests.request(method, url, headers=HEADERS, **kwargs)
        if resp.status_code == 429 and attempt == 0:
            retry_after = resp.json().get("retry_after", 1)
            time.sleep(float(retry_after) + 0.1)
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def fetch_all_members():
    members = []
    after = "0"
    while True:
        resp = discord_request(
            "GET",
            f"{API_BASE}/guilds/{GUILD_ID}/members",
            params={"limit": 1000, "after": after},
        )
        batch = resp.json()
        if not batch:
            break
        members.extend(batch)
        after = batch[-1]["user"]["id"]
        if len(batch) < 1000:
            break
    return members


def build_lookup(members):
    """normalized name -> list of (user_id, label, member) for display_name/global_name/username"""
    lookup = {}
    for m in members:
        user = m["user"]
        candidates = set()
        if m.get("nick"):
            candidates.add(m["nick"])
        if user.get("global_name"):
            candidates.add(user["global_name"])
        if user.get("username"):
            candidates.add(user["username"])
        for label in candidates:
            key = normalize(label)
            lookup.setdefault(key, []).append((user["id"], label, m))
    return lookup


def main():
    apply_changes = "--apply" in sys.argv
    test_apply = "--test-apply" in sys.argv

    print("Fetching guild members...")
    members = fetch_all_members()
    print(f"Fetched {len(members)} members.\n")

    lookup = build_lookup(members)

    user_by_id = {m["user"]["id"]: m for m in members}

    matched = []       # (team, roster_name, user_id, matched_label)
    unmatched = []      # (team, roster_name)
    ambiguous = []       # (team, roster_name, [candidates])

    for team, csv_names in ROSTER.items():
        for raw_name in csv_names.split(","):
            name = raw_name.strip()

            override_id = MANUAL_OVERRIDES.get((name, team))
            if override_id:
                member = user_by_id.get(override_id)
                label = member["user"].get("global_name") or member["user"]["username"] if member else "?"
                matched.append((team, name, override_id, f"{label} [manual override]"))
                continue

            key = normalize(name)
            raw_candidates = lookup.get(key, [])
            # dedupe: the same user can match via nick/global_name/username at once
            by_user = {}
            for user_id, label, member in raw_candidates:
                by_user.setdefault(user_id, (user_id, label, member))
            candidates = list(by_user.values())
            if len(candidates) == 1:
                user_id, label, member = candidates[0]
                matched.append((team, name, user_id, label))
            elif len(candidates) > 1:
                ambiguous.append((team, name, candidates))
            else:
                unmatched.append((team, name))

    print(f"MATCHED ({len(matched)}):")
    for team, name, user_id, label in matched:
        print(f"  Team{team}: \"{name}\" -> {label} (id={user_id})")

    if ambiguous:
        print(f"\nAMBIGUOUS ({len(ambiguous)}) - skipped, multiple members share this name:")
        for team, name, candidates in ambiguous:
            labels = ", ".join(f"{label} (id={uid})" for uid, label, _ in candidates)
            print(f"  Team{team}: \"{name}\" -> {labels}")

    if unmatched:
        print(f"\nUNMATCHED ({len(unmatched)}) - no exact match found, skipped:")
        for team, name in unmatched:
            print(f"  Team{team}: \"{name}\"")

    total = len(matched) + len(ambiguous) + len(unmatched)
    print(f"\nSummary: {len(matched)}/{total} matched, {len(ambiguous)} ambiguous, {len(unmatched)} unmatched.")

    if test_apply:
        team, name, user_id, label = matched[0]
        role_id = TEAM_ROLE_IDS[team]
        print(f"\nTEST APPLY: granting Team{team} to {label} (id={user_id}) only...")
        try:
            discord_request(
                "PUT",
                f"{API_BASE}/guilds/{GUILD_ID}/members/{user_id}/roles/{role_id}",
            )
            print(f"  OK: {label} -> Team{team}")
        except requests.HTTPError as e:
            print(f"  FAILED: {label} -> Team{team}: {e}")
        return

    if not apply_changes:
        print("\nDry run only. Re-run with --apply to grant roles to the MATCHED list above.")
        return

    print("\nApplying role grants (adding only, never removing existing roles)...")
    failures = []
    for team, name, user_id, label in matched:
        role_id = TEAM_ROLE_IDS[team]
        try:
            discord_request(
                "PUT",
                f"{API_BASE}/guilds/{GUILD_ID}/members/{user_id}/roles/{role_id}",
            )
            print(f"  OK: {label} -> Team{team}")
        except requests.HTTPError as e:
            failures.append((team, name, label, str(e)))
            print(f"  FAILED: {label} -> Team{team}: {e}")

    print(f"\nDone. {len(matched) - len(failures)}/{len(matched)} roles applied successfully.")
    if failures:
        print(f"{len(failures)} failures - see above.")


if __name__ == "__main__":
    main()
