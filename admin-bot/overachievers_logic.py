import os
import requests
import discord
from supabase import Client
import logging
import clan_sync_logic

log = logging.getLogger('ClanBot')

WOM_GROUP_ID = os.getenv("WOM_GROUP_ID")
WOM_API_KEY = os.getenv("WOM_API_KEY")

# Category -> (embed title, value_key). Metric names within each category are
# pulled live from WOM's group statistics endpoint, so new bosses/activities/skills
# WOM adds are picked up automatically without needing a code change here.
CATEGORY_CONFIG = {
    'skills': ("🏆 Skill Overachievers", 'experience'),
    'activities': ("⚔️ Activity Overachievers", 'score'),
    'bosses': ("👹 Boss Overachievers", 'kills'),
}

def fetch_group_metric_leaders() -> dict:
    """
    Fetches the group's WOM statistics and returns the metricLeaders dict,
    limited to the categories we track (skills, activities, bosses).
    """
    headers = {"User-Agent": "OnlyFEs-Clan-Bot-v1.0", "x-api-key": WOM_API_KEY}
    stats_url = f"https://api.wiseoldman.net/v2/groups/{WOM_GROUP_ID}/statistics"
    res = requests.get(stats_url, headers=headers)
    res.raise_for_status()
    metric_leaders = res.json().get('metricLeaders', {})
    return {cat: metric_leaders.get(cat, {}) for cat in CATEGORY_CONFIG}

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

    log.info("Fetching members from DB...")
    rsn_data = clan_sync_logic.fetch_all_rows(
        supabase.table('member_rsns').select('rsn, member_id, is_primary').order('is_primary', desc=True)
    )
    db_rsn_map = {}
    for row in rsn_data:
        key = normalize_string(row['rsn'])
        if key not in db_rsn_map:
            db_rsn_map[key] = row['member_id']  # first-seen wins; is_primary rows sort first

    log.info("Fetching previous overachievers...")
    recent_res = supabase.table('overachievers').select('metric, member_id, value, global_rank, date').order('date', desc=True).execute()

    latest_db_records = {} # metric -> record
    for row in recent_res.data:
        m = row['metric']
        if m not in latest_db_records:
            latest_db_records[m] = row

    embeds = []
    error_lines = []
    inserts_payload = []

    log.info("Fetching group statistics from WOM...")

    try:
        metric_leaders = fetch_group_metric_leaders()
    except Exception as e:
        log.error(f"Failed to fetch group statistics: {e}")
        return None, None, None, f"Failed to fetch group statistics: {e}"

    for leader_category, (title, value_key) in CATEGORY_CONFIG.items():
        changes = []
        leaders_for_category = metric_leaders.get(leader_category, {})

        for metric, leader_entry in leaders_for_category.items():
            player = leader_entry.get('player')
            if not player:
                error_lines.append(f"Skipped {metric}: No player leads this metric in the group.")
                continue

            wom_id = player['id']
            display_name = player['displayName']
            username = player['username']

            val = leader_entry.get(value_key, 0)
            rank = leader_entry.get('rank', -1)

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

def get_current_overachiever_member_ids(supabase: Client) -> set:
    """
    Returns the set of member_ids that currently hold the #1 spot
    for at least one metric, based on the latest recorded row per metric.
    """
    recent_res = supabase.table('overachievers').select('metric, member_id, date').order('date', desc=True).execute()

    latest_db_records = {}  # metric -> record
    for row in recent_res.data:
        m = row['metric']
        if m not in latest_db_records:
            latest_db_records[m] = row

    return {rec['member_id'] for rec in latest_db_records.values()}

def get_overachiever_lookup(supabase: Client, query: str) -> tuple[discord.Embed, str]:
    log.info(f"--- Running Lookup for Overachiever '{query}' ---")
    
    normalized_query = normalize_string(query)

    # Check if the query is a Metric (any metric ever recorded, so no
    # separate static list to keep in sync with WOM's tracked metrics)
    metrics_res = supabase.table('overachievers').select('metric').execute()
    all_metrics = {row['metric'] for row in metrics_res.data}
    matched_metric = None
    for m in all_metrics:
        if normalize_string(m) == normalized_query:
            matched_metric = m
            break
            
    if matched_metric:
        # Search the database for who is the overachiever for this metric
        res = supabase.table('overachievers').select('metric, member_id, value, global_rank, date, members(member_rsns(rsn, is_primary))').eq('metric', matched_metric).order('date', desc=True).limit(1).execute()
        
        if not res.data:
            return None, f"No overachiever found for '{format_metric_name(matched_metric)}' (sync may not have run yet)."
            
        data = res.data[0]
        primary_rsn = "Unknown"
        if data.get('members') and data['members'].get('member_rsns'):
            for rsn_obj in data['members']['member_rsns']:
                if rsn_obj.get('is_primary'):
                    primary_rsn = rsn_obj['rsn']
                    break
                    
        embed = discord.Embed(title=f"🏆 {format_metric_name(matched_metric)}", color=discord.Color.gold())
        
        date_obj = discord.utils.parse_time(data['date'])
        if date_obj is None:
            date_str = data['date'].split('T')[0]
        else:
            date_str = f"<t:{int(date_obj.timestamp())}:D>"

        embed.description = f"**{primary_rsn}** is the clan's overachiever with a value of **{data['value']:,}** (Global Rank: {data['global_rank']}).\n*Recorded on: {date_str}*"
        return embed, None
        
    else:
        # It's an RSN query
        rsn_res = supabase.table('member_rsns') \
            .select('member_id, rsn, is_primary') \
            .eq('normalized_rsn', normalized_query) \
            .order('is_primary', desc=True) \
            .execute()

        if not rsn_res.data:
            return None, f"Could not find any member with RSN: '{query}' or any metric called '{query}'."

        member_record = rsn_res.data[0]
        member_id = member_record['member_id']
        display_rsn = member_record['rsn']
        
        recent_res = supabase.table('overachievers').select('metric, member_id, value, global_rank, date').order('date', desc=True).limit(2000).execute()
        
        latest_db_records = {} # metric -> record
        for row in recent_res.data:
            m = row['metric']
            if m not in latest_db_records:
                latest_db_records[m] = row
                
        user_records = [rec for rec in latest_db_records.values() if rec['member_id'] == member_id]
        
        if not user_records:
            return None, f"'{display_rsn}' is currently not an overachiever for any metric."
            
        embed = discord.Embed(title=f"🏆 Overachiever: {display_rsn}", description=f"They currently hold the #1 spot in the clan for **{len(user_records)}** metrics:", color=discord.Color.gold())
        
        lines = []
        for rec in user_records:
            lines.append(f"**{format_metric_name(rec['metric'])}**: {rec['value']:,} (Global Rank {rec['global_rank']})")
            
        desc_str = "\n".join(lines)
        if len(desc_str) > 4000:
            desc_str = desc_str[:4000] + "\n... (truncated)"
        embed.description = embed.description + "\n\n" + desc_str
        
        return embed, None
