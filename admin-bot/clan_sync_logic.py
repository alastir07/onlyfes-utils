import os
import requests
import time
import re
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timezone
from dateutil.parser import parse
import sys
import logging

# Initialize the logger for your bot's custom messages
log = logging.getLogger('ClanBot') 
log.setLevel(logging.INFO) # Set the minimum level for your custom logs

# Create a handler that sends output to sys.stdout
handler = logging.StreamHandler(sys.stdout)

# Set the desired format, which includes the levelname and timestamp
formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(name)s: %(message)s', 
                              datefmt='%Y-%m-%d %H:%M:%S')

handler.setFormatter(formatter)

# Add the handler to the root logger or your specific logger
# Using the root logger is usually best for a uniform output
root = logging.getLogger()
# Clear existing handlers to prevent duplicate logs
if root.hasHandlers():
    root.handlers.clear()
root.addHandler(handler)
root.setLevel(logging.INFO) # Set the minimum level for all logs

# --- 1. LOAD ENVIRONMENT & CONNECT ---
log.info("Loading environment and connecting to clients...")
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
WOM_GROUP_ID = os.getenv("WOM_GROUP_ID")
WOM_API_KEY = os.getenv("WOM_API_KEY")

MISMATCH_THRESHOLD = 15

# This check is only for when running this file directly
if __name__ == "__main__":
    if not all([SUPABASE_URL, SUPABASE_KEY, WOM_GROUP_ID, WOM_API_KEY]):
        log.error("Error: Missing .env variables. Make sure all are set.")
        exit()

# --- 2. NORMALIZATION FUNCTION ---
def normalize_string(s: str) -> str:
    if not s:
        return ""
    return s.lower().replace(' ', '').replace('_', '').replace('-', '').replace('.', '')
    return s.lower().replace(' ', '').replace('_', '').replace('-', '').replace('.', '')

def fetch_all_rows(query_builder, page_size=1000):
    """Helper to fetch all rows using pagination"""
    all_data = []
    page = 0
    while True:
        start = page * page_size
        end = start + page_size - 1
        # Note: Supabase range is inclusive
        response = query_builder.range(start, end).execute()
        data = response.data
        
        if not data:
            break
            
        all_data.extend(data)
        
        if len(data) < page_size:
            break
            
        page += 1
    return all_data

def fetch_wom_members() -> tuple:
    log.info(f"Fetching group data from WOM Group ID: {WOM_GROUP_ID}...")
    url = f"https://api.wiseoldman.net/v2/groups/{WOM_GROUP_ID}"
    headers = {"User-Agent": "OnlyFEs-Clan-Bot-v1.0", "x-api-key": WOM_API_KEY}
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        group_data = response.json()
        wom_members = {}
        for membership in group_data.get("memberships", []):
            if membership.get("player"):
                player = membership["player"]
                normalized_rsn = normalize_string(player["username"])
                wom_members[normalized_rsn] = {
                    "rsn": player["username"],
                    "wom_id": player["id"],
                    "rank": membership["role"],
                    "stale_exp": player.get("exp"),
                    "latest_snapshot": None
                }
        log.info(f"Found {len(wom_members)} members on WOM.")
        return wom_members, group_data
    except Exception as e:
        log.error(f"Error fetching from WOM API: {e}")
        return None, None

def fetch_db_ranks_and_rsns(supabase: Client) -> (dict, dict, dict):
    log.info("Fetching ranks and RSN map from Supabase DB...")
    try:
        ranks_res = supabase.table('ranks').select('id, name').execute()
        ranks_map_normalized = {}
        ranks_map_by_id = {}
        for rank in ranks_res.data:
            ranks_map_normalized[normalize_string(rank['name'])] = rank['id']
            ranks_map_by_id[rank['id']] = rank['name']
        
        
        rsns_query = supabase.table('member_rsns').select('rsn, member_id, is_primary')
        rsns_data = fetch_all_rows(rsns_query)
        
        db_rsn_map_normalized = {}
        for item in rsns_data:
            db_rsn_map_normalized[normalize_string(item['rsn'])] = {
                "member_id": item['member_id'],
                "is_primary": item['is_primary'],
                "original_rsn": item['rsn']
            }
        
        log.info(f"Found {len(ranks_map_normalized)} ranks and {len(db_rsn_map_normalized)} total RSNs in DB.")
        return ranks_map_normalized, ranks_map_by_id, db_rsn_map_normalized
    except Exception as e:
        log.error(f"Error fetching from Supabase: {e}")
        return None, None, None

def fetch_db_member_data(supabase: Client) -> dict:
    log.info("Fetching active members and latest snapshots from DB...")
    try:
        response = supabase.rpc('get_active_member_snapshots').execute()
        db_member_data = {}
        for member in response.data:
            db_member_data[member['id']] = {
                "member_id": member['id'],
                "date_joined": member['date_joined'],
                "current_rank_id": member['current_rank_id'],
                "latest_db_xp": member['latest_db_xp']
            }
        log.info(f"Found {len(db_member_data)} active members in DB.")
        return db_member_data
    except Exception as e:
        log.error(f"Error fetching active member snapshots: {e}")
        return None

def fetch_all_db_members(supabase: Client) -> dict:
    """Fetch ALL members (active and inactive) for detecting returning members"""
    log.info("Fetching all members from DB (including inactive)...")
    try:
        response = supabase.table('members').select('id, current_rank_id, status').execute()
        all_members = {}
        for member in response.data:
            all_members[member['id']] = {
                "member_id": member['id'],
                "current_rank_id": member['current_rank_id'],
                "status": member['status']
            }
        log.info(f"Found {len(all_members)} total members in DB.")
        return all_members
    except Exception as e:
        log.error(f"Error fetching all members: {e}")
        return None

def fetch_player_snapshots(supabase: Client, wom_members: dict, db_member_data: dict, db_rsn_map_normalized: dict, dry_run: bool):
    log.info("Enriching snapshots...")
    headers = {"User-Agent": "OnlyFEs-Clan-Bot-v1.0", "x-api-key": WOM_API_KEY}
    request_count = 0
    start_time = time.time()
    
    total_members = len(wom_members)
    current_member_num = 0
    skipped_count = 0
    dry_run_skip_count = 0
    
    for normalized_rsn, wom_member in wom_members.items():
        current_member_num += 1
        username = wom_member['rsn']
        
        member_id = db_rsn_map_normalized.get(normalized_rsn, {}).get('member_id')
        if member_id and member_id in db_member_data:
            db_data = db_member_data[member_id]
            wom_stale_exp = wom_member.get('stale_exp')
            db_latest_exp = db_data.get('latest_db_xp')
            
            if wom_stale_exp is not None and db_latest_exp is not None and wom_stale_exp == db_latest_exp:
                skipped_count += 1
                continue 
        
        if dry_run:
            log.info(f"  [DRY RUN] Would fetch snapshot for: {username}")
            dry_run_skip_count += 1
            continue

        if request_count >= 90:
            elapsed = time.time() - start_time
            if elapsed < 60:
                wait_time = 60.1 - elapsed
                log.info(f"Rate limit hit. Sleeping for {wait_time:.1f} seconds...")
                time.sleep(wait_time)
            request_count = 0
            start_time = time.time()
        
        try:
            url = f"https://api.wiseoldman.net/v2/players/{username}"
            response = requests.get(url, headers=headers)
            request_count += 1
            response.raise_for_status()
            
            player_data = response.json()
            
            if player_data.get('latestSnapshot'):
                wom_member['latest_snapshot'] = player_data['latestSnapshot']
                log.info(f"Successfully fetched snapshot for {wom_member['rsn']}")
            else:
                wom_member['latest_snapshot'] = None
        except Exception as e:
            log.warning(f"Warning: Could not fetch snapshot for {wom_member['rsn']}. {e}")
            wom_member['latest_snapshot'] = None
            
    log.info(f"Snapshot enrichment complete. Skipped {skipped_count} unchanged players.")
    if dry_run_skip_count > 0:
        log.info(f"  [DRY RUN] Skipped fetching snapshots for {dry_run_skip_count} players.")

# --- 4. NAME CHANGE FUNCTION ---

def fetch_and_process_name_changes(supabase: Client, db_rsn_map_normalized: dict, dry_run: bool, report_lines: list) -> (dict, list):
    log.info("Fetching group name changes from WOM...")
    url = f"https://api.wiseoldman.net/v2/groups/{WOM_GROUP_ID}/name-changes"
    headers = {"User-Agent": "OnlyFEs-Clan-Bot-v1.0", "x-api-key": WOM_API_KEY}
    
    report_name_changes = []
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        name_changes = response.json()
        log.info(f"Found {len(name_changes)} name changes to process.")
        
        if not name_changes:
            return db_rsn_map_normalized, report_name_changes

        for change in name_changes:
            old_name = change['oldName']
            new_name = change['newName']
            old_norm = normalize_string(old_name)
            new_norm = normalize_string(new_name)

            if old_norm in db_rsn_map_normalized:
                member_id = db_rsn_map_normalized[old_norm]['member_id']
                original_db_rsn = db_rsn_map_normalized[old_norm]['original_rsn']

                # --- FIX: Check if new name is already linked to this member ---
                if new_norm in db_rsn_map_normalized:
                    existing_entry = db_rsn_map_normalized[new_norm]
                    existing_member_id = existing_entry['member_id']
                    
                    if existing_member_id == member_id:
                        # Check if we are just reverting to an old name (A -> B -> A)
                        # If existing entry is NOT primary, we need to swap it back to primary
                        if not existing_entry['is_primary']:
                            report_lines.append(f"Processing name revert: {old_name} -> {new_name} (Swapping primary)")
                            report_name_changes.append(f"{old_name} -> {new_name} (Revert)")
                            
                            if not dry_run:
                                try:
                                    # 1. Set the OLD name (which was primary) to non-primary
                                    supabase.table('member_rsns').update({'is_primary': False})\
                                        .eq('member_id', member_id)\
                                        .eq('rsn', original_db_rsn)\
                                        .execute()
                                        
                                    # 2. Set the NEW (existing) name to primary
                                    # Use the stored original RSN from the DB map to match exactly
                                    target_rsn_str = existing_entry['original_rsn']
                                    supabase.table('member_rsns').update({'is_primary': True})\
                                        .eq('member_id', member_id)\
                                        .eq('rsn', target_rsn_str)\
                                        .execute()
                                except Exception as e:
                                    report_lines.append(f"  > ERROR: Failed to swap primary status for {old_name} -> {new_name}. {e}")
                                    continue

                            # Update local map to reflect the swap
                            if old_norm in db_rsn_map_normalized:
                                db_rsn_map_normalized[old_norm]['is_primary'] = False
                            db_rsn_map_normalized[new_norm]['is_primary'] = True
                            
                            continue

                        else:
                            # It's already primary? Then we truly have already processed this.
                            log.warning(f"Skipping name change {old_name} -> {new_name} (Already processed).")
                            continue
                # ---------------------------------------------------------------

                report_lines.append(f"Processing name change: {old_name} -> {new_name}")
                report_name_changes.append(f"{old_name} -> {new_name}")

                try:
                    if old_norm == new_norm:
                        if not dry_run:
                            supabase.table('member_rsns').update({'rsn': new_name})\
                                .eq('member_id', member_id)\
                                .eq('rsn', original_db_rsn)\
                                .execute()
                        db_rsn_map_normalized[new_norm]['original_rsn'] = new_name
                    
                    else:
                        if not dry_run:
                            supabase.table('member_rsns').update({'is_primary': False})\
                                .eq('member_id', member_id)\
                                .eq('is_primary', True)\
                                .execute()
                            
                            supabase.table('member_rsns').insert({
                                'member_id': member_id,
                                'rsn': new_name,
                                'is_primary': True
                            }).execute()
                        
                        db_rsn_map_normalized.pop(old_norm, None)
                        db_rsn_map_normalized[new_norm] = {
                            "member_id": member_id, 
                            "is_primary": True, 
                            "original_rsn": new_name
                        }
                
                except Exception as e:
                    report_lines.append(f"  > ERROR: Failed to update name change for {old_name}. {e}")
                    report_name_changes.pop()

    except Exception as e:
        report_lines.append(f"CRITICAL ERROR: Failed to fetch WOM name changes: {e}")
    
    return db_rsn_map_normalized, report_name_changes

# --- 5. SYNC LOGIC (This is the function bot.py calls) ---

def run_sync(supabase: Client, dry_run: bool = True, force_run: bool = False) -> str:
    report_lines = []
    run_mode = "DRY RUN" if dry_run else "LIVE RUN"
    report_lines.append(f"--- Starting Roster Reconciliation ({run_mode}) ---")
    
    if force_run:
        report_lines.append("--- WARNING: Force run enabled. Bypassing rank mismatch safety check. ---")

    # 1. FETCH ALL DATA
    ranks_map_normalized, ranks_map_by_id, db_rsn_map_normalized = fetch_db_ranks_and_rsns(supabase)
    db_member_data = fetch_db_member_data(supabase)
    all_db_members = fetch_all_db_members(supabase)  # Fetch ALL members including inactive
    wom_members, group_snapshot_data = fetch_wom_members()
    
    if not all([wom_members, ranks_map_normalized, db_member_data, db_rsn_map_normalized, all_db_members]):
        report_lines.append("CRITICAL ERROR: Halting sync due to data fetching error. Check console logs.")
        return "\n".join(report_lines)
    
    # 1.5. INSERT GROUP SNAPSHOT
    if group_snapshot_data:
        if not dry_run:
            try:
                supabase.table('group_snapshots').insert({
                    'snapshot_data': group_snapshot_data
                }).execute()
                log.info("Group snapshot inserted successfully.")
            except Exception as e:
                report_lines.append(f"Warning: Failed to insert group snapshot: {e}")
        else:
            log.info("[DRY RUN] Would insert group snapshot.")

    # 2. PROCESS NAME CHANGES
    db_rsn_map_normalized, report_name_changes = fetch_and_process_name_changes(
        supabase, db_rsn_map_normalized, dry_run, report_lines
    )

    # 3. ENRICH WOM DATA
    fetch_player_snapshots(supabase, wom_members, db_member_data, db_rsn_map_normalized, dry_run)
        
    wom_normalized_rsns = set(wom_members.keys())
    
    # 3.5. BUILD SNAPSHOTS PAYLOAD
    snapshots_payload = []
    for normalized_rsn, wom_member in wom_members.items():
        snapshot = wom_member.get('latest_snapshot')
        if snapshot:
            member_id = db_rsn_map_normalized.get(normalized_rsn, {}).get('member_id')
            if member_id:
                snapshot_data = snapshot.get('data', {})
                skills_data = snapshot_data.get('skills', {})
                overall_data = skills_data.get('overall', {})
                
                snapshots_payload.append({
                    'member_id': member_id,
                    'total_xp': overall_data.get('experience', 0),
                    'total_level': overall_data.get('level', 0),
                    'ehp': snapshot_data.get('computed', {}).get('ehp', {}).get('value', 0),
                    'ehb': snapshot_data.get('computed', {}).get('ehb', {}).get('value', 0),
                    'full_json_payload': snapshot
                })
    
    # 4. CALCULATE "DIFF"
    wom_member_ids_present = set()
    for rsn in wom_normalized_rsns:
        member_id = db_rsn_map_normalized.get(rsn, {}).get('member_id')
        if member_id:
            wom_member_ids_present.add(member_id)

    all_active_db_member_ids = set(db_member_data.keys())
    new_normalized_rsns = wom_normalized_rsns - set(db_rsn_map_normalized.keys())
    departed_member_ids = all_active_db_member_ids - wom_member_ids_present
    
    # 5. PREPARE REPORTS
    report_newly_added = []
    report_deactivated = []
    report_rank_mismatches = []
    report_promo_emerald = []
    report_promo_ruby = []
    new_members_payload = []
    report_auto_rank_updates = []
    today = datetime.now(timezone.utc)

    # A: Process New Members
    for rsn in new_normalized_rsns:
        member = wom_members[rsn]
        rank_name = member['rank']
        normalized_rank_name = normalize_string(rank_name)
        rank_id = ranks_map_normalized.get(normalized_rank_name)
        
        if not rank_id:
            report_lines.append(f"Note: Rank '{rank_name}' (normalized: '{normalized_rank_name}') not found.")
            if not dry_run:
                try:
                    new_rank_data = supabase.table('ranks').insert({
                        "name": rank_name,
                        "rank_type": 'Other'
                    }).execute().data[0]
                    rank_id = new_rank_data['id']
                    ranks_map_normalized[normalized_rank_name] = rank_id
                    report_lines.append(f"  > Successfully created new 'Other' rank: {rank_name}")
                except Exception as e:
                    report_lines.append(f"  > ERROR: Could not create new rank '{rank_name}'. {e}")
        
        # Prepare new member payload
        latest_xp = 0
        snapshot = member.get('latest_snapshot')
        if snapshot:
            latest_xp = snapshot.get('data', {}).get('skills', {}).get('overall', {}).get('experience', 0)
        elif member.get('stale_exp'):
            latest_xp = member.get('stale_exp')

        new_members_payload.append({
            "rsn": member['rsn'],
            "date_joined": today.isoformat(),
            "current_rank_id": rank_id,
            "latest_db_xp": latest_xp,
            "status": 'Active'
        })
        
        report_newly_added.append(f"{member['rsn']} (Rank: {rank_name})")
        
    # B: Process Returning Members (inactive in DB, present in WOM) - PRIMARY RSNs ONLY
    report_returning_members = []
    returning_members_payload = []
    
    for normalized_rsn in wom_normalized_rsns:
        if normalized_rsn in db_rsn_map_normalized and normalized_rsn not in new_normalized_rsns:
            # CRITICAL: Only process PRIMARY RSNs to avoid alt accounts triggering reactivation
            if not db_rsn_map_normalized[normalized_rsn]['is_primary']:
                continue  # Skip non-primary RSNs
            
            member_id = db_rsn_map_normalized[normalized_rsn]['member_id']
            if member_id in all_db_members and all_db_members[member_id]['status'] == 'Inactive':
                # This member is inactive in DB but present in WOM - they've returned!
                wom_member = wom_members[normalized_rsn]
                wom_rank_name = wom_member['rank']
                normalized_wom_rank = normalize_string(wom_rank_name)
                new_rank_id = ranks_map_normalized.get(normalized_wom_rank)
                old_rank_id = all_db_members[member_id]['current_rank_id']
                
                if new_rank_id:
                    returning_members_payload.append({
                        'member_id': member_id,
                        'old_rank_id': old_rank_id,
                        'new_rank_id': new_rank_id
                    })
                    old_rank_name = ranks_map_by_id.get(old_rank_id, 'Unknown')
                    report_returning_members.append(f"{wom_member['rsn']}: {old_rank_name} -> {wom_rank_name}")
    
    # C: Check Rank Mismatches for Existing Active Members (PRIMARY RSNs ONLY)
    for normalized_rsn in wom_normalized_rsns:
        if normalized_rsn in db_rsn_map_normalized and normalized_rsn not in new_normalized_rsns:
            # CRITICAL: Only check rank for PRIMARY RSNs to avoid alt accounts overwriting rank
            if not db_rsn_map_normalized[normalized_rsn]['is_primary']:
                continue  # Skip non-primary RSNs
            
            member_id = db_rsn_map_normalized[normalized_rsn]['member_id']
            if member_id in db_member_data:  # Active member
                wom_member = wom_members[normalized_rsn]
                wom_rank_name = wom_member['rank']
                normalized_wom_rank = normalize_string(wom_rank_name)
                wom_rank_id = ranks_map_normalized.get(normalized_wom_rank)
                db_rank_id = db_member_data[member_id]['current_rank_id']
                
                if wom_rank_id and wom_rank_id != db_rank_id:
                    # Rank mismatch detected!
                    db_rank_name = ranks_map_by_id.get(db_rank_id, 'Unknown')
                    report_rank_mismatches.append(f"{wom_member['rsn']}: DB says '{db_rank_name}', WOM says '{wom_rank_name}'")

    # D: Check for emerald rankups (Sapphire rank and joined over 28 days ago)
    for member_id in db_member_data:
        if member_id in db_member_data:
            member = db_member_data[member_id]
            if member['current_rank_id'] == ranks_map_by_id[10] and member['date_joined'] > (today - timedelta(days=28)):
                report_promo_emerald.append(f"{member['rsn']}")

    # E: Check for ruby rankups (Emerald rank and joined over 56 days ago with 1250 total level)
    for member_id in db_member_data:
        if member_id in db_member_data:
            member = db_member_data[member_id]
            if member['current_rank_id'] == ranks_map_by_id[11] and member['date_joined'] > (today - timedelta(days=56)) and member['total_level'] >= 1250:
                report_promo_ruby.append(f"{member['rsn']}")
    
    # --- 6. CIRCUIT BREAKER CHECK ---
    report_lines.append("\n--- Running Safety Checks ---")
    report_lines.append(f"Found {len(report_rank_mismatches)} rank mismatches.")
    for report in report_rank_mismatches:
        report_lines.append(f"  - {report}")
    mismatch_count = len(report_rank_mismatches)
    
    if force_run:
        report_lines.append(f"Found {mismatch_count} mismatches. Bypassing Safety Checks as force_run=True was specified.")
    
    elif mismatch_count > MISMATCH_THRESHOLD:
        report_lines.append(f"\n\n--- !!! SYNC HALTED: CIRCUIT BREAKER TRIGGERED !!! ---")
        report_lines.append(f"Found {mismatch_count} rank mismatches, which is over the threshold of {MISMATCH_THRESHOLD}.")
        report_lines.append("\nACTION: Please run an in-game WOM sync, wait 5 minutes, and try again.")
        report_lines.append("If this is intentional, run /sync-clan with force_run=True.\n")
        report_lines.append("--- Mismatch Report ---")
        for report in report_rank_mismatches:
            report_lines.append(f"  - {report}")
        report_lines.append("\n--- NO CHANGES HAVE BEEN MADE TO THE DATABASE ---")
        return "\n".join(report_lines)

    else:
        report_lines.append(f"Found {mismatch_count} mismatches. (Under threshold of {MISMATCH_THRESHOLD}). Proceeding with sync.")

    # --- 7. FORCE RANK UPDATES (if enabled) ---
    if force_run and report_rank_mismatches:
        report_lines.append("\n--- 🤖 EXECUTING FORCED RANK UPDATES ---")
        rank_history_payload = []
        
        for report_str in report_rank_mismatches:
            match = re.match(r"(.+?): DB says '(.+?)', WOM says '(.+?)'", report_str)
            if not match:
                continue
            
            rsn, db_rank, wom_rank = match.groups()
            
            try:
                normalized_rsn = normalize_string(rsn)
                member_id = db_rsn_map_normalized[normalized_rsn]['member_id']
                old_rank_id = db_member_data[member_id]['current_rank_id']
                normalized_wom_rank = normalize_string(wom_rank)
                new_rank_id = ranks_map_normalized.get(normalized_wom_rank)

                if not new_rank_id:
                    report_lines.append(f"  - ERROR: Cannot update {rsn}. Rank '{wom_rank}' is unknown.")
                    continue

                if not dry_run:
                    supabase.table('members').update({'current_rank_id': new_rank_id}).eq('id', member_id).execute()
                    rank_history_payload.append({
                        'member_id': member_id, 
                        'new_rank_id': new_rank_id, 
                        'previous_rank_id': old_rank_id
                    })
                report_auto_rank_updates.append(f"{rsn}: {db_rank} -> {wom_rank}")
            except Exception as e:
                report_lines.append(f"  - ERROR: Failed to auto-update rank for {rsn}: {e}")

        if not dry_run and rank_history_payload:
            try:
                supabase.table('rank_history').insert(rank_history_payload).execute()
            except Exception as e:
                report_lines.append(f"  - ERROR: Failed to insert rank history: {e}")
        
        report_rank_mismatches = [] 

    # --- 8. EXECUTE DB WRITES (if not dry_run) ---
    if not dry_run:
        report_lines.append("\n--- EXECUTING LIVE DATABASE WRITES ---")
        
        # A: Process New Members
        if new_members_payload:
            report_lines.append(f"Adding {len(new_members_payload)} new members...")
            db_members_payload = []
            for m in new_members_payload:
                db_members_payload.append({k: v for k, v in m.items() if k not in ['rsn', 'latest_db_xp']})
            try:
                inserted_members = supabase.table('members').insert(db_members_payload).execute().data
                new_rsns_payload = []
                new_ranks_payload = []
                for i, member_data in enumerate(inserted_members):
                    new_rsns_payload.append({"member_id": member_data['id'], "rsn": new_members_payload[i]['rsn'], "is_primary": True})
                    new_ranks_payload.append({"member_id": member_data['id'], "new_rank_id": member_data['current_rank_id']})
                if new_rsns_payload:
                    supabase.table('member_rsns').insert(new_rsns_payload).execute()
                if new_ranks_payload:
                    supabase.table('rank_history').insert(new_ranks_payload).execute()
                report_lines.append("New member processing complete.")
            except Exception as e:
                report_lines.append(f"ERROR processing new members: {e}")

        # A2: Process Returning Members
        if returning_members_payload:
            report_lines.append(f"Reactivating {len(returning_members_payload)} returning members...")
            try:
                rank_history_payload = []
                for returning_member in returning_members_payload:
                    member_id = returning_member['member_id']
                    new_rank_id = returning_member['new_rank_id']
                    old_rank_id = returning_member['old_rank_id']
                    
                    # Reactivate and update rank
                    supabase.table('members').update({
                        'status': 'Active',
                        'current_rank_id': new_rank_id
                    }).eq('id', member_id).execute()
                    
                    # Add rank history
                    rank_history_payload.append({
                        'member_id': member_id,
                        'previous_rank_id': old_rank_id,
                        'new_rank_id': new_rank_id
                    })
                
                if rank_history_payload:
                    supabase.table('rank_history').insert(rank_history_payload).execute()
                
                report_lines.append("Returning member processing complete.")
            except Exception as e:
                report_lines.append(f"ERROR processing returning members: {e}")

        # B: Process Departed Members
        if departed_member_ids:
            report_lines.append(f"Deactivating {len(report_deactivated)} departed members...")
            try:
                supabase.table('members').update({"status": 'Inactive'}).in_('id', list(departed_member_ids)).execute()
                report_lines.append("Deactivation complete.")
            except Exception as e:
                report_lines.append(f"ERROR deactivating members: {e}")
        
        # C: Process Snapshots
        try:
            if snapshots_payload:
                report_lines.append(f"Inserting {len(snapshots_payload)} stat snapshots...")
                supabase.table('wom_snapshots').insert(snapshots_payload).execute()
                report_lines.append("Snapshot insertion complete.")
            else:
                report_lines.append("No new snapshots to insert.")
        except Exception as e:
            report_lines.append(f"Error inserting snapshots: {e}")
            
    else:
        report_lines.append("\n--- (DRY RUN) SKIPPING ALL DATABASE WRITES ---")
        report_lines.append(f"Would add {len(report_newly_added)} new members.")
        report_lines.append(f"Would reactivate {len(returning_members_payload)} returning members.")
        report_lines.append(f"Would deactivate {len(report_deactivated)} members.")
        report_lines.append(f"Would insert {len(snapshots_payload)} stat snapshots.")
        if report_auto_rank_updates:
            report_lines.append(f"Would force-update {len(report_auto_rank_updates)} mismatched ranks.")

        
    report_lines.append("\n--- 💎 Staff Action Required: Pending Promotions ---")
    report_lines.append("Promote in-game, then run /rankup <rsn> <rank>")
    if report_promo_emerald:
        report_lines.append("\n  Sapphire -> Emerald (>= 28 days):")
        for report in report_promo_emerald:
            report_lines.append(f"    - {report}")
    if report_promo_ruby:
        report_lines.append("\n  Emerald -> Ruby (>= 56 days & 1250+ total):")
        for report in report_promo_ruby:
            report_lines.append(f"    - {report}")
    if not report_promo_emerald and not report_promo_ruby:
        report_lines.append("  No pending auto-promotions found.")
        
    report_lines.append(f"\n--- Sync Complete ({run_mode}) ---")
    
    return "\n".join(report_lines)

# --- 6. RUN THE SCRIPT (for manual testing) ---
if __name__ == "__main__":
    import sys
    
    is_dry_run = True
    is_force_run = False
    
    if "--live" in sys.argv:
        is_dry_run = False
    if "--force" in sys.argv:
        is_dry_run = False
        is_force_run = True

    try:
        supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        log.info("Supabase connection successful for manual run.")
        
        report = run_sync(supabase_client, dry_run=is_dry_run, force_run=is_force_run)
        log.info(report)
        
    except Exception as e:
        log.error(f"Error initializing Supabase: {e}")