import os
import sys

from dotenv import load_dotenv

load_dotenv()

SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")
RECEIVER_AUTH_TOKEN = os.getenv("RECEIVER_AUTH_TOKEN")

_REQUIRED = {
    "SUPABASE_DB_URL": SUPABASE_DB_URL,
    "RECEIVER_AUTH_TOKEN": RECEIVER_AUTH_TOKEN,
}

_missing = [name for name, value in _REQUIRED.items() if not value]
if _missing:
    print(f"Missing required environment variables: {', '.join(_missing)}", file=sys.stderr)
    sys.exit(1)
