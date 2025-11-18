import os
import csv
from supabase import create_client, Client
from dateutil.parser import parse

# --- PASTE YOUR KEYS HERE ---
SUPABASE_URL = "https://jprtvhnqghhkjuabwxqq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpwcnR2aG5xZ2hoa2p1YWJ3eHFxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjMxNzY0MzMsImV4cCI6MjA3ODc1MjQzM30.YMtbY734FJFlNN92RkE7q-f5JuMRfg0llrjZoX8mvRI"
# -----------------------------

# The name of your CSV file
CSV_FILE_NAME = "OnlyFEs Join Dates - Table.csv"

def get_ranks_map(supabase: Client) -> dict:
    """
    Fetches all ranks from the DB and returns a simple
    dictionary mapping: {"rank_name": rank_id}
    """
    print("Fetching ranks map from database...")
    try:
        response = supabase.table('ranks').select('id, name').execute()
        ranks_map = {rank['name']: rank['id'] for rank in response.data}
        print(f"Successfully loaded {len(ranks_map)} ranks.")
        return ranks_map
    except Exception as e:
        print(f"Error fetching ranks: {e}")
        return None

def parse_csv_data(file_name: str) -> list:
    """
    Reads the CSV file and returns a list of members.
    Skips the header row and any blank rows.
    """
    members_to_add = []
    print(f"Reading data from {file_name}...")
    try:
        with open(file_name, mode='r', encoding='utf-8') as f:
            reader = csv.reader(f)
            
            # Skip the header row
            next(reader, None) 
            
            for row in reader:
                # Basic validation: ensure row has at least 3 columns
                if len(row) >= 3 and row[0].strip():
                    rsn = row[0].strip()
                    rank_name = row[1].strip()
                    date_str = row[2].strip()
                    
                    # Parse the date
                    try:
                        join_date = parse(date_str).isoformat()
                        members_to_add.append({
                            "rsn": rsn,
                            "rank_name": rank_name,
                            "date_joined": join_date
                        })
                    except Exception as e:
                        print(f"Warning: Could not parse date '{date_str}' for {rsn}. Skipping.")
                        
    except FileNotFoundError:
        print(f"Error: {file_name} not found. Make sure it's in the same folder.")
        return None
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return None
        
    print(f"Found {len(members_to_add)} members to add from CSV.")
    return members_to_add

def main():
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Error connecting to Supabase: {e}")
        return

    # 1. Get the map of Rank Names -> Rank IDs
    ranks_map = get_ranks_map(supabase)
    if not ranks_map:
        print("Cannot proceed without ranks map.")
        return

    # 2. Get the list of members from the CSV
    members_to_add = parse_csv_data(CSV_FILE_NAME)
    if not members_to_add:
        print("No members found to add.")
        return

    print(f"\n--- STARTING INITIAL DATA LOAD ---")
    success_count = 0
    fail_count = 0

    for member in members_to_add:
        rsn = member["rsn"]
        rank_name = member["rank_name"]
        
        # 3. Find the rank_id from our map
        rank_id = ranks_map.get(rank_name)
        
        if not rank_id:
            # This handles the 'Anchor' rank and any other oddities
            # For now, we'll try to add it as an 'Other' rank
            print(f"Warning: Rank '{rank_name}' for {rsn} not found. Attempting to add as 'Other'...")
            try:
                rank_data = supabase.table('ranks').insert({
                    "name": rank_name,
                    "rank_type": 'Other',
                    "hierarchy_level": None # No hierarchy
                }).execute()
                
                new_rank = rank_data.data[0]
                rank_id = new_rank['id']
                ranks_map[rank_name] = rank_id # Add to our local map
                print(f"Successfully added new rank: {rank_name}")
            except Exception as e:
                print(f"Error adding new rank {rank_name}: {e}")
                print(f"--> FAILED to add {rsn}.")
                fail_count += 1
                continue # Skip this member

        try:
            # 4. Create the 'members' entry
            #    We use .execute() to get the data back, which has the new member's ID
            print(f"Adding {rsn}...")
            member_data = supabase.table('members').insert({
                'date_joined': member['date_joined'],
                'current_rank_id': rank_id
            }).execute()
            
            new_member_id = member_data.data[0]['id']

            # 5. Create the linked 'member_rsns' entry
            supabase.table('member_rsns').insert({
                'member_id': new_member_id,
                'rsn': rsn,
                'is_primary': True
            }).execute()

            # 6. Create the initial 'rank_history' entry
            supabase.table('rank_history').insert({
                'member_id': new_member_id,
                'new_rank_id': rank_id,
                'previous_rank_id': None # This is their first rank
            }).execute()
            
            success_count += 1

        except Exception as e:
            print(f"--> FAILED to add {rsn}: {e}")
            fail_count += 1

    print("\n--- INITIAL DATA LOAD COMPLETE ---")
    print(f"Successfully added: {success_count}")
    print(f"Failed to add: {fail_count}")

# This makes the script run when you call it from the command line
if __name__ == "__main__":
    main()