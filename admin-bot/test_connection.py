import os
from supabase import create_client, Client

# --- PASTE YOUR KEYS HERE ---
# (You can also use environment variables, but this is fine for a test)
SUPABASE_URL = "https://jprtvhnqghhkjuabwxqq.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImpwcnR2aG5xZ2hoa2p1YWJ3eHFxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjMxNzY0MzMsImV4cCI6MjA3ODc1MjQzM30.YMtbY734FJFlNN92RkE7q-f5JuMRfg0llrjZoX8mvRI"
# -----------------------------

try:
    # 1. Create the Supabase client
    print("Connecting to Supabase...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Connection successful!")

    # 2. Fetch the data from the 'ranks' table
    # .select('*') means "get all columns"
    # .execute() runs the query
    print("Fetching 'ranks' table...")
    response = supabase.table('ranks').select('*').order('hierarchy_level').execute()

    # 3. Print the results
    print("\n--- SUCCESSFULLY FETCHED RANKS ---")
    
    # response.data will be a list of dictionaries
    for rank in response.data:
        print(f"  - [ID: {rank['id']}] {rank['name']} (Type: {rank['rank_type']}, Level: {rank['hierarchy_level']})")
    
    print("\n------------------------------------")
    print(f"Total ranks found: {len(response.data)}")

except Exception as e:
    print("\n--- AN ERROR OCCURRED ---")
    print(f"Error: {e}")
    print("\nPlease check your SUPABASE_URL and SUPABASE_KEY.")