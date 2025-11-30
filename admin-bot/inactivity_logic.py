import os
import requests
import time
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from supabase import create_client, Client
import logging
# Ensure this line is placed early in your bot.py
logging.basicConfig(level=logging.INFO, 
                    format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')

# Initialize the logger for your bot's custom messages
log = logging.getLogger('ClanBot') # Give your bot a specific name

# Load environment variables
load_dotenv()

WOM_API_KEY = os.getenv("WOM_API_KEY")
WOM_HEADERS = {
    "User-Agent": "OnlyFEs-Clan-Bot-v1.0",
    "x-api-key": WOM_API_KEY
}

# Rate limiting configuration
MAX_REQUESTS_PER_MINUTE = 90
REQUEST_WINDOW_SECONDS = 60

# Rank tiers that get 30-day check (others get 60-day)
SHORT_PERIOD_RANKS = ['sapphire', 'emerald', 'ruby']


def get_active_members_with_snapshots(supabase: Client) -> list:
    """
    Fetches all active clan members with their current rank, latest snapshot, and join date.
    Uses a database function for efficiency if available, otherwise falls back to manual query.
    
    Returns:
        list: List of dicts with member_id, rsn, rank_name, rank_id, latest_xp, date_joined
    """
    log.info("Fetching active members with snapshots...")
    
    try:
        # Try to use RPC function first (more efficient)
        response = supabase.rpc('get_active_member_snapshots').execute()
        
        members = []
        for member in response.data:
            members.append({
                'member_id': member['id'],
                'rsn': None,  # Will be fetched separately
                'rank_id': member['current_rank_id'],
                'rank_name': None,  # Will be fetched separately
                'latest_xp': member.get('latest_db_xp', 0),
                'date_joined': member.get('date_joined')  # Already in RPC response!
            })
        
        # Fetch RSNs
        rsn_response = supabase.table('member_rsns').select('member_id, rsn').eq('is_primary', True).execute()
        rsn_map = {item['member_id']: item['rsn'] for item in rsn_response.data}
        
        # Fetch rank names
        rank_response = supabase.table('ranks').select('id, name').execute()
        rank_map = {item['id']: item['name'] for item in rank_response.data}
        
        # Enrich members with RSN and rank name
        for member in members:
            member['rsn'] = rsn_map.get(member['member_id'], 'Unknown')
            member['rank_name'] = rank_map.get(member['rank_id'], 'Unknown')
        
        log.info(f"Found {len(members)} active members.")
        return members
        
    except Exception as e:
        log.error(f"Error fetching active members: {e}")
        return []


def get_historical_snapshot(supabase: Client, member_id: str, days_ago: int, max_lookback: int = 5) -> dict:
    """
    Retrieves a historical snapshot for a member from approximately N days ago.
    If exact day not found, tries N+1, N+2, etc. up to max_lookback additional days.
    
    Args:
        supabase: Supabase client
        member_id: The member's ID
        days_ago: Target number of days ago
        max_lookback: Maximum additional days to search
    
    Returns:
        dict: Snapshot data with total_xp and snapshot_date, or None if not found
    """
    target_date = datetime.now(timezone.utc) - timedelta(days=days_ago)
    
    for offset in range(max_lookback + 1):
        check_date = target_date - timedelta(days=offset)
        start_of_day = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = check_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        try:
            response = supabase.table('wom_snapshots') \
                .select('total_xp, snapshot_date') \
                .eq('member_id', member_id) \
                .gte('snapshot_date', start_of_day.isoformat()) \
                .lte('snapshot_date', end_of_day.isoformat()) \
                .order('snapshot_date', desc=True) \
                .limit(1) \
                .execute()
            
            if response.data:
                return response.data[0]
        except Exception as e:
            log.error(f"  Error querying snapshot for member {member_id}: {e}")
            continue
    
    return None


def find_last_activity_from_wom(rsn: str, baseline_xp: int, lookback_days: int = 30) -> int:
    """
    Queries WOM API to find when the player last gained XP.
    Paginates through snapshots to find the last XP change.
    
    Args:
        rsn: Player's RSN
        baseline_xp: The current XP (not used in this implementation)
        lookback_days: How many days to look back from now (default 30)
    
    Returns:
        int: Days since last XP gain, or -1 if not found (meaning >lookback_days)
    """
    log.info(f"  Checking WOM API for last activity of {rsn}...")
    
    # Use snapshots endpoint with pagination
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=lookback_days)
    
    url = f"https://api.wiseoldman.net/v2/players/{rsn}/snapshots"
    
    offset = 0
    limit = 50
    
    while True:
        params = {
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "limit": limit,
            "offset": offset
        }
        
        try:
            response = requests.get(url, headers=WOM_HEADERS, params=params)
            response.raise_for_status()
            snapshots = response.json()
            
            if not snapshots:
                # No more snapshots to check
                return -1
            
            # Sort snapshots by date (newest first)
            snapshots.sort(key=lambda x: x['createdAt'], reverse=True)
            
            # Find the most recent day where XP increased from previous day
            for i in range(len(snapshots) - 1):
                current = snapshots[i]
                previous = snapshots[i + 1]
                
                current_xp = current.get('data', {}).get('skills', {}).get('overall', {}).get('experience', 0)
                previous_xp = previous.get('data', {}).get('skills', {}).get('overall', {}).get('experience', 0)
                
                # If current XP is higher than previous, they gained XP on this snapshot's date
                if current_xp > previous_xp:
                    snapshot_date = datetime.fromisoformat(current['createdAt'].replace('Z', '+00:00'))
                    days_ago = (datetime.now(timezone.utc) - snapshot_date).days
                    return days_ago
            
            # If we got fewer results than the limit, we've reached the end
            if len(snapshots) < limit:
                return -1
            
            # Move to next page
            offset += limit
            time.sleep(0.1)  # Small delay between paginated requests
            
        except Exception as e:
            log.error(f"  Error querying WOM API for {rsn}: {e}")
            return -1


def check_inactivity(supabase: Client, members: list) -> dict:
    """
    Checks each member for inactivity by examining their recent snapshot history.
    Since snapshots are only created when XP is gained, we can detect inactivity by:
    1. Checking if they only have 1 snapshot (new member or never logged in)
    2. Checking if latest snapshot is >30/60 days old
    3. Checking if XP hasn't changed across recent snapshots (data issue)
    
    Args:
        supabase: Supabase client
        members: List of member dicts from get_active_members_with_snapshots()
    
    Returns:
        dict: {'inactive': [...], 'at_risk': [...]}
    """
    log.info("\nChecking for inactive members...")
    inactive_members = []
    at_risk_members = []
    request_count = 0
    start_time = time.time()
    
    for idx, member in enumerate(members, 1):
        rsn = member['rsn']
        rank_name = member['rank_name'].lower()
        current_xp = member['latest_xp']
        
        # Determine lookback period based on rank
        days_threshold = 30 if rank_name in SHORT_PERIOD_RANKS else 60
        at_risk_threshold = days_threshold - 5  # 5 days before threshold
        
        log.info(f"[{idx}/{len(members)}] Checking {rsn} ({rank_name}, {days_threshold}-day threshold)...")
        
        # Get most recent 5 snapshots for this member
        try:
            snapshots_response = supabase.table('wom_snapshots') \
                .select('total_xp, snapshot_date') \
                .eq('member_id', member['member_id']) \
                .order('snapshot_date', desc=True) \
                .limit(5) \
                .execute()
            
            snapshots = snapshots_response.data
            
            if not snapshots:
                log.warning(f"  No snapshots found for {rsn}, skipping.")
                continue
            
            needs_wom_verification = False
            reason = ""
            
            # Flag 1: Only has 1 snapshot (new member or never logged in after joining)
            if len(snapshots) == 1:
                needs_wom_verification = True
                reason = "only 1 snapshot"
            
            # Flag 2: Latest snapshot is older than threshold
            if not needs_wom_verification:
                latest_snapshot_date = datetime.fromisoformat(snapshots[0]['snapshot_date'].replace('Z', '+00:00'))
                days_since_latest = (datetime.now(timezone.utc) - latest_snapshot_date).days
                
                if days_since_latest > days_threshold:
                    needs_wom_verification = True
                    reason = f"latest snapshot is {days_since_latest} days old"
            
            # Flag 3: XP hasn't changed across snapshots (data integrity issue)
            if not needs_wom_verification and len(snapshots) > 1:
                xp_values = [s['total_xp'] for s in snapshots]
                if len(set(xp_values)) == 1:  # All XP values are the same
                    needs_wom_verification = True
                    reason = "XP unchanged across snapshots"
            
            # If flagged, verify with WOM API
            if needs_wom_verification:
                log.warning(f"  ⚠️ {rsn} flagged for WOM verification ({reason})")
                
                # Rate limiting
                if request_count >= MAX_REQUESTS_PER_MINUTE:
                    elapsed = time.time() - start_time
                    if elapsed < REQUEST_WINDOW_SECONDS:
                        wait_time = REQUEST_WINDOW_SECONDS - elapsed + 1
                        log.info(f"\n⏳ Rate limit reached. Sleeping for {wait_time:.1f} seconds...")
                        time.sleep(wait_time)
                    request_count = 0
                    start_time = time.time()
                
                # Use current XP as baseline for WOM check
                # Look back threshold + 30 days to catch activity slightly beyond the threshold
                wom_lookback = days_threshold + 30
                days_inactive = find_last_activity_from_wom(rsn, current_xp, lookback_days=wom_lookback)
                request_count += 1
                
                # If no activity found in WOM lookback, report as >wom_lookback
                if days_inactive == -1:
                    days_inactive = f">{wom_lookback}"
                
                member_data = {
                    'rsn': rsn,
                    'rank_name': member['rank_name'],
                    'days_inactive': days_inactive,
                    'latest_xp': current_xp,
                    'date_joined': member.get('date_joined'),
                    'days_threshold': days_threshold
                }
                
                # Categorize as inactive or at-risk
                if isinstance(days_inactive, str):  # ">X" format
                    inactive_members.append(member_data)
                    log.info(f"  ⚠️ Confirmed inactive: {days_inactive} days")
                elif days_inactive >= days_threshold:  # Changed to >= to include threshold
                    inactive_members.append(member_data)
                    log.info(f"  ⚠️ Confirmed inactive: {days_inactive} days")
                elif days_inactive >= at_risk_threshold:
                    at_risk_members.append(member_data)
                    log.info(f"  ⚠️ At risk: {days_inactive} days")
                else:
                    log.info(f"  ✓ WOM check shows recent activity ({days_inactive} days ago)")
                
                time.sleep(0.1)
            else:
                log.info(f"  ✓ {rsn} has recent snapshots, active")
                
        except Exception as e:
            log.error(f"  Error checking {rsn}: {e}")
            continue
    
    return {'inactive': inactive_members, 'at_risk': at_risk_members}


def generate_inactivity_report(result: dict) -> str:
    """
    Generates a formatted text report of inactive and at-risk members.
    
    Args:
        result: Dict with 'inactive' and 'at_risk' lists
    
    Returns:
        str: Formatted report text
    """
    inactive_members = result['inactive']
    at_risk_members = result['at_risk']
    
    # Sort function to handle both numeric and ">X" string values
    def sort_key(member):
        days = member['days_inactive']
        if isinstance(days, str) and days.startswith('>'):
            return 9999  # Put ">X" values at the top (most inactive)
        return days
    
    # Sort both lists by days inactive (descending - most inactive first)
    inactive_members = sorted(inactive_members, key=sort_key, reverse=True)
    at_risk_members = sorted(at_risk_members, key=sort_key, reverse=True)
    
    report_lines = []
    report_lines.append("Inactive Members Report")
    report_lines.append("")
    
    # Eligible for Removal section
    if inactive_members:
        report_lines.append(f"Eligible for Removal ({len(inactive_members)})")
        for member in inactive_members:
            rank_name = member['rank_name'].title()  # Capitalize properly
            xp_formatted = f"{member['latest_xp'] / 1_000_000:.1f}m XP"
            days_inactive = member['days_inactive']
            
            # Calculate days in clan
            if member.get('date_joined'):
                joined_date = datetime.fromisoformat(member['date_joined'].replace('Z', '+00:00'))
                days_in_clan = (datetime.now(timezone.utc) - joined_date).days
            else:
                days_in_clan = "?"
            
            report_lines.append(f"{member['rsn']} | {rank_name} | {xp_formatted} | {days_inactive} days inactive | {days_in_clan} days in clan")
        report_lines.append("")
    
    # Approaching Inactivity Criteria section
    if at_risk_members:
        report_lines.append("Approaching Inactivity Criteria")
        report_lines.append("")
        report_lines.append(f"At Risk ({len(at_risk_members)})")
        for member in at_risk_members:
            rank_name = member['rank_name'].title()  # Capitalize properly
            xp_formatted = f"{member['latest_xp'] / 1_000_000:.1f}m XP"
            days_inactive = member['days_inactive']
            
            # Calculate days in clan
            if member.get('date_joined'):
                joined_date = datetime.fromisoformat(member['date_joined'].replace('Z', '+00:00'))
                days_in_clan = (datetime.now(timezone.utc) - joined_date).days
            else:
                days_in_clan = "?"
            
            report_lines.append(f"{member['rsn']} | {rank_name} | {xp_formatted} | {days_inactive} days inactive | {days_in_clan} days in clan")
        report_lines.append("")
    
    if not inactive_members and not at_risk_members:
        report_lines.append("✅ No inactive or at-risk members found!")
        report_lines.append("")
    
    return "\n".join(report_lines)


def run_inactivity_check(supabase: Client) -> str:
    """
    Main orchestration function that runs the full inactivity check.
    
    Args:
        supabase: Supabase client
    
    Returns:
        str: Formatted report text
    """
    log.info("Starting inactivity check...")
    
    # Step 1: Get all active members with their snapshots
    members = get_active_members_with_snapshots(supabase)
    
    if not members:
        return "Error: Could not fetch active members."
    
    # Step 2: Check each member for inactivity
    result = check_inactivity(supabase, members)
    
    # Step 3: Generate report
    report = generate_inactivity_report(result)
    
    log.info("\nInactivity check complete!")
    return report


# --- Standalone execution for testing ---
if __name__ == "__main__":
    log.info("Running inactivity check in standalone mode...\n")
    
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    
    if not all([SUPABASE_URL, SUPABASE_KEY, WOM_API_KEY]):
        log.error("Error: Missing required environment variables.")
        log.error("Required: SUPABASE_URL, SUPABASE_KEY, WOM_API_KEY")
        exit(1)
    
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        log.info("✓ Connected to Supabase\n")
        
        report = run_inactivity_check(supabase)
        log.info("\n" + report)
        
    except Exception as e:
        import traceback
        log.error(traceback.format_exc())
