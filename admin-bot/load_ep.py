import os
import csv
from supabase import create_client, Client

# --- PASTE YOUR KEYS HERE ---
SUPABASE_URL = "https://jprtvhnqghhkjuabwxqq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpwcnR2aG5xZ2hoa2p1YWJ3eHFxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjMxNzY0MzMsImV4cCI6MjA3ODc1MjQzM30.YMtbY734FJFlNN92RkE7q-f5JuMRfg0llrjZoX8mvRI"
# -----------------------------

CSV_FILE_NAME = "OnlyFEs Event Points Tracker - Tracker.csv"

def get_member_rsn_map(supabase: Client) -> dict:
    """
    Fetches all members and their primary RSNs from the DB.
    Returns a simple dictionary mapping: {"rsn_lowercase": "member_id"}
    """
    print("Fetching RSN-to-MemberID map from database...")
    try:
        response = supabase.table('member_rsns').select('rsn, member_id').eq('is_primary', True).execute()
        rsn_map = {}
        for item in response.data:
            normalized_rsn = item['rsn'].lower().strip()
            rsn_map[normalized_rsn] = item['member_id']
        print(f"Successfully loaded {len(rsn_map)} RSNs.")
        return rsn_map
    except Exception as e:
        print(f"Error fetching RSNs: {e}")
        return None

def parse_ep_csv(file_name: str) -> list:
    """
    Reads the EP Tracker CSV and returns a list of transactions.
    """
    transactions_to_add = []
    print(f"Reading data from {file_name}...")
    try:
        with open(file_name, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None) # Skip header
            for row in reader:
                if len(row) >= 2 and row[0].strip():
                    rsn = row[0].strip()
                    try:
                        points = int(row[1].strip())
                        if points > 0:
                            transactions_to_add.append({"rsn": rsn, "points": points})
                    except ValueError:
                        print(f"Warning: Could not parse points for {rsn} (value: '{row[1]}'). Skipping.")
    except FileNotFoundError:
        print(f"Error: {file_name} not found.")
        return None
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return None
    print(f"Found {len(transactions_to_add)} members with EP in CSV.")
    return transactions_to_add

def main():
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Error connecting to Supabase: {e}")
        return

    rsn_map = get_member_rsn_map(supabase)
    if not rsn_map:
        return

    transactions_to_add = parse_ep_csv(CSV_FILE_NAME)
    if not transactions_to_add:
        return

    print(f"\n--- STARTING EP DATA LOAD (v2) ---")
    not_found_list = []
    ep_payload = []

    for item in transactions_to_add:
        rsn = item["rsn"]
        points = item["points"]
        normalized_rsn = rsn.lower().strip()
        
        member_id = rsn_map.get(normalized_rsn)
        
        # --- NEW LOGIC ---
        if not member_id and '/' in normalized_rsn:
            # RSN not found, check if it's a "person/alt" RSN
            print(f"Note: '{rsn}' not found. Checking for primary RSN...")
            primary_rsn = normalized_rsn.split('/')[0].strip()
            member_id = rsn_map.get(primary_rsn)
            
            if member_id:
                print(f"  > Found match! Linking '{rsn}' EP to '{primary_rsn}'.")
        # --- END NEW LOGIC ---

        if not member_id:
            print(f"Warning: RSN '{rsn}' not found in member list. Skipping.")
            not_found_list.append(rsn)
            continue

        ep_payload.append({
            'member_id': member_id,
            'modification': points,
            'reason': 'Initial EP balance load'
        })

    print(f"\nFound {len(ep_payload)} valid transactions. Inserting into database...")
    try:
        response = supabase.table('event_point_transactions').insert(ep_payload).execute()
        success_count = len(response.data)
        fail_count = 0
    except Exception as e:
        print(f"--> FAILED to insert EP batch: {e}")
        success_count = 0
        fail_count = len(ep_payload)

    print("\n--- EP DATA LOAD COMPLETE ---")
    print(f"Successfully added: {success_count}")
    print(f"Failed to add: {fail_count}")
    print(f"RSNs not found ({len(not_found_list)}): {not_found_list}")

if __name__ == "__main__":
    main()