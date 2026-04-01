import os
import requests
import time
import discord
from supabase import Client
import logging

log = logging.getLogger('ClanBot')

WOM_GROUP_ID = os.getenv("WOM_GROUP_ID")
WOM_API_KEY = os.getenv("WOM_API_KEY")

SKILLS = [
    'overall', 'attack', 'defence', 'strength', 'hitpoints', 'ranged', 'prayer', 
    'magic', 'cooking', 'woodcutting', 'fletching', 'fishing', 'firemaking', 
    'crafting', 'smithing', 'mining', 'herblore', 'agility', 'thieving', 
    'slayer', 'farming', 'runecrafting', 'hunter', 'construction', 'sailing'
]

ACTIVITIES = [
    'bounty_hunter_hunter', 'bounty_hunter_rogue', 'clue_scrolls_all', 
    'clue_scrolls_beginner', 'clue_scrolls_easy', 'clue_scrolls_medium', 
    'clue_scrolls_hard', 'clue_scrolls_elite', 'clue_scrolls_master', 
    'last_man_standing', 'pvp_arena', 'soul_wars_zeal', 'guardians_of_the_rift', 
    'colosseum_glory', 'collections_logged'
]

BOSSES = [
    'abyssal_sire', 'alchemical_hydra', 'amoxliatl', 'araxxor', 'artio', 
    'barrows_chests', 'brutus', 'bryophyta', 'callisto', 'calvarion', 
    'cerberus', 'chambers_of_xeric', 'chambers_of_xeric_challenge_mode', 
    'chaos_elemental', 'chaos_fanatic', 'commander_zilyana', 'corporeal_beast', 
    'crazy_archaeologist', 'dagannoth_prime', 'dagannoth_rex', 'dagannoth_supreme', 
    'deranged_archaeologist', 'doom_of_mokhaiotl', 'duke_sucellus', 'general_graardor', 
    'giant_mole', 'grotesque_guardians', 'hespori', 'kalphite_queen', 'king_black_dragon', 
    'kraken', 'kreearra', 'kril_tsutsaroth', 'lunar_chests', 'mimic', 'nex', 
    'nightmare', 'phosanis_nightmare', 'obor', 'phantom_muspah', 'sarachnis', 
    'scorpia', 'scurrius', 'shellbane_gryphon', 'skotizo', 'sol_heredit', 'spindel', 
    'tempoross', 'the_gauntlet', 'the_corrupted_gauntlet', 'the_hueycoatl', 
    'the_leviathan', 'the_royal_titans', 'the_whisperer', 'theatre_of_blood', 
    'theatre_of_blood_hard_mode', 'thermonuclear_smoke_devil', 'tombs_of_amascut', 
    'tombs_of_amascut_expert', 'tzkal_zuk', 'tztok_jad', 'vardorvis', 'venenatis', 
    'vetion', 'vorkath', 'wintertodt', 'yama', 'zalcano', 'zulrah'
]
def normalize_string(s: str) -> str:
    if not s: return ""
    return s.lower().replace(' ', '').replace('_', '').replace('-', '').replace('.', '')

def format_metric_name(metric: str) -> str:
    return metric.replace('_', ' ').title()

def create_embed(title: str, changes: list) -> discord.Embed:
    embed = discord.Embed(title=title, color=discord.Color.gold())
    
    if not changes:
        embed.description = "No changes this month!"
        return embed
    
    description_lines = []
    for change in changes:
        # e.g., "**Woodcutting**: Bilie (200,000,000) - Rank 5"
        description_lines.append(
            f"**{format_metric_name(change['metric'])}**: {change['player_name']} ({change['value']:,}) - Global Rank {change['rank']}"
        )
    
    desc_str = "\n".join(description_lines)
    if len(desc_str) > 4000:
        desc_str = desc_str[:4000] + "\n... (truncated)"
        
    embed.description = desc_str
    return embed

def run_overachievers_check(supabase: Client, dry_run: bool = True) -> tuple:
    """
    Checks all top members in WOM and records them in Supabase,
    returning a tuple of 3 embeds (skills, activities, bosses) and an error string.
    """
    log.info(f"--- Starting Overachievers Check {'(DRY RUN)' if dry_run else '(LIVE)'} ---")
    
    if not WOM_GROUP_ID or not WOM_API_KEY:
        log.error("Missing WOM_GROUP_ID or WOM_API_KEY.")
        return None, None, None, "Missing WOM API credentials."

    headers = {"User-Agent": "OnlyFEs-Clan-Bot-v1.0", "x-api-key": WOM_API_KEY}
    
    log.info("Fetching members from DB...")
    rsn_res = supabase.table('member_rsns').select('rsn, member_id').execute()
    db_rsn_map = {normalize_string(row['rsn']): row['member_id'] for row in rsn_res.data}
    
    log.info("Fetching previous overachievers...")
    recent_res = supabase.table('overachievers').select('metric, member_id, value, global_rank, date').order('date', desc=True).execute()
    
    latest_db_records = {} # metric -> record
    for row in recent_res.data:
        m = row['metric']
        if m not in latest_db_records:
            latest_db_records[m] = row
            
    categories = [
        ("🏆 Skill Overachievers", SKILLS, 'skill', 'experience'),
        ("⚔️ Activity Overachievers", ACTIVITIES, 'activity', 'score'),
        ("👹 Boss Overachievers", BOSSES, 'boss', 'kills')
    ]
    
    embeds = []
    error_lines = []
    inserts_payload = []
    
    log.info("Fetching metrics from WOM...")
    
    for title, metric_list, category_type, value_key in categories:
        changes = []
        
        for metric in metric_list:
            url = f"https://api.wiseoldman.net/v2/groups/{WOM_GROUP_ID}/hiscores?metric={metric}&limit=1"
            try:
                time.sleep(0.3)
                res = requests.get(url, headers=headers)
                res.raise_for_status()
                data = res.json()
                
                if not data:
                    continue
                    
                top_entry = data[0]
                player = top_entry['player']
                player_data = top_entry['data']
                
                wom_id = player['id']
                display_name = player['displayName']
                username = player['username']
                
                val = player_data.get(value_key, 0)
                rank = player_data.get('rank', -1)
                
                normalized_username = normalize_string(username)
                member_id = db_rsn_map.get(normalized_username)
                if not member_id:
                    error_lines.append(f"Skipped {metric}: Top player {display_name} (WOM ID {wom_id}) not found in database.")
                    continue
                
                previous_record = latest_db_records.get(metric)
                
                changed = False
                if not previous_record:
                    changed = True
                elif previous_record['member_id'] != member_id:
                    changed = True
                
                if changed:
                    changes.append({
                        'metric': metric,
                        'player_name': display_name,
                        'value': val,
                        'rank': rank
                    })
                
                inserts_payload.append({
                    'member_id': member_id,
                    'metric': metric,
                    'value': val,
                    'global_rank': rank
                })

            except Exception as e:
                error_lines.append(f"Failed to fetch {metric}: {e}")
                
        embeds.append(create_embed(title, changes))

    if not dry_run and inserts_payload:
        log.info(f"Inserting {len(inserts_payload)} new overachiever records...")
        try:
            chunk_size = 50
            for i in range(0, len(inserts_payload), chunk_size):
                supabase.table('overachievers').insert(inserts_payload[i:i+chunk_size]).execute()
        except Exception as e:
            error_lines.append(f"DB Insert failed: {e}")
            log.error(f"DB Insert failed: {e}")

    error_str = "\n".join(error_lines)
    return embeds[0], embeds[1], embeds[2], error_str
