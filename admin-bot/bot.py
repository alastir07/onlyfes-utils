import os
import discord
from discord import app_commands, ui, Interaction
from discord.ext import tasks
from dotenv import load_dotenv
from supabase import create_client, Client
import asyncio
import aiohttp
import re
import json
from io import StringIO
import traceback
import random
from datetime import datetime, time, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo
import functools
import logging
import sys # <-- Import sys

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

# --- Import your logic module ---
import clan_sync_logic
import inactivity_logic
import github_leaderboard
import overachievers_logic

# --- 1. LOAD SECRETS & CONNECT ---
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
IA_LOGGING_OUTPUT_CHANNEL_ID = os.getenv("IA_LOGGING_OUTPUT_CHANNEL_ID")
SYNC_REPORT_CHANNEL_ID = os.getenv("SYNC_REPORT_CHANNEL_ID")
INACTIVITY_REPORT_CHANNEL_ID = os.getenv("INACTIVITY_REPORT_CHANNEL_ID")
INACTIVITY_REPORT_THREAD_ID = os.getenv("INACTIVITY_REPORT_THREAD_ID")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

SUMMARIZE_PROMPT = "Briefly summarize the conversation contained in these discord messages. \
All conversation participants are staff for an Old School Runescape Clan and are friendly with each other. \
Keep your summary to 3-5 sentences. Do not include any additional information not present in the conversation."
GEMINI_MODEL = "gemini-3.5-flash"
SUMMARIZE_MIN_MESSAGES_THRESHOLD = 25
SUMMARIZE_MAX_MESSAGES_THRESHOLD = 1000

if not all([DISCORD_TOKEN, SUPABASE_URL, SUPABASE_KEY, IA_LOGGING_OUTPUT_CHANNEL_ID, SYNC_REPORT_CHANNEL_ID, INACTIVITY_REPORT_CHANNEL_ID, INACTIVITY_REPORT_THREAD_ID, GITHUB_TOKEN]):
    log.error("Missing one or more .env variables!")
    exit()

# Connect to Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Helper functions ---
def normalize_string(s: str) -> str:
    if not s: return ""
    return s.lower().replace(' ', '').replace('_', '').replace('-', '').replace('.', '')

def get_normalized_rank_from_db(rank_name_input: str) -> dict | None:
    """Fetches a rank from the database matching the normalized rank name."""
    try:
        ranks_res = supabase.table('ranks').select('*').execute()
        if not ranks_res.data:
            return None
        normalized_input = normalize_string(rank_name_input)
        for r in ranks_res.data:
            if normalize_string(r['name']) == normalized_input:
                return r
        return None
    except Exception as e:
        log.error(f"Error fetching ranks for normalization: {e}")
        return None

def resolve_rsn_to_member(rsn: str) -> dict | None:
    """
    Looks up a member by their RSN (case-insensitive, space/underscore-insensitive).
    Returns a dict containing 'member_id' and 'rsn' (original casing from DB) if found, else None.
    """
    try:
        normalized_input = normalize_string(rsn)
        if not normalized_input:
            return None
            
        res = supabase.table('member_rsns').select('member_id, rsn').execute()
        for row in res.data:
            if normalize_string(row['rsn']) == normalized_input:
                return {
                    'member_id': row['member_id'],
                    'rsn': row['rsn']
                }
        return None
    except Exception as e:
        log.error(f"Error resolving RSN '{rsn}': {e}")
        return None


def get_staff_member_id(interaction: discord.Interaction) -> str | None:
    try:
        user_id_int = interaction.user.id
        response = supabase.table('members').select('id').eq('discord_id', user_id_int).limit(1).execute()
        if response.data:
            return response.data[0]['id']
    except Exception as e:
        log.warning(f"Could not find member_id for staff {interaction.user}: {e}")
    return None

async def log_command_use(message: str):
    """Sends a command usage message to the admin logging channel if configured."""
    try:
        if IA_LOGGING_OUTPUT_CHANNEL_ID:
            channel = client.get_channel(int(IA_LOGGING_OUTPUT_CHANNEL_ID))
            if channel:
                await channel.send(f"```\n{message}\n```")
            else:
                log.warning(f"Could not find admin logging channel ID {IA_LOGGING_OUTPUT_CHANNEL_ID}")
    except Exception as e:
        log.error(f"Failed to send log to admin logging channel: {e}")

def parse_duration(time_str: str) -> datetime | None:
    """
    Parses relative duration strings (e.g. '2h', '1d 4h', '30m')
    and returns a UTC datetime threshold (now - duration).
    """
    time_str = time_str.strip().lower()
    pattern = re.compile(r'(\d+)\s*(s|sec|second|m|min|minute|h|hr|hour|d|day|w|wk|week)s?')
    matches = pattern.findall(time_str)
    
    if not matches:
        return None

    delta = timedelta()
    for amount_str, unit in matches:
        amount = int(amount_str)
        if unit in ('s', 'sec', 'second'):
            delta += timedelta(seconds=amount)
        elif unit in ('m', 'min', 'minute'):
            delta += timedelta(minutes=amount)
        elif unit in ('h', 'hr', 'hour'):
            delta += timedelta(hours=amount)
        elif unit in ('d', 'day'):
            delta += timedelta(days=amount)
        elif unit in ('w', 'wk', 'week'):
            delta += timedelta(weeks=amount)
            
    return datetime.now(ZoneInfo('UTC')) - delta

async def check_gemini_quota(api_key: str) -> bool:
    """
    Verifies Gemini API quota / key validity using a lightweight token count call.
    Returns True if request succeeds, False otherwise.
    """
    url = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:countTokens?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": "ping"
                    }
                ]
            }
        ]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers={"Content-Type": "application/json"}) as resp:
                if resp.status == 200:
                    return True
                else:
                    error_text = await resp.text()
                    log.info(f"Gemini API quota check on v1 failed (status {resp.status}), attempting v1beta fallback: {error_text}")
                    
                    fallback_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:countTokens?key={api_key}"
                    async with session.post(fallback_url, json=payload, headers={"Content-Type": "application/json"}) as resp_fb:
                        if resp_fb.status == 200:
                            return True
                        else:
                            error_text_fb = await resp_fb.text()
                            log.error(f"Gemini API quota check failed on fallback with status {resp_fb.status}: {error_text_fb}")
                            return False
    except Exception as e:
        log.error(f"Gemini API quota check error: {e}")
        return False

async def discord_api_request(session: aiohttp.ClientSession, method: str, url: str) -> any:
    """
    Helper to execute Discord REST API requests with built-in retry logic for rate limits.
    """
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json"
    }
    for attempt in range(3):
        async with session.request(method, url, headers=headers) as resp:
            if resp.status == 429:
                retry_after = 1.0
                try:
                    retry_after_hdr = resp.headers.get("Retry-After")
                    if retry_after_hdr:
                        retry_after = float(retry_after_hdr)
                except Exception:
                    pass
                log.warning(f"Discord API Rate Limited (429). Retrying in {retry_after}s...")
                await asyncio.sleep(retry_after)
                continue
            elif resp.status == 200:
                return await resp.json()
            else:
                log.error(f"Discord API request to {url} failed with status {resp.status}")
                return None
    return None

def get_matriarch_id(channel) -> int:
    """
    Finds the highest-level parent ID (like category ID) for a channel or thread.
    Chains parents / categories until we reach the top-level parent ID.
    """
    curr = channel
    while curr:
        parent = getattr(curr, 'parent', None)
        category = getattr(curr, 'category', None)
        
        if parent:
            curr = parent
        elif category:
            curr = category
        else:
            parent_id = getattr(curr, 'parent_id', None)
            category_id = getattr(curr, 'category_id', None)
            next_id = parent_id or category_id
            
            if next_id:
                guild = getattr(curr, 'guild', None)
                resolved = guild.get_channel(int(next_id)) if guild else None
                if resolved:
                    curr = resolved
                else:
                    return int(next_id)
            else:
                break
    return curr.id

# --- Discord Ranks Configuration ---
DISCORD_RANKS = [
    {"role_id": 1509529699255320657, "role_name": "Sapphire", "display_name": "Sapphire", "is_rankup_check": False, "auto_apply_discord": True, "is_exclusive": True},
    {"role_id": 1509530886616518737, "role_name": "Emerald", "display_name": "Emerald", "is_rankup_check": False, "auto_apply_discord": True, "is_exclusive": True},
    {"role_id": 1509530851854258306, "role_name": "Ruby", "display_name": "Ruby", "is_rankup_check": False, "auto_apply_discord": True, "is_exclusive": True},
    {"role_id": 1225511074514604095, "role_name": "Diamond", "display_name": "Diamond", "is_rankup_check": True, "auto_apply_discord": True, "is_exclusive": True},
    {"role_id": 1225511118005604453, "role_name": "Dragonstone", "display_name": "Dragonstone", "is_rankup_check": True, "auto_apply_discord": True, "is_exclusive": True},
    {"role_id": 1225511151526346844, "role_name": "Onyx", "display_name": "Onyx", "is_rankup_check": True, "auto_apply_discord": True, "is_exclusive": True},
    {"role_id": 1225511181528334346, "role_name": "Zenyte", "display_name": "Zenyte", "is_rankup_check": True, "auto_apply_discord": True, "is_exclusive": True},
    {"role_id": 1282755027399868468, "role_name": "Maxed", "display_name": "Maxed (Elite Skiller)", "is_rankup_check": True, "auto_apply_discord": True, "is_exclusive": True},
    {"role_id": 1282755185013166100, "role_name": "TzKal", "display_name": "TzKal (Elite PvMer)", "is_rankup_check": True, "auto_apply_discord": True, "is_exclusive": True},
    {"role_id": 1419123726015922297, "role_name": "Myth", "display_name": "Myth (Living Legend)", "is_rankup_check": True, "auto_apply_discord": True, "is_exclusive": True},
    {"role_id": 1170648724968587324, "role_name": "Beast", "display_name": "Beast (BOTM Winner)", "is_rankup_check": False, "auto_apply_discord": True, "is_exclusive": False},
    {"role_id": 1170648918414082120, "role_name": "Skiller", "display_name": "Skiller (SOTM Winner)", "is_rankup_check": False, "auto_apply_discord": True, "is_exclusive": False},
    {"role_id": 1233048247069708298, "role_name": "Merchant", "display_name": "Merchant (Big Booty/COTM Winner)", "is_rankup_check": False, "auto_apply_discord": True, "is_exclusive": False},
    {"role_id": 1170649282039251074, "role_name": "Adventurer", "display_name": "Adventurer (Event Winner)", "is_rankup_check": False, "auto_apply_discord": True, "is_exclusive": False},
    {"role_id": 1171851424372625459, "role_name": "Gamer", "display_name": "Gamer (Event Champion)", "is_rankup_check": False, "auto_apply_discord": True, "is_exclusive": False},
    {"role_id": 1394777556280021204, "role_name": "Raider", "display_name": "Raider (Event Overlord)", "is_rankup_check": False, "auto_apply_discord": True, "is_exclusive": False},
    {"role_id": 1418803591602245633, "role_name": "Administrator", "display_name": "Administrator (Retired Key)", "is_rankup_check": False, "auto_apply_discord": True, "is_exclusive": False},
    {"role_id": 1059330179094302760, "role_name": "Captain", "display_name": "Captain", "is_rankup_check": False, "auto_apply_discord": False, "is_exclusive": False},
    {"role_id": 1059330194139250698, "role_name": "General", "display_name": "General", "is_rankup_check": False, "auto_apply_discord": False, "is_exclusive": False},
    {"role_id": 1471345801430302892, "role_name": "Master", "display_name": "Master", "is_rankup_check": False, "auto_apply_discord": False, "is_exclusive": False},
    {"role_id": 1171576313862164590, "role_name": "Commander", "display_name": "Commander", "is_rankup_check": False, "auto_apply_discord": False, "is_exclusive": False},
    {"role_id": 1054602889122812025, "role_name": "Deputy Owner", "display_name": "Deputy Owner", "is_rankup_check": False, "auto_apply_discord": False, "is_exclusive": False},
    {"role_id": 1054602889122812025, "role_name": "Owner", "display_name": "Owner", "is_rankup_check": False, "auto_apply_discord": False, "is_exclusive": False}
]

# --- Role-Based Permission System ---
STAFF_ROLES = ["Owner", "Deputy Owner", "Commander", "Master", "General", "Captain"] # Ordered Highest to Lowest
ROLE_HIERARCHY_LEVELS = {
    "Owner": 99,
    "Deputy Owner": 98,
    "Commander": 53,
    "Master": 52,
    "General": 51,
    "Captain": 50
}

def get_user_role_level(interaction: discord.Interaction) -> str | None:
    """
    Returns the highest staff role the user has, or None if they have no staff role.
    Returns: "Owner", "Commander", "Master", "General", "Captain", or None
    """
    if not isinstance(interaction.user, discord.Member):
        return None
    
    user_role_names = [r.name for r in interaction.user.roles]
    
    # Check from highest to lowest
    for role in STAFF_ROLES:
        if role in user_role_names:
            return role
    
    return None

def check_staff_role(required_role: str):
    """
    Decorator to check if a user has the required role or higher.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(interaction: discord.Interaction, *args, **kwargs):
            if not isinstance(interaction.user, discord.Member):
                await interaction.response.send_message("⛔ This command can only be used in a server.", ephemeral=True)
                return

            user_role_names = [r.name for r in interaction.user.roles]
            
            # Determine allowed roles based on hierarchy
            allowed_roles = []
            if required_role in STAFF_ROLES:
                req_index = STAFF_ROLES.index(required_role)
                allowed_roles = STAFF_ROLES[:req_index+1] # Slice includes the role and all above it
            else:
                # Fallback: if role not in list, require exact match (shouldn't happen with correct usage)
                allowed_roles = [required_role]

            if any(r in allowed_roles for r in user_role_names):
                return await func(interaction, *args, **kwargs)
            else:
                await interaction.response.send_message(f"⛔ You need the **{required_role}** role (or higher) to use this command.", ephemeral=True)
                return
        return wrapper
    return decorator

async def sync_discord_clan_member_roles(guild: discord.Guild, sync_metadata: dict, dry_run: bool) -> str:
    """
    Syncs the Clan Members role (1516942589503340604) for active/deactivated members.
    Returns a summary string of the actions taken.
    """
    CLAN_MEMBERS_ROLE_ID = 1516942589503340604
    role = guild.get_role(CLAN_MEMBERS_ROLE_ID)
    if not role:
        log.error(f"Could not find Clan Members role with ID {CLAN_MEMBERS_ROLE_ID}")
        return f"⚠️ Error: Clan Members role with ID `{CLAN_MEMBERS_ROLE_ID}` not found in this server."

    active_ids = sync_metadata.get("active_discord_ids", [])
    deactivated_ids = sync_metadata.get("deactivated_discord_ids", [])
    
    if dry_run:
        return (f"Discord Role Sync (DRY RUN): Would ensure {len(active_ids)} active member(s) have the role "
                f"and remove it from {len(deactivated_ids)} deactivated member(s).")

    added_count = 0
    removed_count = 0
    failed_count = 0

    # 1. Remove role from deactivated members
    for d_id in deactivated_ids:
        try:
            member = guild.get_member(int(d_id))
            if not member:
                member = await guild.fetch_member(int(d_id))
            if member and role in member.roles:
                await member.remove_roles(role, reason="Clan sync: Member deactivated")
                removed_count += 1
        except discord.NotFound:
            log.info(f"Deactivated user {d_id} not found in guild.")
        except Exception as e:
            log.error(f"Failed to remove role from deactivated user {d_id}: {e}")
            failed_count += 1

    # 2. Add role to active members if they don't have it
    for a_id in active_ids:
        try:
            member = guild.get_member(int(a_id))
            if not member:
                member = await guild.fetch_member(int(a_id))
            if member and role not in member.roles:
                await member.add_roles(role, reason="Clan sync: Ensure active member has role")
                added_count += 1
        except discord.NotFound:
            log.info(f"Active user {a_id} not found in guild.")
        except Exception as e:
            log.error(f"Failed to add role to active user {a_id}: {e}")
            failed_count += 1

    summary = f"**Discord Role Sync:** Added to {added_count} member(s), Removed from {removed_count} member(s)."
    if failed_count > 0:
        summary += f" Failed for {failed_count} member(s)."
    return summary


intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 

# --- Define the bot (UPDATED) ---
class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        # We no longer need the guild_obj for the sync
        self.tree = app_commands.CommandTree(self)
        self.synced_on_startup = False # 'run once' flag

client = MyClient(intents=intents)

# --- 2. BOT READY EVENT (UPDATED) ---
@client.event
async def on_ready():
    # Check if we've already synced. This prevents re-syncing on disconnects.
    if not client.synced_on_startup:
        try:
            log.info("--- Attempting to SYNC commands GLOBALLY ---")
            # guild=None means we are syncing all commands globally
            await client.tree.sync(guild=None) 
            log.info("--- Global command sync complete ---")
        except Exception as e:
            log.error(f"CRITICAL ERROR during global on_ready sync: {e}")
        
        client.synced_on_startup = True 
        
        # Start scheduled tasks (only on first ready event)
        scheduled_ep_leaderboard.start()
        scheduled_clan_sync.start()
        scheduled_inactivity_check.start()
        scheduled_overachievers_check.start()
        scheduled_no_discord_check.start()
        scheduled_clan_veteran_check.start()
        scheduled_bounty_generate.start()
        scheduled_bounty_close.start()

        log.info("Scheduled tasks started: ep_leaderboard (hourly), clan_sync (00:00, 12:00 UTC), inactivity_check (14:00 UTC), overachievers (00:00 daily), no_discord_check (00:05 UTC weekly on Sundays), clan_veteran_check (00:10 UTC monthly on the 1st), bounty_generate (Mon 06:00 UTC), bounty_close (Sat 06:00 UTC)")

        # Restore bounty state from DB
        await _load_bounty_state()

    log.info(f'Logged in as {client.user} (ID: {client.user.id})')
    log.info('Bot is ready and online.')

# --- 3. /HELP COMMAND ---
COMMANDS_HELP = {
    "help": {
        "syntax": "`/help [command] [publish]`",
        "description": "Shows a list of all available commands, or details about a specific command.",
        "category": "User Commands",
        "min_role": None
    },
    "memberinfo": {
        "syntax": "`/memberinfo <rsn> [publish]`",
        "description": "Gets a member's rank, join date, current EP, and past RSNs.",
        "category": "User Commands",
        "min_role": None
    },
    "rankhistory": {
        "syntax": "`/rankhistory <rsn> [num_changes] [publish]`",
        "description": "Gets a member's recent rank changes.",
        "category": "User Commands",
        "min_role": None
    },
    "overachievers": {
        "syntax": "`/overachievers <query> [publish]`",
        "description": "Look up which metrics an RSN holds, or who holds a specific metric.",
        "category": "User Commands",
        "min_role": None
    },
    "rankup": {
        "syntax": "`/rankup <rsn> <rank_name> [publish] [bypass_discord]`",
        "description": "Manually promotes/demotes a single member.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "bulkrankup": {
        "syntax": "`/bulkrankup <rank_name> <rsn_list> [publish] [bypass_discord]`",
        "description": "Updates multiple members to the same rank.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "rankup-check": {
        "syntax": "`/rankup-check <rsn> <rank_name> [publish]`",
        "description": "Checks if a member meets the requirements for a rank.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "linkrsn": {
        "syntax": "`/linkrsn <rsn> <@user> [publish]`",
        "description": "Links a member's RSN to their Discord account.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "addpoints": {
        "syntax": "`/addpoints <rsn> <points> <reason> [publish]`",
        "description": "Adds Event Points for a member.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "removepoints": {
        "syntax": "`/removepoints <rsn> <points> <reason> [publish]`",
        "description": "Removes Event Points from a member.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "bulkaddpoints": {
        "syntax": "`/bulkaddpoints <points> <reason> <rsn_list> [publish]`",
        "description": "Adds Event Points to multiple members at once.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "addpointsbotm": {
        "syntax": "`/addpointsbotm <first> <second> <third> <participants> [publish]`",
        "description": "Adds points for Boss of the Month.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "addpointssotm": {
        "syntax": "`/addpointssotm <first> <second> <third> <participants> [publish]`",
        "description": "Adds points for Skill of the Month.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "addpointsbigbooty": {
        "syntax": "`/addpointsbigbooty <first> <second> <third> <participants> [publish]`",
        "description": "Adds points for Big Booty (Clue of the Month).",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "check-no-discord": {
        "syntax": "`/check-no-discord [publish]`",
        "description": "Checks for active clan members with no linked Discord ID.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "clan-veteran-check": {
        "syntax": "`/clan-veteran-check [publish]`",
        "description": "Checks and updates Clan Veteran roles for members with >2y in the clan.",
        "category": "Captain Commands",
        "min_role": "Captain"
    },
    "syncclan": {
        "syntax": "`/syncclan [dry_run] [force_run] [publish]`",
        "description": "Runs the clan sync with WOM.",
        "category": "General & Master Commands",
        "min_role": "General"
    },
    "addexempt": {
        "syntax": "`/addexempt <rsn> <reason> [days] [publish]`",
        "description": "Grants a member immunity from inactivity tracking for a set number of days (default 90).",
        "category": "General & Master Commands",
        "min_role": "General"
    },
    "checkinactives": {
        "syntax": "`/checkinactives [publish]`",
        "description": "Checks for members with 0 XP gain in their check period.",
        "category": "General & Master Commands",
        "min_role": "General"
    },
    "purgemember": {
        "syntax": "`/purgemember <rsn>`",
        "description": "**⚠️ IRREVERSIBLE.** Deletes a member and all their associated data from the database.",
        "category": "Commander Commands",
        "min_role": "Commander"
    },
    "updateepleaderboard": {
        "syntax": "`/updateepleaderboard [publish]`",
        "description": "Manually update the EP leaderboard on GitHub Pages.",
        "category": "Commander Commands",
        "min_role": "Commander"
    },
    "overachievers-sync": {
        "syntax": "`/overachievers-sync [dry_run] [publish]`",
        "description": "Run the Overachievers check (1st of month typically).",
        "category": "Commander Commands",
        "min_role": "Commander"
    },
    "tldr": {
        "syntax": "`/tldr [time] [message_id] [testing]`",
        "description": "Summarizes the staff channel conversation from a time/message ID to current.",
        "category": "Commander Commands",
        "min_role": "Commander"
    },
    "generate-new-bounty-quest": {
        "syntax": "`/generate-new-bounty-quest [item_name] [publish]`",
        "description": "Creates a new weekly bounty thread and announcement. Optionally specify an item; otherwise one is chosen randomly.",
        "category": "Owner Commands",
        "min_role": "Owner"
    },
    "close-bounty-quest": {
        "syntax": "`/close-bounty-quest <thread_id> [publish]`",
        "description": "Locks and archives a bounty quest thread.",
        "category": "Owner Commands",
        "min_role": "Owner"
    },
    "check-bounty-completion": {
        "syntax": "`/check-bounty-completion <thread_id> [publish]`",
        "description": "Checks a bounty thread for messages with a ✅ reaction and lists the confirmed completions.",
        "category": "Owner Commands",
        "min_role": "Owner"
    },
    "enable-automatic-bounties": {
        "syntax": "`/enable-automatic-bounties`",
        "description": "Enables the automatic weekly bounty tasks (generate on Monday 06:00 UTC, close on Saturday 06:00 UTC).",
        "category": "Owner Commands",
        "min_role": "Owner"
    },
    "disable-automatic-bounties": {
        "syntax": "`/disable-automatic-bounties`",
        "description": "Disables the automatic weekly bounty tasks so bounties can be managed manually.",
        "category": "Owner Commands",
        "min_role": "Owner"
    }
}

def is_authorized(user_role: str | None, min_role: str | None) -> bool:
    if not min_role:
        return True
    if not user_role:
        return False
    try:
        req_index = STAFF_ROLES.index(min_role)
        allowed_roles = STAFF_ROLES[:req_index+1]
        return user_role in allowed_roles
    except ValueError:
        return False

@client.tree.command(name="help", description="Shows a list of all available commands.")
@app_commands.describe(
    command="The specific command to get detailed help for.",
    publish="True to post the help message publicly."
)
async def help(interaction: discord.Interaction, command: str = None, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /help command={command} publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /help command={command} publish={publish} used by {interaction.user}")
    
    # Determine user's role level
    user_role = get_user_role_level(interaction)
    
    if command:
        cmd_name = command.lower().strip().lstrip('/')
        if cmd_name not in COMMANDS_HELP:
            await interaction.response.send_message(f"❌ Command `/{cmd_name}` not found. Use `/help` to see all available commands.", ephemeral=True)
            return
            
        cmd_info = COMMANDS_HELP[cmd_name]
        
        # Check authorization
        if not is_authorized(user_role, cmd_info["min_role"]):
            await interaction.response.send_message(f"⛔ You do not have permission to view help for the `/{cmd_name}` command.", ephemeral=True)
            return
            
        # Create premium help embed for specific command
        embed = discord.Embed(
            title=f"IronAssistant Help: /{cmd_name}",
            description=cmd_info["description"],
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=client.user.avatar.url if client.user.avatar else None)
        embed.add_field(name="📋 Category", value=cmd_info["category"], inline=True)
        embed.add_field(name="🔑 Required Role", value=cmd_info["min_role"] or "None (All Users)", inline=True)
        embed.add_field(name="💻 Usage Syntax", value=cmd_info["syntax"], inline=False)
        embed.set_footer(text="Tip: Commands in brackets [like_this] are optional. Angle brackets <like_this> are required.")
        
        is_ephemeral = not publish
        await interaction.response.send_message(embed=embed, ephemeral=is_ephemeral)
        return

    # Default /help (no command argument)
    embed = discord.Embed(
        title="IronAssistant Help",
        color=discord.Color.greyple()
    )
    embed.set_thumbnail(url=client.user.avatar.url if client.user.avatar else None)
    
    is_staff = user_role in STAFF_ROLES
    
    if is_staff:
        embed.description = "Here are the commands you can use. Run `/help <command>` for detailed info on a specific command.\n`[publish:True]` can be added to any command to make the reply public."
    else:
        embed.description = "Here are the commands you can use.\n`[publish:True]` can be added to any command to make the reply public."
    
    # Categorize commands by category
    categories_data = {
        "User Commands": [],
        "Captain Commands": [],
        "General & Master Commands": [],
        "Commander Commands": [],
        "Owner Commands": []
    }
    
    for cmd_name, cmd_info in COMMANDS_HELP.items():
        if is_authorized(user_role, cmd_info["min_role"]):
            categories_data[cmd_info["category"]].append(cmd_info)
            
    for category_name, cmd_list in categories_data.items():
        if not cmd_list:
            continue
            
        formatted_cmds = []
        for cmd in cmd_list:
            if is_staff:
                # Remove description, list only the syntax/signature
                formatted_cmds.append(cmd["syntax"])
            else:
                # Include description
                formatted_cmds.append(f"{cmd['syntax']}\n{cmd['description']}")
                
        emoji_prefix = "📋" if category_name == "User Commands" else \
                       "👮" if category_name == "Captain Commands" else \
                       "⭐" if category_name == "General & Master Commands" else \
                       "🔥" if category_name == "Commander Commands" else \
                       "👑"
                       
        embed.add_field(
            name=f"{emoji_prefix} {category_name}",
            value="\n".join(formatted_cmds) if is_staff else "\n\n".join(formatted_cmds),
            inline=False
        )
    
    # Add footer showing user's role level
    if user_role:
        embed.set_footer(text=f"Your role: {user_role} • You can use all commands at your level and below.")
    else:
        embed.set_footer(text="Your role: Member • You can use all User Commands.")
    
    is_ephemeral = not publish
    await interaction.response.send_message(embed=embed, ephemeral=is_ephemeral)

@help.autocomplete("command")
async def help_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    user_role = get_user_role_level(interaction)
    choices = []
    for cmd_name, cmd_info in COMMANDS_HELP.items():
        if is_authorized(user_role, cmd_info["min_role"]):
            if current.lower() in cmd_name.lower():
                choices.append(app_commands.Choice(name=f"/{cmd_name}", value=cmd_name))
    return choices[:25]

# --- 4. /MEMBERINFO COMMAND (UPDATED) ---
@client.tree.command(name="memberinfo", description="Get info for a clan member (shows primary RSN).")
@app_commands.describe(
    rsn="The RSN (current or past) of the member to look up.",
    publish="True to post the member info publicly."
)
async def member_info(interaction: discord.Interaction, rsn: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /memberinfo rsn='{rsn}' publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /memberinfo rsn='{rsn}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral) 

    try:
        resolved = resolve_rsn_to_member(rsn)
        if not resolved:
            await interaction.followup.send(f"Sorry, I couldn't find anyone with an RSN matching `{rsn}`.", ephemeral=True)
            return

        response = supabase.rpc('get_member_info', {'rsn_query': resolved['rsn']}).execute()

        member = response.data[0]
        
        join_date_obj = discord.utils.parse_time(member['date_joined'])
        formatted_date = f"<t:{int(join_date_obj.timestamp())}:D>"
        days_in_clan = member.get('total_days_in_clan', 0)
        combined_date_and_days = f"{formatted_date} ({days_in_clan} days)"
        latest_wom_snapshot_obj = discord.utils.parse_time(member['latest_wom_snapshot']) or "Never"
        formatted_latest_wom_snapshot = f"<t:{int(latest_wom_snapshot_obj.timestamp())}:D>" if latest_wom_snapshot_obj != "Never" else "Never"
        latest_ep_transaction_obj = discord.utils.parse_time(member['latest_ep_transaction']) or "Never"
        formatted_latest_ep_transaction = f"<t:{int(latest_ep_transaction_obj.timestamp())}:D>" if latest_ep_transaction_obj != "Never" else "Never"

        # Check permissions (Captain+)
        user_role = get_user_role_level(interaction)
        is_staff = user_role is not None

        embed = discord.Embed(
            title=f"Member Info: {member['primary_rsn']}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Current Rank", value=member['rank_name'], inline=True)
        embed.add_field(name="Current EP", value=f"{member['total_ep']:,}", inline=True)
        embed.add_field(name="Join Date", value=combined_date_and_days, inline=True)
        
        if is_staff:
             embed.add_field(name="Latest XP Gain", value=formatted_latest_wom_snapshot, inline=True)
             embed.add_field(name="Latest EP Gain", value=formatted_latest_ep_transaction, inline=True)
        
             # --- Add Discord ID (plaintext) ---
             discord_id = member.get('discord_id')
             if discord_id:
                 # Use backticks to format it as code and prevent pings
                 embed.add_field(name="Linked Discord ID", value=f"`{discord_id}`", inline=False)

        past_names = member.get('past_names')
        if past_names:
            names_str = ", ".join(past_names)
            embed.add_field(name="Formerly Known As", value=names_str, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in /memberinfo command: {e}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)
        
                
# --- 5. /RANKHISTORY COMMAND ---
@client.tree.command(name="rankhistory", description="Get a member's recent rank changes.")
@app_commands.describe(
    rsn="The RSN (current or past) of the member to look up.",
    num_changes="Number of changes to show (default: 3).",
    publish="True to post the history publicly."
)
async def rankhistory(interaction: discord.Interaction, rsn: str, num_changes: int = 3, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /rankhistory rsn='{rsn}' num_changes={num_changes} publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /rankhistory rsn='{rsn}' num_changes={num_changes} publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral) 

    try:
        resolved = resolve_rsn_to_member(rsn)
        if not resolved:
            await interaction.followup.send(f"Sorry, I couldn't find anyone with an RSN matching `{rsn}` (or they have no rank history).", ephemeral=True)
            return

        response = supabase.rpc('get_rank_history', {'rsn_query': resolved['rsn'], 'limit_count': num_changes}).execute()
        if not response.data:
            await interaction.followup.send(f"Sorry, I couldn't find anyone with an RSN matching `{rsn}` (or they have no rank history).", ephemeral=True)
            return
        history_list = response.data
        primary_rsn = history_list[0]['primary_rsn']
        embed = discord.Embed(
            title=f"Rank History: {primary_rsn}",
            description=f"Showing the {len(history_list)} most recent rank changes.",
            color=discord.Color.blue()
        )
        for change in history_list:
            date_obj = discord.utils.parse_time(change['date_enacted'])
            formatted_date = f"<t:{int(date_obj.timestamp())}:D>"
            prev_rank = change['previous_rank'] or "N/A (Joined)"
            embed.add_field(
                name=f"🗓️ {formatted_date}",
                value=f"`{prev_rank}` → **{change['new_rank']}**",
                inline=False
            )
        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)
    except Exception as e:
        log.error(f"Error in /rankhistory command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)

# --- 6. /SYNC-CLAN COMMAND ---
@client.tree.command(name="syncclan", description="Manually run the daily sync with WOM.")
@app_commands.describe(
    dry_run="True (default) to just see the report. False to execute changes.",
    force_run="False (default). True to bypass the rank mismatch safety check.",
    publish="False (default). True to post the final report publicly."
)
@check_staff_role("General")
async def sync_clan(
    interaction: discord.Interaction, 
    dry_run: bool = True, 
    force_run: bool = False, 
    publish: bool = False
):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /syncclan dry_run={dry_run} force_run={force_run} publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /syncclan dry_run={dry_run} force_run={force_run} publish={publish} used by {interaction.user}")
    is_ephemeral = not publish 
    await interaction.response.defer(ephemeral=is_ephemeral)
    if force_run and dry_run:
        await interaction.followup.send("Error: Cannot use `force_run=True` with `dry_run=True`. No action taken.", ephemeral=True)
        return
    try:
        report_string, sync_metadata = await asyncio.to_thread(
            clan_sync_logic.run_sync, 
            supabase, 
            dry_run=dry_run, 
            force_run=force_run
        )
        log.info("Sync function complete. Synchronizing Discord roles...")
        
        role_sync_summary = ""
        guild = interaction.guild
        if guild:
            try:
                role_sync_summary = await sync_discord_clan_member_roles(guild, sync_metadata, dry_run=dry_run)
            except Exception as re:
                log.error(f"Error in sync_discord_clan_member_roles: {re}")
                role_sync_summary = f"⚠️ Discord Role Sync Error: {re}"
        
        if role_sync_summary:
            report_string += f"\n\n{role_sync_summary}"

        log.info("Sending report.")
        if len(report_string) > 1900:
            await interaction.followup.send(
                "Sync complete. The report is too long, so it's attached as a file.",
                file=discord.File(StringIO(report_string), "sync_report.txt"),
                ephemeral=is_ephemeral
            )
        else:
            await interaction.followup.send(
                f"Sync complete.\n```\n{report_string}\n```",
                ephemeral=is_ephemeral
            )
    except Exception as e:
        log.error(f"CRITICAL Error in /sync-clan command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"A critical error occurred. Check the bot console logs: `{e}`", ephemeral=True)

# --- 7. /PURGE-MEMBER COMMAND ---
class ConfirmPurgeView(ui.View):
    def __init__(self, *, member_id: str, original_author: discord.User, rsn: str, join_date: str):
        super().__init__(timeout=60.0)
        self.member_id = member_id
        self.original_author = original_author
        self.rsn = rsn
        self.join_date = join_date
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.original_author.id:
            await interaction.response.send_message("You are not authorized to use this button.", ephemeral=True)
            return False
        return True
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        log.info(f"Purge command for {self.rsn} timed out.")
    @ui.button(label="Yes, Purge This Member", style=discord.ButtonStyle.danger, emoji="🔥")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log.info(f"[{timestamp}] /purge-member CONFIRMED for rsn='{self.rsn}' by {interaction.user}")
        await log_command_use(f"[{timestamp}] /purge-member CONFIRMED for rsn='{self.rsn}' by {interaction.user}")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        try:
            # Delete dependent records that might not have ON DELETE CASCADE
            supabase.table('membership_events').delete().eq('member_id', self.member_id).execute()
            
            data = supabase.table('members').delete().eq('id', self.member_id).execute()
            if not data.data:
                await interaction.followup.send(f"Error: Could not find member with ID {self.member_id} to delete.", ephemeral=True)
                return
            log.info(f"Member {self.rsn} (ID: {self.member_id}) was purged by {self.original_author}.")
            embed = discord.Embed(title="🔥 Purge Complete", description=f"Successfully purged **{self.rsn}** and all their associated data from the database.", color=discord.Color.dark_red())
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            log.error(f"Error during purge: {e}")
            await interaction.followup.send(f"An error occurred during the purge: `{e}`", ephemeral=True)
    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Purge operation cancelled.", embed=None, view=self)

@client.tree.command(name="purgemember", description="DANGER: Permanently deletes a member and all their data.")
@app_commands.describe(rsn="The RSN of the member to purge (must be an exact, case-sensitive match).")
@check_staff_role("Commander")
async def purge_member(interaction: discord.Interaction, rsn: str):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /purgemember rsn='{rsn}' used by {interaction.user}")
    await log_command_use(f"[{timestamp}] /purgemember rsn='{rsn}' used by {interaction.user}")
    await interaction.response.defer(ephemeral=True)
    try:
        response = supabase.table('member_rsns').select('member_id, members(date_joined)').eq('rsn', rsn).limit(1).execute()
        if not response.data:
            await interaction.followup.send(f"Could not find any member with the exact RSN: `{rsn}`. No action taken.", ephemeral=True)
            return
        member_info = response.data[0]
        member_id = member_info['member_id']
        join_date = "Unknown"
        if member_info.get('members'):
             join_date_obj = discord.utils.parse_time(member_info['members']['date_joined'])
             join_date = f"<t:{int(join_date_obj.timestamp())}:D>"
        embed = discord.Embed(title="🔥 Confirm Permanent Deletion", description=f"This will **irreversibly** delete all database records for the member associated with **{rsn}**.", color=discord.Color.red())
        embed.add_field(name="Member ID", value=f"`{member_id}`", inline=False)
        embed.add_field(name="RSN", value=rsn, inline=True)
        embed.add_field(name="Join Date", value=join_date, inline=True)
        embed.set_footer(text="This operation cannot be undone. The buttons will time out in 60 seconds.")
        view = ConfirmPurgeView(member_id=member_id, original_author=interaction.user, rsn=rsn, join_date=join_date)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        log.error(f"Error in /purge-member command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)

# --- 8. /RANKUP COMMAND ---
@client.tree.command(name="rankup", description="Promote or demote a single member.")
@app_commands.describe(
    rsn="The member's RSN (current or past).",
    rank_name="The new rank to assign (e.g., 'Ruby', 'Beast').",
    publish="True to post the confirmation publicly.",
    bypass_discord="True to bypass updating the Discord role (useful if member has no Discord)."
)
@app_commands.choices(rank_name=[
    app_commands.Choice(name=rank["display_name"], value=rank["role_name"])
    for rank in DISCORD_RANKS
])

@check_staff_role("Captain")
async def rankup(interaction: discord.Interaction, rsn: str, rank_name: str, publish: bool = False, bypass_discord: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /rankup rsn='{rsn}' rank_name='{rank_name}' publish={publish} bypass_discord={bypass_discord} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /rankup rsn='{rsn}' rank_name='{rank_name}' publish={publish} bypass_discord={bypass_discord} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)

    try:
        staff_member_id = get_staff_member_id(interaction)
        staff_role = get_user_role_level(interaction)
        staff_max_hierarchy = ROLE_HIERARCHY_LEVELS.get(staff_role, 0) if staff_role else 0
        
        new_rank = get_normalized_rank_from_db(rank_name)
        
        if not new_rank:
            await interaction.followup.send(f"Error: The rank `{rank_name}` does not exist in the database.", ephemeral=True)
            return
            
        if new_rank.get('hierarchy_level', 0) > staff_max_hierarchy:
            await interaction.followup.send(f"⛔ Permission Denied: You cannot assign a rank ({new_rank['name']}) with a higher hierarchy level than your own staff role.", ephemeral=True)
            return
        
        new_rank_id = new_rank['id']
        new_rank_name = new_rank['name'] 

        member_res = supabase.table('member_rsns') \
            .select('member_id, rsn, members(current_rank_id, discord_id, ranks(hierarchy_level))') \
            .ilike('rsn', rsn) \
            .limit(1) \
            .execute()

        if not member_res.data:
            await interaction.followup.send(f"Error: Member data not found in the database.", ephemeral=True)
            return

        member_id = member_res.data[0]['member_id']
        member_rsn = member_res.data[0]['rsn']
        old_rank_id = member_res.data[0]['members']['current_rank_id']
        discord_id = member_res.data[0]['members'].get('discord_id')
        
        old_hierarchy = 0
        if member_res.data[0].get('members') and member_res.data[0]['members'].get('ranks'):
            old_hierarchy = member_res.data[0]['members']['ranks'].get('hierarchy_level', 0)
            
        if old_hierarchy > staff_max_hierarchy:
            await interaction.followup.send(f"⛔ Permission Denied: You cannot modify the rank of a member whose current hierarchy level ({old_hierarchy}) is higher than your own staff role.", ephemeral=True)
            return

        if old_rank_id == new_rank_id:
            await interaction.followup.send(f"Error: `{member_rsn}` already has the rank `{new_rank_name}`.", ephemeral=True)
            return

        supabase.table('members').update({'current_rank_id': new_rank_id}).eq('id', member_id).execute()
        
        supabase.table('rank_history').insert({
            'member_id': member_id, 
            'previous_rank_id': old_rank_id, 
            'new_rank_id': new_rank_id,
            'enacted_by_member_id': staff_member_id
        }).execute()
        
        # Update Discord role if linked and role_id is configured
        discord_msg = ""
        if discord_id and not bypass_discord:
            rank_config = next((r for r in DISCORD_RANKS if r["role_name"] == rank_name), None)
            if rank_config and rank_config.get("auto_apply_discord") is False:
                discord_msg = " (Discord role auto-apply is disabled for staff ranks.)"
            elif rank_config and rank_config.get("role_id"):
                role_id = rank_config["role_id"]
                guild = interaction.guild
                if guild:
                    role = guild.get_role(int(role_id))
                    if role:
                        try:
                            discord_member = guild.get_member(int(discord_id))
                            if not discord_member:
                                discord_member = await guild.fetch_member(int(discord_id))
                            
                            # Clean up old exclusive roles
                            roles_to_remove = []
                            if rank_config.get("is_exclusive"):
                                for r_cfg in DISCORD_RANKS:
                                    if r_cfg.get("is_exclusive") and r_cfg.get("role_id") and int(r_cfg["role_id"]) != int(role_id):
                                        role_obj = guild.get_role(int(r_cfg["role_id"]))
                                        if role_obj and role_obj in discord_member.roles:
                                            roles_to_remove.append(role_obj)
                            
                            removed_msg = ""
                            if roles_to_remove:
                                await discord_member.remove_roles(*roles_to_remove, reason=f"Rankup to {new_rank_name} (exclusive ranks cleanup)")
                                removed_names = ", ".join([r.name for r in roles_to_remove])
                                removed_msg = f" and removed **{removed_names}**"
                            
                            if role not in discord_member.roles:
                                await discord_member.add_roles(role, reason=f"Rankup to {new_rank_name} by {interaction.user}")
                                discord_msg = f" Also added Discord role **{role.name}**{removed_msg}."
                            else:
                                if removed_msg:
                                    discord_msg = f" (Removed old exclusive rank(s): {', '.join([r.name for r in roles_to_remove])}.)"
                                else:
                                    discord_msg = f" (Already has Discord role **{role.name}**.)"
                        except discord.Forbidden:
                            discord_msg = " ⚠️ Could not assign Discord role (Bot lacks 'Manage Roles' permission or role is higher than Bot's role)."
                        except discord.HTTPException as de:
                            discord_msg = f" ⚠️ Failed to assign Discord role: {de}"
                    else:
                        discord_msg = f" ⚠️ Discord role ID `{role_id}` not found in this server."
                else:
                    discord_msg = " ⚠️ Command was not run in a server, cannot assign Discord role."
            elif rank_config:
                discord_msg = " (Discord role ID not configured yet.)"
        elif bypass_discord:
            discord_msg = " (Bypassed Discord role update.)"
        
        await interaction.followup.send(f"✅ Success! `{member_rsn}`'s rank has been updated to **{new_rank_name}**.{discord_msg}", ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in /rankup command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 9. /BULKRANKUP COMMAND ---
@client.tree.command(name="bulkrankup", description="Promote or demote multiple members to the same rank.")
@app_commands.describe(
    rank_name="The new rank to assign all members (e.g., 'Beast').",
    rsn_list="A comma-separated list of RSNs.",
    publish="True to post the confirmation publicly.",
    bypass_discord="True to bypass updating Discord roles (useful if members have no Discord)."
)
@app_commands.choices(rank_name=[
    app_commands.Choice(name=rank["display_name"], value=rank["role_name"])
    for rank in DISCORD_RANKS
])
@check_staff_role("Captain")
async def bulkrankup(interaction: discord.Interaction, rank_name: str, rsn_list: str, publish: bool = False, bypass_discord: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /bulkrankup rank_name='{rank_name}' rsn_list='{rsn_list}' publish={publish} bypass_discord={bypass_discord} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /bulkrankup rank_name='{rank_name}' rsn_list='{rsn_list}' publish={publish} bypass_discord={bypass_discord} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        staff_member_id = get_staff_member_id(interaction)
        staff_role = get_user_role_level(interaction)
        staff_max_hierarchy = ROLE_HIERARCHY_LEVELS.get(staff_role, 0) if staff_role else 0

        new_rank = get_normalized_rank_from_db(rank_name)
        
        if not new_rank:
            await interaction.followup.send(f"Error: The rank `{rank_name}` does not exist in the database.", ephemeral=True)
            return
            
        if new_rank.get('hierarchy_level', 0) > staff_max_hierarchy:
            await interaction.followup.send(f"⛔ Permission Denied: You cannot assign a rank ({new_rank['name']}) with a higher hierarchy level than your own staff role.", ephemeral=True)
            return
        
        new_rank_id = new_rank['id']
        new_rank_name = new_rank['name']

        log.info("Building RSN map for bulk rankup...")
        rsns_res = supabase.table('member_rsns') \
            .select('rsn, member_id, members(current_rank_id, discord_id, ranks(hierarchy_level))') \
            .execute()
        
        rsn_map = {}
        for item in rsns_res.data:
            if item.get('members'):
                old_h = 0
                if item['members'].get('ranks'):
                    old_h = item['members']['ranks'].get('hierarchy_level', 0)
                rsn_map[normalize_string(item['rsn'])] = {
                    "member_id": item['member_id'],
                    "original_rsn": item['rsn'],
                    "old_rank_id": item['members']['current_rank_id'],
                    "old_hierarchy": old_h,
                    "discord_id": item['members'].get('discord_id')
                }
        log.info("RSN map built.")

        rsns_to_process = [r.strip() for r in rsn_list.split(',')]
        
        member_ids_to_update = []
        history_payload = []
        successful_discord_members = []
        report_success = []
        report_fail_not_found = []
        report_fail_already_rank = []
        report_fail_permission = []
        report_fail_no_discord = []

        for rsn in rsns_to_process:
            if not rsn: continue
            
            normalized_rsn = normalize_string(rsn)
            member_data = rsn_map.get(normalized_rsn)

            if not member_data:
                report_fail_not_found.append(rsn)
                continue
            
            if member_data['old_hierarchy'] > staff_max_hierarchy:
                report_fail_permission.append(member_data['original_rsn'])
                continue
                
            if member_data['old_rank_id'] == new_rank_id:
                report_fail_already_rank.append(member_data['original_rsn'])
                continue
                
            if not member_data['discord_id'] and not bypass_discord:
                report_fail_no_discord.append(member_data['original_rsn'])
                continue
                
            member_ids_to_update.append(member_data['member_id'])
            history_payload.append({
                'member_id': member_data['member_id'], 
                'previous_rank_id': member_data['old_rank_id'], 
                'new_rank_id': new_rank_id,
                'enacted_by_member_id': staff_member_id
            })
            report_success.append(member_data['original_rsn'])
            successful_discord_members.append({
                "rsn": member_data['original_rsn'],
                "discord_id": member_data['discord_id']
            })

        if member_ids_to_update:
            log.info(f"Updating {len(member_ids_to_update)} members to rank {new_rank_name}...")
            supabase.table('members').update({'current_rank_id': new_rank_id}).in_('id', member_ids_to_update).execute()
            supabase.table('rank_history').insert(history_payload).execute()
            log.info("Batch update complete.")
        else:
            log.info("No members valid for update.")

        # Discord roles update for bulkrankup
        discord_summary = ""
        if successful_discord_members and not bypass_discord:
            rank_config = next((r for r in DISCORD_RANKS if r["role_name"] == rank_name), None)
            if rank_config and rank_config.get("auto_apply_discord") is False:
                discord_summary = "ℹ️ Discord role auto-apply is disabled for staff ranks."
            elif rank_config and rank_config.get("role_id"):
                role_id = rank_config["role_id"]
                guild = interaction.guild
                if guild:
                    role = guild.get_role(int(role_id))
                    if role:
                        role_assigned_count = 0
                        role_skipped_count = 0
                        role_failed_count = 0
                        for s_member in successful_discord_members:
                            d_id = s_member["discord_id"]
                            if not d_id:
                                continue
                            try:
                                discord_member = guild.get_member(int(d_id))
                                if not discord_member:
                                    discord_member = await guild.fetch_member(int(d_id))
                                
                                # Clean up old exclusive roles
                                roles_to_remove = []
                                if rank_config.get("is_exclusive"):
                                    for r_cfg in DISCORD_RANKS:
                                        if r_cfg.get("is_exclusive") and r_cfg.get("role_id") and int(r_cfg["role_id"]) != int(role_id):
                                            role_obj = guild.get_role(int(r_cfg["role_id"]))
                                            if role_obj and role_obj in discord_member.roles:
                                                roles_to_remove.append(role_obj)
                                
                                if roles_to_remove:
                                    await discord_member.remove_roles(*roles_to_remove, reason=f"Bulk rankup to {new_rank_name} (exclusive ranks cleanup)")
                                
                                if role not in discord_member.roles:
                                    await discord_member.add_roles(role, reason=f"Bulk rankup to {new_rank_name} by {interaction.user}")
                                    role_assigned_count += 1
                                else:
                                    role_skipped_count += 1
                            except Exception as de:
                                log.error(f"Failed to assign role to {s_member['rsn']} (discord_id: {d_id}): {de}")
                                role_failed_count += 1
                        
                        discord_summary = f"**Discord Roles ({role.name}):** Assigned {role_assigned_count}, Already had {role_skipped_count}, Failed {role_failed_count}"
                    else:
                        discord_summary = f"⚠️ Discord role ID `{role_id}` not found in this server."
                else:
                    discord_summary = "⚠️ Command not run in server; skipped Discord roles."
            elif rank_config:
                discord_summary = "ℹ️ Discord role ID not configured yet."
        elif bypass_discord:
            discord_summary = "ℹ️ Bypassed Discord roles update."

        embed = discord.Embed(
            title=f"Bulk Rank Update to '{new_rank_name}' Complete",
            description=discord_summary if discord_summary else None,
            color=discord.Color.green() if not report_fail_not_found and not report_fail_no_discord else discord.Color.orange()
        )
        
        if report_success:
            embed.add_field(name=f"✅ Success ({len(report_success)})", value="```\n" + "\n".join(report_success) + "\n```", inline=False)
        if report_fail_already_rank:
            embed.add_field(name=f"ℹ️ No Change ({len(report_fail_already_rank)})", value="```\n" + "\n".join(report_fail_already_rank) + "\n```", inline=False)
        if report_fail_no_discord:
            embed.add_field(name=f"❌ Failed: No Discord Linked ({len(report_fail_no_discord)})", value="```\n" + "\n".join(report_fail_no_discord) + "\n```\n*Use `bypass_discord=True` to update database-only, or link them using `/linkrsn` first.*", inline=False)
        if report_fail_not_found:
            embed.add_field(name=f"❌ Failed: RSN Not Found ({len(report_fail_not_found)})", value="```\n" + "\n".join(report_fail_not_found) + "\n```", inline=False)
        if report_fail_permission:
            embed.add_field(name=f"⛔ Failed: Permission Denied ({len(report_fail_permission)})", value="```\n" + "\n".join(report_fail_permission) + "\n```", inline=False)
        
        if not report_success and not report_fail_already_rank and not report_fail_not_found and not report_fail_permission and not report_fail_no_discord:
            embed.description = "No RSNs were provided or found."

        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in /bulkrankup command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 10. /RANKUP-CHECK COMMAND ---
@client.tree.command(name="rankup-check", description="Check if a member meets the requirements for a rank.")
@app_commands.describe(
    rsn="The member's RSN.",
    rank_name="The rank to check eligibility for.",
    publish="True to post the report publicly."
)
@app_commands.choices(rank_name=[
    app_commands.Choice(name=rank["display_name"], value=rank["role_name"])
    for rank in DISCORD_RANKS if rank["is_rankup_check"]
])
@check_staff_role("Captain")
async def rankup_check(interaction: discord.Interaction, rsn: str, rank_name: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /rankup-check rsn='{rsn}' rank_name='{rank_name}' publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /rankup-check rsn='{rsn}' rank_name='{rank_name}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        target_rank = get_normalized_rank_from_db(rank_name)
        if not target_rank:
            await interaction.followup.send(f"Error: Rank `{rank_name}` not found in database.", ephemeral=True)
            return
        
        resolved = resolve_rsn_to_member(rsn)
        if not resolved:
            await interaction.followup.send(f"Error: RSN `{rsn}` not found in the database.", ephemeral=True)
            return

        member_id = resolved['member_id']
        member_rsn = resolved['rsn']

        info_res = supabase.rpc('get_member_info', {'rsn_query': member_rsn}).execute()
        if not info_res.data:
            await interaction.followup.send(f"Error: Could not retrieve info for `{member_rsn}`.", ephemeral=True)
            return
            
        member_info = info_res.data[0]
        
        date_joined_str = member_info.get('date_joined')
        if date_joined_str:
            join_date_obj = discord.utils.parse_time(date_joined_str)
            formatted_join_date = f"<t:{int(join_date_obj.timestamp())}:D>"
        else:
            formatted_join_date = "Unknown"

        days_in_clan = member_info.get('total_days_in_clan', 0)

        wom_res = supabase.table('wom_snapshots').select('total_level').eq('member_id', member_id).order('snapshot_date', desc=True).limit(1).execute()
        total_level = wom_res.data[0].get('total_level', 0) if wom_res.data else 0
        total_level = total_level or 0
        
        req_months = target_rank.get('req_months_in_clan') or 0
        req_tl = target_rank.get('req_total_level') or 0
        
        has_time = days_in_clan >= (req_months * 28)
        time_status = "✅ Met" if has_time else "❌ Not Met"

        has_tl = total_level >= req_tl
        tl_status = "✅ Met" if has_tl else "❌ Not Met"

        embed = discord.Embed(
            title=f"Checking if {member_rsn} is eligible for {target_rank['name']}...",
            color=discord.Color.gold()
        )
        
        embed.add_field(name="Join Date", value=formatted_join_date, inline=True)
        embed.add_field(name="Current EP", value=f"{member_info.get('total_ep', 0):,}", inline=True)
        embed.add_field(name="Current Rank", value=member_info.get('rank_name', 'Unknown'), inline=True)
        
        embed.add_field(
            name="Time In Clan Requirement", 
            value=f"{time_status} (Needs {req_months} mo.)", 
            inline=False
        )
        if req_tl > 0:
            embed.add_field(
                name="Total Level Requirement", 
                value=f"{tl_status} ({total_level:,} / {req_tl:,})", 
                inline=False
            )
        
        manual_crit = target_rank.get('manual_criteria') or "None"
        embed.add_field(name="Manual Criteria", value=manual_crit, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in /rankup-check command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 11. /LINK-RSN COMMAND ---
@client.tree.command(name="linkrsn", description="Links a member's RSN to their Discord account.")
@app_commands.describe(
    rsn="The member's RSN (current or past).",
    user="The @discord user to link.",
    publish="True to post the confirmation publicly."
)
@check_staff_role("Captain")
async def link_rsn(interaction: discord.Interaction, rsn: str, user: discord.Member, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /linkrsn rsn='{rsn}' user='{user}' publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /linkrsn rsn='{rsn}' user='{user}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        # 1. Find the member by RSN
        resolved = resolve_rsn_to_member(rsn)
        if not resolved:
            await interaction.followup.send(f"Error: RSN `{rsn}` not found in the database.", ephemeral=True)
            return

        member_id = resolved['member_id']
        member_rsn = resolved['rsn']
        
        # 2. Check if they are already linked
        member_res = supabase.table('members').select('discord_id').eq('id', member_id).limit(1).execute()
        if not member_res.data:
            await interaction.followup.send(f"Error: Member data not found in the database.", ephemeral=True)
            return

        if member_res.data[0].get('discord_id'):
            old_discord_id = member_res.data[0]['discord_id']
            if old_discord_id == user.id:
                await interaction.followup.send(f"ℹ️ No change: `{member_rsn}` is already linked to {user.mention}.", ephemeral=True)
                return
            else:
                await interaction.followup.send(f"Warning: `{member_rsn}` is already linked to a different user (<@{old_discord_id}>). Please /unlink them first.", ephemeral=True)
                return
        
        # 3. Execute the update
        supabase.table('members').update({'discord_id': user.id}).eq('id', member_id).execute()
        
        # 4. Assign Clan Members role immediately
        role_msg = ""
        CLAN_MEMBERS_ROLE_ID = 1516942589503340604
        guild = interaction.guild
        if guild:
            role = guild.get_role(CLAN_MEMBERS_ROLE_ID)
            if role:
                if role not in user.roles:
                    try:
                        await user.add_roles(role, reason=f"RSN {member_rsn} linked by {interaction.user}")
                        role_msg = f" Also added **{role.name}** role."
                    except Exception as de:
                        log.warning(f"Could not assign Clan Members role: {de}")
                        role_msg = " ⚠️ Could not assign Clan Members role (lacks permission)."
                else:
                    role_msg = f" (Already has **{role.name}** role.)"
            else:
                log.error(f"Could not find Clan Members role with ID {CLAN_MEMBERS_ROLE_ID}")
                
        await interaction.followup.send(f"✅ Success! `{member_rsn}` is now linked to {user.mention}.{role_msg}", ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in /link-rsn command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 11. /ADD-POINTS COMMAND ---
@client.tree.command(name="addpoints", description="Add Event Points (EP) for a member.")
@app_commands.describe(
    rsn="The member's RSN.",
    points="The amount of points to add (must be positive).",
    reason="The reason for this transaction (e.g., 'Event attendance', 'Store purchase').",
    publish="True to post the confirmation publicly."
)
@check_staff_role("Captain")
async def add_points(interaction: discord.Interaction, rsn: str, points: int, reason: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /addpoints rsn='{rsn}' points={points} reason='{reason}' publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /addpoints rsn='{rsn}' points={points} reason='{reason}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    if points < 0:
        await interaction.followup.send(f"⛔ Please use `/remove-points` to subtract points.", ephemeral=True)
        return

    try:
        # 1. Find the member
        resolved = resolve_rsn_to_member(rsn)
        if not resolved:
            await interaction.followup.send(f"Error: RSN `{rsn}` not found in the database.", ephemeral=True)
            return

        member_id = resolved['member_id']
        member_rsn = resolved['rsn']
        
        # 2. Insert Transaction
        supabase.table('event_point_transactions').insert({
            'member_id': member_id,
            'modification': points,
            'reason': reason
        }).execute()
        
        # 3. Fetch New Total
        info_res = supabase.rpc('get_member_info', {'rsn_query': member_rsn}).execute()
        new_total = "Unknown"
        if info_res.data:
            new_total = f"{info_res.data[0]['total_ep']:,}"
            
        # 4. Send Confirmation
        embed = discord.Embed(
            title="Event Points Added",
            color=discord.Color.green()
        )
        embed.add_field(name="Member", value=member_rsn, inline=True)
        embed.add_field(name="Added", value=f"+{points}", inline=True)
        embed.add_field(name="New Total EP", value=new_total, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in /addpoints command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 12. /REMOVE-POINTS COMMAND ---
@client.tree.command(name="removepoints", description="Remove Event Points (EP) from a member.")
@app_commands.describe(
    rsn="The member's RSN.",
    points="The amount of points to remove (must be positive).",
    reason="The reason for this transaction.",
    publish="True to post the confirmation publicly."
)
@check_staff_role("Captain")
async def remove_points(interaction: discord.Interaction, rsn: str, points: int, reason: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /removepoints rsn='{rsn}' points={points} reason='{reason}' publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /removepoints rsn='{rsn}' points={points} reason='{reason}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    if points < 0:
        await interaction.followup.send(f"⛔ Please enter a positive number (e.g., 10) to remove points.", ephemeral=True)
        return

    try:
        # 1. Find the member
        resolved = resolve_rsn_to_member(rsn)
        if not resolved:
            await interaction.followup.send(f"Error: RSN `{rsn}` not found in the database.", ephemeral=True)
            return

        member_id = resolved['member_id']
        member_rsn = resolved['rsn']
        
        # 2. Insert Transaction (Negative modification)
        supabase.table('event_point_transactions').insert({
            'member_id': member_id,
            'modification': -points,
            'reason': reason
        }).execute()
        
        # 3. Fetch New Total
        info_res = supabase.rpc('get_member_info', {'rsn_query': member_rsn}).execute()
        new_total = "Unknown"
        if info_res.data:
            new_total = f"{info_res.data[0]['total_ep']:,}"
            
        # 4. Send Confirmation
        embed = discord.Embed(
            title="Event Points Removed",
            color=discord.Color.red()
        )
        embed.add_field(name="Member", value=member_rsn, inline=True)
        embed.add_field(name="Removed", value=f"-{points}", inline=True)
        embed.add_field(name="New Total EP", value=new_total, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in /remove-points command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 13. /BULK-ADD-POINTS COMMAND ---
@client.tree.command(name="bulkaddpoints", description="Add Event Points (EP) to multiple members at once.")
@app_commands.describe(
    points="The amount of points to add (must be positive).",
    reason="The reason for this transaction.",
    rsn_list="A comma-separated list of RSNs.",
    publish="True to post the confirmation publicly."
)
@check_staff_role("Captain")
async def bulk_add_points(interaction: discord.Interaction, points: int, reason: str, rsn_list: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /bulkaddpoints points={points} reason='{reason}' rsn_list='{rsn_list}' publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /bulkaddpoints points={points} reason='{reason}' rsn_list='{rsn_list}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    if points < 0:
        await interaction.followup.send(f"⛔ Please enter a positive number for points.", ephemeral=True)
        return

    try:
        # 1. Parse RSNs
        rsns_to_process = [r.strip() for r in rsn_list.split(',') if r.strip()]
        if not rsns_to_process:
            await interaction.followup.send("Error: No RSNs provided.", ephemeral=True)
            return

        # 2. Build RSN Map (Optimization: Fetch all members once)
        # We need to resolve RSN -> Member ID
        log.info("Building RSN map for bulk add points...")
        all_rsns_res = supabase.table('member_rsns').select('rsn, member_id').execute()
        
        rsn_map = {}
        for item in all_rsns_res.data:
            rsn_map[normalize_string(item['rsn'])] = {
                "member_id": item['member_id'],
                "original_rsn": item['rsn']
            }
        
        transactions = []
        success_list = []
        not_found_list = []

        for rsn in rsns_to_process:
            normalized = normalize_string(rsn)
            if normalized in rsn_map:
                member_data = rsn_map[normalized]
                transactions.append({
                    'member_id': member_data['member_id'],
                    'modification': points,
                    'reason': reason
                })
                success_list.append(member_data['original_rsn'])
            else:
                not_found_list.append(rsn)

        # 3. Execute Transactions
        if transactions:
            supabase.table('event_point_transactions').insert(transactions).execute()
            
        # 4. Send Report
        embed = discord.Embed(
            title="Bulk Event Points Added",
            color=discord.Color.green()
        )
        embed.add_field(name="Points Added", value=f"+{points}", inline=True)
        embed.add_field(name="Reason", value=reason, inline=True)
        
        if success_list:
            embed.add_field(name=f"✅ Success ({len(success_list)})", value="```\n" + "\n".join(success_list) + "\n```", inline=False)
        
        if not_found_list:
            embed.add_field(name=f"❌ Not Found ({len(not_found_list)})", value="```\n" + "\n".join(not_found_list) + "\n```", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in /bulkaddpoints command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 14. /ADDEXEMPT COMMAND ---
@client.tree.command(name="addexempt", description="Grant a member immunity from inactivity tracking.")
@app_commands.describe(
    rsn="The member's RSN (current or past).",
    reason="The reason for this exemption (e.g., 'Taking a break from the game').",
    days="Number of days for the exemption (defaults to 90).",
    publish="True to post the confirmation publicly."
)
@check_staff_role("General")
async def add_exempt(interaction: discord.Interaction, rsn: str, reason: str, days: int = 90, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /addexempt rsn='{rsn}' reason='{reason}' days={days} publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /addexempt rsn='{rsn}' reason='{reason}' days={days} publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        # 1. Find the member by RSN
        resolved = resolve_rsn_to_member(rsn)
        if not resolved:
            await interaction.followup.send(f"Error: RSN `{rsn}` not found in the database.", ephemeral=True)
            return
        member_id = resolved['member_id']
        member_rsn = resolved['rsn']
        
        # 2. Check if they already have an active exemption
        existing_exemption = supabase.table('inactivity_exemptions') \
            .select('id, expiration_date') \
            .eq('member_id', member_id) \
            .gte('expiration_date', datetime.now().isoformat()) \
            .execute()
        
        if existing_exemption.data:
            existing_exp = existing_exemption.data[0]['expiration_date']
            exp_date_obj = discord.utils.parse_time(existing_exp)
            formatted_exp = f"<t:{int(exp_date_obj.timestamp())}:D>"
            await interaction.followup.send(
                f"ℹ️ `{member_rsn}` already has an active exemption until {formatted_exp}.\n"
                f"If you need to extend it, please remove the old exemption first.",
                ephemeral=True
            )
            return
        
        # 3. Get staff member ID
        staff_member_id = get_staff_member_id(interaction)
        
        # 4. Calculate expiration date
        from dateutil.relativedelta import relativedelta
        expiration_date = datetime.now() + relativedelta(days=days)
        
        # 5. Insert exemption
        supabase.table('inactivity_exemptions').insert({
            'member_id': member_id,
            'expiration_date': expiration_date.isoformat(),
            'granted_by_member_id': staff_member_id,
            'reason': reason
        }).execute()
        
        # 6. Send confirmation
        exp_date_obj = discord.utils.parse_time(expiration_date.isoformat())
        formatted_exp = f"<t:{int(exp_date_obj.timestamp())}:D>"
        
        embed = discord.Embed(
            title="✅ Inactivity Exemption Granted",
            color=discord.Color.green()
        )
        embed.add_field(name="Member", value=member_rsn, inline=True)
        embed.add_field(name="Expires", value=formatted_exp, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text="This member will be skipped in inactivity checks until the expiration date.")
        
        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)
    except Exception as e:
        log.error(f"Error in /addexempt command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)

# --- 15. COMPETITION POINT COMMANDS ---

async def process_competition_points(
    interaction: discord.Interaction, 
    first: str, 
    second: str, 
    third: str, 
    participants: str, 
    points_map: dict, 
    reason_prefix: str, 
    publish: bool
):
    """
    Helper to process points for BOTM, SOTM, and Big Booty.
    points_map should be: {'1st': int, '2nd': int, '3rd': int, 'participation': int}
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    current_month = datetime.now().strftime('%B %Y') # e.g., "November 2025"
    full_reason = f"{reason_prefix} {current_month}"
    
    log.info(f"[{timestamp}] Competition command ({reason_prefix}) used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] Competition command ({reason_prefix}) used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)

    # 1. Collect all RSNs to resolve
    # We map normalized_rsn -> {'rank': '1st'/'2nd'/'3rd'/'participation', 'original': 'RsN'}
    # Note: If a user is in multiple slots (unlikely but possible), we'll just take the highest value or process sequentially.
    # For simplicity, we'll process them as a list of transactions.
    
    targets = []
    if first:
        first_list = [r.strip() for r in first.split(',') if r.strip()]
        for f in first_list:
            targets.append({'rsn': f, 'points': points_map['1st'], 'rank': '1st Place'})
    if second:
        second_list = [r.strip() for r in second.split(',') if r.strip()]
        for s in second_list:
            targets.append({'rsn': s, 'points': points_map['2nd'], 'rank': '2nd Place'})
    if third:
        third_list = [r.strip() for r in third.split(',') if r.strip()]
        for t in third_list:
            targets.append({'rsn': t, 'points': points_map['3rd'], 'rank': '3rd Place'})
    
    if participants:
        part_list = [p.strip() for p in participants.split(',') if p.strip()]
        for p in part_list:
            targets.append({'rsn': p, 'points': points_map['participation'], 'rank': 'Participant'})

    if not targets:
        await interaction.followup.send("Error: No RSNs provided.", ephemeral=True)
        return

    try:
        # 2. Resolve RSNs to Member IDs
        # Fetch all member RSNs to minimize queries (or we could `in_` query if list is small, but map is safer for normalization)
        all_rsns_res = supabase.table('member_rsns').select('rsn, member_id').execute()
        rsn_map = {normalize_string(item['rsn']): item for item in all_rsns_res.data}

        transactions = []
        report_lines = []
        not_found = []

        for target in targets:
            norm = normalize_string(target['rsn'])
            if norm in rsn_map:
                member_data = rsn_map[norm]
                transactions.append({
                    'member_id': member_data['member_id'],
                    'modification': target['points'],
                    'reason': full_reason
                })
                report_lines.append(f"**{target['rank']}**: {member_data['rsn']} (+{target['points']})")
            else:
                not_found.append(f"{target['rsn']} ({target['rank']})")

        # 3. Execute Transactions
        if transactions:
            supabase.table('event_point_transactions').insert(transactions).execute()

        # 4. Build Embed
        embed = discord.Embed(
            title=f"Points Added: {reason_prefix.title()}",
            description=f"**Month:** {current_month}",
            color=discord.Color.gold()
        )
        
        if report_lines:
            # Split into chunks if too long (basic check)
            chunk_str = "\n".join(report_lines)
            if len(chunk_str) > 1000:
                embed.add_field(name="Results", value=chunk_str[:1000] + "...", inline=False)
            else:
                embed.add_field(name="Results", value=chunk_str, inline=False)
        
        if not_found:
            embed.add_field(name="❌ RSNs Not Found", value="\n".join(not_found), inline=False)

        if not transactions and not_found:
            embed.description = "No valid members found to add points to."
            embed.color = discord.Color.red()

        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in competition command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


@client.tree.command(name="addpointsbotm", description="Add points for Boss of the Month.")
@app_commands.describe(
    first="Comma-separated list of 1st place RSNs (12 pts each)",
    second="Comma-separated list of 2nd place RSNs (7 pts each)",
    third="Comma-separated list of 3rd place RSNs (5 pts each)",
    participants="Comma-separated list of other participants (3 pts each)",
    publish="True to post publicly"
)
@check_staff_role("Captain")
async def add_points_botm(interaction: discord.Interaction, first: str, second: str, third: str, participants: str, publish: bool = False):
    points = {'1st': 12, '2nd': 7, '3rd': 5, 'participation': 3}
    await process_competition_points(interaction, first, second, third, participants, points, "boss of the month", publish)


@client.tree.command(name="addpointssotm", description="Add points for Skill of the Month.")
@app_commands.describe(
    first="Comma-separated list of 1st place RSNs (12 pts each)",
    second="Comma-separated list of 2nd place RSNs (7 pts each)",
    third="Comma-separated list of 3rd place RSNs (5 pts each)",
    participants="Comma-separated list of other participants (3 pts each)",
    publish="True to post publicly"
)
@check_staff_role("Captain")
async def add_points_sotm(interaction: discord.Interaction, first: str, second: str, third: str, participants: str, publish: bool = False):
    points = {'1st': 12, '2nd': 7, '3rd': 5, 'participation': 3}
    await process_competition_points(interaction, first, second, third, participants, points, "skill of the month", publish)


@client.tree.command(name="addpointsbigbooty", description="Add points for Big Booty (Clue of the Month).")
@app_commands.describe(
    first="Comma-separated list of 1st place RSNs (20 pts each)",
    second="Comma-separated list of 2nd place RSNs (15 pts each)",
    third="Comma-separated list of 3rd place RSNs (10 pts each)",
    participants="Comma-separated list of other participants (5 pts each)",
    publish="True to post publicly"
)
@check_staff_role("Captain")
async def add_points_bigbooty(interaction: discord.Interaction, first: str, second: str, third: str, participants: str, publish: bool = False):
    points = {'1st': 20, '2nd': 15, '3rd': 10, 'participation': 5}
    await process_competition_points(interaction, first, second, third, participants, points, "big booty", publish)


# --- 16. /CHECK-INACTIVES COMMAND ---
@client.tree.command(name="checkinactives", description="Check for members with 0 XP gain in their check period.")
@app_commands.describe(
    publish="False (default). True to post the report publicly."
)
@check_staff_role("General")
async def check_inactives(interaction: discord.Interaction, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /checkinactives publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /checkinactives publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        report_string = await asyncio.to_thread(
            inactivity_logic.run_inactivity_check,
            supabase
        )
        
        log.info("Inactivity check complete. Sending report.")
        
        if len(report_string) > 1900:
            await interaction.followup.send(
                "Inactivity check complete. The report is too long, so it's attached as a file.",
                file=discord.File(StringIO(report_string), "inactivity_report.txt"),
                ephemeral=is_ephemeral
            )
        else:
            await interaction.followup.send(
                f"Inactivity check complete.\n```\n{report_string}\n```",
                ephemeral=is_ephemeral
            )
    except Exception as e:
        log.error(f"CRITICAL Error in /check-inactives command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"A critical error occurred. Check the bot console logs: `{e}`", ephemeral=True)


# --- 16.5 /CHECK-NO-DISCORD COMMAND ---
async def generate_no_discord_embed() -> discord.Embed:
    """Helper to query active members with no linked Discord and generate the embed."""
    # 1. Fetch active members with no discord_id
    members_res = supabase.table('members') \
        .select('id') \
        .eq('status', 'Active') \
        .is_('discord_id', 'null') \
        .execute()
        
    if not members_res.data:
        return discord.Embed(
            title="Active Members with No Discord",
            description="✅ All active clan members have a linked Discord ID!",
            color=discord.Color.green()
        )

    member_ids = [m['id'] for m in members_res.data]
    
    # 2. Fetch primary RSNs for these members
    rsn_res = supabase.table('member_rsns') \
        .select('rsn') \
        .eq('is_primary', True) \
        .in_('member_id', member_ids) \
        .execute()
        
    rsns = [r['rsn'] for r in rsn_res.data]
    rsns.sort(key=str.lower)
    
    # 3. Format the response
    embed = discord.Embed(
        title=f"Active Members with No Discord ({len(rsns)})",
        color=discord.Color.orange()
    )
    
    if rsns:
        rsns_list_str = "\n".join(f"• {rsn}" for rsn in rsns)
        if len(rsns_list_str) > 4000:
            embed.description = "Here is the list of active members with no linked Discord ID (truncated due to length):\n\n" + rsns_list_str[:3800] + "\n... (list truncated)"
        else:
            embed.description = "Here is the list of active members with no linked Discord ID:\n\n" + rsns_list_str
    else:
        embed.description = "No RSNs found for these active members."
        
    return embed


@client.tree.command(name="check-no-discord", description="Checks for active clan members with no linked Discord ID")
@app_commands.describe(
    publish="False (default). True to post the report publicly."
)
@check_staff_role("Captain")
async def check_no_discord(interaction: discord.Interaction, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /check-no-discord publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /check-no-discord publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        embed = await generate_no_discord_embed()
        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)
    except Exception as e:
        log.error(f"Error in /check-no-discord command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 16.6 /CHECK-INACTIVITY-EXEMPTIONS COMMAND ---
@client.tree.command(name="check-inactivity-exemptions", description="Check for current inactivity exemptions.")
@app_commands.describe(
    publish="False (default). True to post the report publicly."
)
@check_staff_role("Captain")
async def check_inactivity_exemptions(interaction: discord.Interaction, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /check-inactivity-exemptions publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /check-inactivity-exemptions publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        now_str = datetime.now().isoformat()
        exemptions_res = supabase.table('inactivity_exemptions') \
            .select('member_id, expiration_date, granted_by_member_id, granted_date, reason') \
            .gt('expiration_date', now_str) \
            .execute()
            
        exemptions_data = exemptions_res.data or []
        
        if not exemptions_data:
            await interaction.followup.send("✅ No active inactivity exemptions found.", ephemeral=is_ephemeral)
            return

        # Fetch all primary RSNs to build a mapping from member_id -> RSN
        rsn_res = supabase.table('member_rsns') \
            .select('member_id, rsn') \
            .eq('is_primary', True) \
            .execute()
        
        rsn_map = {item['member_id']: item['rsn'] for item in rsn_res.data or []}
        
        # Sort exemptions by expiration_date ascending (closest to expire first)
        exemptions_data = sorted(exemptions_data, key=lambda x: x.get('expiration_date') or '')

        def format_db_date(date_str: str) -> str:
            if not date_str:
                return "Unknown"
            try:
                parsed = discord.utils.parse_time(date_str)
                if parsed:
                    return parsed.strftime('%Y-%m-%d')
            except Exception:
                pass
            return date_str

        # Format rows
        lines = [
            "rsn | expiration date | who granted it (rsn) | granted date | reason",
            "------------------------------------------------------------------"
        ]
        
        for ex in exemptions_data:
            member_rsn = rsn_map.get(ex['member_id'], "Unknown")
            granter_id = ex.get('granted_by_member_id')
            granter_rsn = rsn_map.get(granter_id, "Unknown") if granter_id else "Unknown"
            
            exp_date = format_db_date(ex.get('expiration_date'))
            grant_date = format_db_date(ex.get('granted_date'))
            reason = ex.get('reason') or "None"
            
            lines.append(f"{member_rsn} | {exp_date} | {granter_rsn} | {grant_date} | {reason}")
            
        report_string = "\n".join(lines)
        
        if len(report_string) > 1900:
            await interaction.followup.send(
                "Inactivity exemptions report is too long, so it's attached as a file.",
                file=discord.File(StringIO(report_string), "inactivity_exemptions.txt"),
                ephemeral=is_ephemeral
            )
        else:
            await interaction.followup.send(
                f"```\n{report_string}\n```",
                ephemeral=is_ephemeral
            )
            
    except Exception as e:
        log.error(f"Error in /check-inactivity-exemptions command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 16.65 /EXPIRE-EXEMPTION COMMAND ---
@client.tree.command(name="expire-exemption", description="Expires an active inactivity exemption for a member.")
@app_commands.describe(
    rsn="The member's RSN.",
    publish="False (default). True to post the confirmation publicly."
)
@check_staff_role("Captain")
async def expire_exemption(interaction: discord.Interaction, rsn: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /expire-exemption rsn='{rsn}' publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /expire-exemption rsn='{rsn}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        # 1. Find the member by RSN
        member_res = supabase.table('member_rsns') \
            .select('member_id, rsn') \
            .ilike('rsn', rsn) \
            .limit(1) \
            .execute()
            
        if not member_res.data:
            await interaction.followup.send(f"Error: RSN `{rsn}` not found in the database.", ephemeral=True)
            return
            
        member_id = member_res.data[0]['member_id']
        member_rsn = member_res.data[0]['rsn']
        
        # 2. Check if they have an active exemption
        now_str = datetime.now().isoformat()
        existing_exemption = supabase.table('inactivity_exemptions') \
            .select('id, expiration_date') \
            .eq('member_id', member_id) \
            .gte('expiration_date', now_str) \
            .execute()
            
        if not existing_exemption.data:
            await interaction.followup.send(f"ℹ️ `{member_rsn}` does not have an active inactivity exemption.", ephemeral=is_ephemeral)
            return
            
        # 3. Update the active exemption(s) expiration date to now
        supabase.table('inactivity_exemptions') \
            .update({'expiration_date': now_str}) \
            .eq('member_id', member_id) \
            .gte('expiration_date', now_str) \
            .execute()
            
        await interaction.followup.send(f"✅ Successfully expired inactivity exemption for `{member_rsn}`.", ephemeral=is_ephemeral)
        
    except Exception as e:
        log.error(f"Error in /expire-exemption command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 16.7 /CLAN-VETERAN-CHECK COMMAND ---
async def run_clan_veteran_check(guild: discord.Guild) -> discord.Embed:
    CLAN_VETERAN_ROLE_ID = 1191649334438133820
    role = guild.get_role(CLAN_VETERAN_ROLE_ID)
    if not role:
        return discord.Embed(
            title="Clan Veteran Check Failed",
            description=f"❌ Could not find Clan Veteran role with ID `{CLAN_VETERAN_ROLE_ID}` in this server.",
            color=discord.Color.red()
        )
        
    try:
        response = supabase.rpc('get_active_members_time_in_clan').execute()
        members = response.data or []
    except Exception as e:
        log.error(f"Failed to fetch members from database: {e}")
        return discord.Embed(
            title="Clan Veteran Check Failed",
            description=f"❌ Database error: {e}",
            color=discord.Color.red()
        )

    added_members = []
    no_discord_members = []
    failed_members = []
    already_had_role = 0
    not_eligible_yet = 0
    
    now = datetime.now(ZoneInfo('UTC'))
    
    for m in members:
        rsn = m.get('primary_rsn') or "Unknown RSN"
        days_in_clan = m.get('days_in_clan', 0)
        discord_id = m.get('discord_id')
        
        if days_in_clan > 730:
            if not discord_id:
                no_discord_members.append(f"• **{rsn}** ({days_in_clan} days in clan)")
                continue
                
            try:
                discord_member = guild.get_member(int(discord_id))
                if not discord_member:
                    discord_member = await guild.fetch_member(int(discord_id))
                    
                if not discord_member:
                    failed_members.append((rsn, f"Could not find Discord user with ID `{discord_id}` in this server"))
                    continue
                    
                if role in discord_member.roles:
                    already_had_role += 1
                else:
                    try:
                        await discord_member.add_roles(role, reason="Clan Veteran check (automatic promotion for >2y in clan)")
                        added_members.append(f"• **{rsn}** (<@{discord_id}>) - {days_in_clan} days")
                    except discord.Forbidden:
                        failed_members.append((rsn, "Bot lacks 'Manage Roles' permission or role is higher than Bot's role"))
                    except Exception as role_err:
                        failed_members.append((rsn, f"Failed to add role: {role_err}"))
            except discord.NotFound:
                failed_members.append((rsn, f"Discord user ID `{discord_id}` not found in this server"))
            except Exception as member_err:
                failed_members.append((rsn, f"Error fetching member: {member_err}"))
        else:
            not_eligible_yet += 1
            
    embed = discord.Embed(
        title="🛡️ Clan Veteran Role Check Report",
        timestamp=datetime.now(),
        color=discord.Color.gold()
    )
    embed.add_field(name="✅ Roles Added", value=str(len(added_members)), inline=True)
    embed.add_field(name="✨ Already Had Role", value=str(already_had_role), inline=True)
    embed.add_field(name="⏳ Not Eligible Yet (<2y)", value=str(not_eligible_yet), inline=True)
    
    if added_members:
        added_str = "\n".join(added_members)
        if len(added_str) > 1024:
            added_str = added_str[:1000] + "\n... (truncated)"
        embed.add_field(name="🎉 Added Role To", value=added_str, inline=False)
    else:
        embed.add_field(name="🎉 Added Role To", value="No new members needed the role.", inline=False)
        
    if no_discord_members:
        no_discord_str = "\n".join(no_discord_members)
        if len(no_discord_str) > 1024:
            no_discord_str = no_discord_str[:1000] + "\n... (truncated)"
        embed.add_field(name="⚠️ Eligible but No Discord Linked", value=no_discord_str, inline=False)
        
    if failed_members:
        failed_str = "\n".join(f"• **{r}**: {err}" for r, err in failed_members)
        if len(failed_str) > 1024:
            failed_str = failed_str[:1000] + "\n... (truncated)"
        embed.add_field(name="❌ Errors", value=failed_str, inline=False)
        
    embed.set_footer(text="OnlyFEs Clan Veteran Check Utility")
    return embed


@client.tree.command(name="clan-veteran-check", description="Checks and updates Clan Veteran roles for members with >2y in the clan.")
@app_commands.describe(
    publish="False (default). True to post the report publicly."
)
@check_staff_role("Captain")
async def clan_veteran_check(interaction: discord.Interaction, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /clan-veteran-check publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /clan-veteran-check publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        embed = await run_clan_veteran_check(interaction.guild)
        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)
    except Exception as e:
        log.error(f"Error in /clan-veteran-check command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 17. /UPDATE-EP-LEADERBOARD COMMAND ---
@client.tree.command(name="updateepleaderboard", description="Manually update the EP leaderboard on GitHub Pages.")
@app_commands.describe(
    publish="False (default). True to post the confirmation publicly."
)
@check_staff_role("Commander")
async def update_ep_leaderboard_command(interaction: discord.Interaction, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /updateepleaderboard publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /updateepleaderboard publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        if not GITHUB_TOKEN:
            await interaction.followup.send("Error: GITHUB_TOKEN not configured.", ephemeral=True)
            return
        
        # Update leaderboard
        success, message = await asyncio.to_thread(
            github_leaderboard.update_leaderboard,
            supabase,
            GITHUB_TOKEN
        )
        
        if success:
            await interaction.followup.send(f"✅ {message}", ephemeral=is_ephemeral)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)
        
    except Exception as e:
        log.error(f"Error in /updateepleaderboard command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)

# --- 17.5 /TLDR COMMAND ---
@client.tree.command(name="tldr", description="Summarize the staff channel conversation from a relative time or message ID.")
@app_commands.describe(
    time="Relative time window to summarize (e.g., 2h, 1d 4h, 30m).",
    message_id="Discord message ID representing the start of the summary window.",
    testing="True to dump the conversation array as a JSON file and skip Gemini."
)
@check_staff_role("Captain")
async def tldr(interaction: discord.Interaction, time: str = None, message_id: str = None, testing: bool = False):
    # Log usage
    timestamp_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp_str}] /tldr time={time} message_id={message_id} testing={testing} used by {interaction.user} in #{interaction.channel}")
    await log_command_use(f"[{timestamp_str}] /tldr time={time} message_id={message_id} testing={testing} used by {interaction.user} in #{interaction.channel}")
    
    # 1. Quota check first (if not testing)
    gemini_key = None
    if not testing:
        gemini_key = os.getenv("IA_SUMMARIZE_GEMINI_API_KEY")
        if not gemini_key:
            log.error("Gemini API key (IA_SUMMARIZE_GEMINI_API_KEY) is missing.")
            await interaction.response.send_message("Gemini Quota Reached, Guess you have to read it now", ephemeral=True)
            return

        quota_ok = await check_gemini_quota(gemini_key)
        if not quota_ok:
            await interaction.response.send_message("Gemini Quota Reached, Guess you have to read it now", ephemeral=True)
            return

    # 2. Check channel second
    channel = interaction.channel
    matriarch_id = get_matriarch_id(channel)
    if matriarch_id != 1059296867663491233:
        await interaction.response.send_message("I can only summarize staff channels, you're going to have to read that channel yourself!", ephemeral=True)
        return

    # 3. Check arguments
    if not time and not message_id:
        await interaction.response.send_message("You must provide at least one of time or message_id to start your summary window.", ephemeral=True)
        return

    # Defer interaction: always non-ephemeral to allow conditional public followups
    await interaction.response.defer(ephemeral=False)

    try:
        # Determine start snowflake
        start_snowflake = None
        if message_id:
            try:
                start_snowflake = int(message_id)
            except ValueError:
                await interaction.followup.send("❌ Invalid `message_id` format. Please provide a valid integer message ID.", ephemeral=True)
                return
        else:
            # Parse time
            dt_threshold = parse_duration(time)
            if not dt_threshold:
                await interaction.followup.send("❌ Invalid `time` format. Please use formats like '2h', '1d 4h', '30m'.", ephemeral=True)
                return
            start_snowflake = discord.utils.time_snowflake(dt_threshold)

        # Get all messages using Direct REST endpoint with pagination
        all_messages = []
        after_id = start_snowflake
        
        async with aiohttp.ClientSession() as session:
            # Pagination loop
            while True:
                url = f"https://discord.com/api/v10/channels/{channel.id}/messages?limit=100&after={after_id}"
                data = await discord_api_request(session, "GET", url)
                if not data:
                    break
                
                all_messages.extend(data)
                
                # Find maximum message ID in this batch to progress
                max_id = max(int(m['id']) for m in data)
                after_id = max_id
                
                if len(data) < 100:
                    break
            
            # Sort messages chronologically by ID/timestamp
            all_messages.sort(key=lambda m: int(m['id']))
            
            if not all_messages:
                await interaction.followup.send("No messages found in the specified window.", ephemeral=True)
                return

            if len(all_messages) < SUMMARIZE_MIN_MESSAGES_THRESHOLD:
                caller_id = interaction.user.id
                caller_name = interaction.user.display_name
                msg_count = len(all_messages)
                if caller_id == 288564337218682892:
                    response_text = f"Really? You want to use an LLM to summarize {msg_count} messages? I expected better.. Oh, wait, {caller_name}? I was warned about you. Read it yourself."
                else:
                    response_text = f"Really? You want to use an LLM to summarize {msg_count} messages? I expected this from Bristle, not from you, {caller_name}"
                await interaction.followup.send(response_text, ephemeral=True)
                return

            if len(all_messages) > SUMMARIZE_MAX_MESSAGES_THRESHOLD:
                await interaction.followup.send(f"That's too many messages to summarize. Please try again with a smaller time window.", ephemeral=True)
                return

            # Grab user display names via /guilds/{guild_id}/members/{user_id} with cache
            guild_id = channel.guild.id
            display_name_cache = {}
            conversation_array = []
            
            for msg in all_messages:
                # Strip metadata: keep content, timestamp, author.id
                content = msg.get('content', '')
                timestamp_val = msg.get('timestamp')
                author_id = msg.get('author', {}).get('id')
                
                if not author_id:
                    continue
                    
                if author_id not in display_name_cache:
                    member_url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{author_id}"
                    member_data = await discord_api_request(session, "GET", member_url)
                    if member_data:
                        nick = member_data.get('nick')
                        user = member_data.get('user', {})
                        global_name = user.get('global_name')
                        username = user.get('username')
                        display_name = nick or global_name or username or str(author_id)
                    else:
                        display_name = msg.get('author', {}).get('username') or str(author_id)
                    display_name_cache[author_id] = display_name
                
                display_name = display_name_cache[author_id]
                
                # Assemble conversation turn
                conversation_array.append({
                    "message": content,
                    "timestamp": timestamp_val,
                    "display_name": display_name
                })
            
            if testing:
                convo_json_str = json.dumps(conversation_array, indent=2)
                file_data = StringIO(convo_json_str)
                discord_file = discord.File(file_data, filename="conversation_dump.json")
                await interaction.followup.send(
                    content=f"🧪 **Testing Mode:** Fetched {len(all_messages)} messages successfully. Below is the conversation array dump:",
                    file=discord_file,
                    ephemeral=testing
                )
                return
            
            # Pass conversation array to Gemini API along with prompt
            conversation_json = json.dumps(conversation_array, indent=2)
            prompt_text = f"{SUMMARIZE_PROMPT}\n\nConversation data:\n{conversation_json}"
            
            gemini_url = f"https://generativelanguage.googleapis.com/v1/models/{GEMINI_MODEL}:generateContent?key={gemini_key}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": prompt_text
                            }
                        ]
                    }
                ]
            }
            
            async with session.post(gemini_url, json=payload, headers={"Content-Type": "application/json"}) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    log.info(f"Gemini API generateContent on v1 failed (status {resp.status}), attempting v1beta fallback: {error_text}")
                    
                    fallback_gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={gemini_key}"
                    async with session.post(fallback_gemini_url, json=payload, headers={"Content-Type": "application/json"}) as resp_fb:
                        if resp_fb.status != 200:
                            error_text_fb = await resp_fb.text()
                            log.error(f"Gemini API generateContent failed on fallback with status {resp_fb.status}: {error_text_fb}")
                            await interaction.followup.send("Gemini Quota Reached, Guess you have to read it now", ephemeral=True)
                            return
                        res_data = await resp_fb.json()
                else:
                    res_data = await resp.json()
                
                try:
                    summary_text = res_data['candidates'][0]['content']['parts'][0]['text']
                except (KeyError, IndexError, TypeError) as e:
                    log.error(f"Error parsing Gemini response: {e}\nResponse: {res_data}")
                    await interaction.followup.send("❌ Error parsing the summary from Gemini API.", ephemeral=True)
                    return
            
            # Build and send Embed
            embed = discord.Embed(
                title="📝 Staff Conversation Summary",
                description=summary_text,
                color=discord.Color.blurple(),
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"Summarized {len(all_messages)} messages. Credit to Boolaa for the idea 🧡")
            await interaction.followup.send(embed=embed, ephemeral=testing)
 
    except Exception as e:
        log.error(f"Error in /tldr command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred: `{e}`", ephemeral=True)

# --- 18. SCHEDULED TASKS ---
@tasks.loop(time=[time(hour=0, minute=15), time(hour=12, minute=15)])
async def scheduled_ep_leaderboard():
    """Runs EP leaderboard update daily at 00:15 and 12:15 UTC"""
    log.info("=== Starting scheduled EP leaderboard update ===")
    
    try:
        if not GITHUB_TOKEN:
            log.error("GITHUB_TOKEN not configured. Skipping EP leaderboard update.")
            return
        
        # Update leaderboard
        success, message = await asyncio.to_thread(
            github_leaderboard.update_leaderboard,
            supabase,
            GITHUB_TOKEN
        )
        
        if success:
            log.info(f"EP leaderboard update complete: {message}")
        else:
            log.error(f"EP leaderboard update failed: {message}")
        
    except Exception as e:
        log.error(f"ERROR in scheduled_ep_leaderboard: {e}\n{traceback.format_exc()}")


@tasks.loop(time=[time(hour=0, minute=0), time(hour=12, minute=0)])
async def scheduled_clan_sync():
    """Runs clan sync twice daily at 00:00 and 12:00 UTC"""
    log.info("=== Starting scheduled clan sync ===")
    
    try:
        # Get the sync report channel
        if not SYNC_REPORT_CHANNEL_ID:
            log.error("SYNC_REPORT_CHANNEL_ID not configured. Skipping scheduled sync.")
            return
        
        channel = client.get_channel(int(SYNC_REPORT_CHANNEL_ID))
        if not channel:
            log.error(f"Could not find channel with ID {SYNC_REPORT_CHANNEL_ID}")
            return
        
        # Run the sync (live run, no force)
        report_string, sync_metadata = await asyncio.to_thread(
            clan_sync_logic.run_sync,
            supabase,
            dry_run=False,
            force_run=False
        )
        
        log.info("Scheduled sync complete. Synchronizing Discord roles...")
        
        role_sync_summary = ""
        guild = channel.guild if channel else None
        if not guild and client.guilds:
            guild = client.guilds[0]
            
        if guild:
            try:
                role_sync_summary = await sync_discord_clan_member_roles(guild, sync_metadata, dry_run=False)
            except Exception as re:
                log.error(f"Error in sync_discord_clan_member_roles: {re}")
                role_sync_summary = f"⚠️ Discord Role Sync Error: {re}"
        
        if role_sync_summary:
            report_string += f"\n\n{role_sync_summary}"

        log.info("Scheduled sync complete. Posting report to channel.")
        
        # Post the report
        if len(report_string) > 1900:
            await channel.send(
                "🤖 **Automated Clan Sync Complete**\nThe report is too long, so it's attached as a file.",
                file=discord.File(StringIO(report_string), f"sync_report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt")
            )
        else:
            await channel.send(f"🤖 **Automated Clan Sync Complete**\n```\n{report_string}\n```")
        
        log.info("Scheduled sync report posted successfully.")
        
    except Exception as e:
        log.error(f"ERROR in scheduled_clan_sync: {e}\n{traceback.format_exc()}")
        # Try to post error to channel
        try:
            if SYNC_REPORT_CHANNEL_ID:
                channel = client.get_channel(int(SYNC_REPORT_CHANNEL_ID))
                if channel:
                    await channel.send(f"⚠️ **Automated Clan Sync Failed**\nError: `{e}`\nCheck bot logs for details.")
        except:
            pass  # If we can't post the error, just log it
@tasks.loop(time=[time(hour=14, minute=0)])
async def scheduled_inactivity_check():
    """Runs inactivity check daily at 14:00 UTC"""
    log.info("=== Starting scheduled inactivity check ===")
    
    try:
        # Get the inactivity report channel and thread
        if not INACTIVITY_REPORT_CHANNEL_ID:
            log.error("INACTIVITY_REPORT_CHANNEL_ID not configured. Skipping scheduled inactivity check.")
            return
        
        channel = client.get_channel(int(INACTIVITY_REPORT_CHANNEL_ID))
        if not channel:
            log.error(f"Could not find channel with ID {INACTIVITY_REPORT_CHANNEL_ID}")
            return
        
        # If thread ID is provided, try to get the thread
        target = channel
        if INACTIVITY_REPORT_THREAD_ID:
            try:
                thread = channel.get_thread(int(INACTIVITY_REPORT_THREAD_ID))
                if thread:
                    target = thread
                    log.info(f"Posting to thread: {thread.name}")
                else:
                    # Try fetching archived threads
                    log.info("Thread not in cache, attempting to fetch...")
                    thread = await channel.fetch_channel(int(INACTIVITY_REPORT_THREAD_ID))
                    if thread:
                        target = thread
                        log.info(f"Found thread: {thread.name}")
            except Exception as e:
                log.warning(f"Could not find thread {INACTIVITY_REPORT_THREAD_ID}, posting to channel instead: {e}")
        
        # Run the inactivity check
        report_string = await asyncio.to_thread(
            inactivity_logic.run_inactivity_check,
            supabase
        )
        
        log.info("Scheduled inactivity check complete. Posting report.")
        
        # Post the report
        if len(report_string) > 1900:
            await target.send(
                "🤖 **Automated Inactivity Check Complete**\nThe report is too long, so it's attached as a file.",
                file=discord.File(StringIO(report_string), f"inactivity_report_{datetime.now().strftime('%Y%m%d_%H%M')}.txt")
            )
        else:
            await target.send(f"🤖 **Automated Inactivity Check Complete**\n```\n{report_string}\n```")
        
        log.info("Scheduled inactivity report posted successfully.")
        
    except Exception as e:
        log.error(f"ERROR in scheduled_inactivity_check: {e}\n{traceback.format_exc()}")
        # Try to post error to channel
        try:
            if INACTIVITY_REPORT_CHANNEL_ID:
                channel = client.get_channel(int(INACTIVITY_REPORT_CHANNEL_ID))
                if channel:
                    await channel.send(f"⚠️ **Automated Inactivity Check Failed**\nError: `{e}`\nCheck bot logs for details.")
        except:
            pass  # If we can't post the error, just log it
@scheduled_clan_sync.before_loop
async def before_scheduled_clan_sync():
    """Wait for bot to be ready before starting the sync task"""
    await client.wait_until_ready()
    log.info("Bot is ready. Starting scheduled clan sync task.")
@scheduled_inactivity_check.before_loop
async def before_scheduled_inactivity_check():
    """Wait for bot to be ready before starting the inactivity check task"""
    await client.wait_until_ready()
    log.info("Bot is ready. Starting scheduled inactivity check task.")


# --- 18.5 OVERACHIEVERS ---
@client.tree.command(name="overachievers-sync", description="Run the Overachievers check (1st of month typically).")
@app_commands.describe(
    dry_run="True (default) to just see report. False to execute DB writes.",
    publish="False (default). True to post publicly."
)
@check_staff_role("Commander")
async def check_overachievers_sync(interaction: discord.Interaction, dry_run: bool = True, publish: bool = False):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /overachievers-sync dry_run={dry_run} publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /overachievers-sync dry_run={dry_run} publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        skill_emb, act_emb, boss_emb, err_str = await asyncio.to_thread(
            overachievers_logic.run_overachievers_check,
            supabase,
            dry_run=dry_run
        )
        
        if skill_emb is None:
            await interaction.followup.send(f"Critical API Error: {err_str}", ephemeral=True)
            return
            
        await interaction.followup.send(content=f"Overachievers Sync Complete.", embeds=[skill_emb, act_emb, boss_emb], ephemeral=is_ephemeral)
        
        if err_str:
            log.warning(f"Overachievers sync warnings:\n{err_str}")
            if len(err_str) > 1000:
                err_str = err_str[:1000] + "\n... (truncated)"
            await interaction.followup.send(f"Warnings/Errors:\n```text\n{err_str}\n```", ephemeral=True)
            
    except Exception as e:
        log.error(f"CRITICAL Error in /overachievers-sync command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"A critical error occurred. Check the bot console logs: `{e}`", ephemeral=True)

@client.tree.command(name="overachievers", description="Look up which metrics an RSN holds, or who holds a specific metric.")
@app_commands.describe(
    query="RSN (e.g., 'Maikhol') or Metric (e.g., 'Artio')",
    publish="False (default). True to post publicly."
)
async def lookup_overachievers(interaction: discord.Interaction, query: str, publish: bool = False):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /overachievers query='{query}' publish={publish} used by {interaction.user}")
    if not publish:
        await log_command_use(f"[{timestamp}] /overachievers query='{query}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        embed, err_str = await asyncio.to_thread(
            overachievers_logic.get_overachiever_lookup,
            supabase,
            query
        )
        
        if err_str:
            await interaction.followup.send(f"Error: {err_str}", ephemeral=True)
            return
            
        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)
            
    except Exception as e:
        log.error(f"CRITICAL Error in /overachievers lookup: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"A critical error occurred. Check the bot console logs: `{e}`", ephemeral=True)

@tasks.loop(time=[time(hour=0, minute=0)])
async def scheduled_overachievers_check():
    """Runs overachievers check daily at 00:00 UTC but executes ONLY on the 1st of the month"""
    log.info("=== Starting scheduled overachievers check ===")
    
    # Check if it's the first of the month
    if datetime.now(ZoneInfo('UTC')).day != 1:
        log.info("Not the 1st of the month. Skipping overachievers check.")
        return
        
    try:
        if not SYNC_REPORT_CHANNEL_ID:
            log.error("SYNC_REPORT_CHANNEL_ID not configured.")
            return
            
        channel = client.get_channel(int(SYNC_REPORT_CHANNEL_ID))
        if channel:
            skill_emb, act_emb, boss_emb, err_str = await asyncio.to_thread(
                overachievers_logic.run_overachievers_check,
                supabase,
                dry_run=False
            )
            if skill_emb:
                await channel.send("🏆 **Monthly Overachievers Report**", embeds=[skill_emb, act_emb, boss_emb])
            else:
                log.error(f"Failed to generate overachievers report: {err_str}")
    except Exception as e:
        log.error(f"ERROR in scheduled_overachievers_check: {e}")

@scheduled_overachievers_check.before_loop
async def before_scheduled_overachievers_check():
    await client.wait_until_ready()
    log.info("Bot is ready. Starting scheduled overachievers task.")


@tasks.loop(time=[time(hour=0, minute=5)])
async def scheduled_no_discord_check():
    """Runs check-no-discord weekly on Sundays at 00:05 UTC"""
    log.info("=== Starting scheduled no discord check ===")
    
    # Check if today is Sunday (6)
    if datetime.now(ZoneInfo('UTC')).weekday() != 6:
        log.info("Not Sunday. Skipping no discord check.")
        return
        
    try:
        if not SYNC_REPORT_CHANNEL_ID:
            log.error("SYNC_REPORT_CHANNEL_ID not configured. Skipping scheduled no discord check.")
            return
            
        channel = client.get_channel(int(SYNC_REPORT_CHANNEL_ID))
        if not channel:
            log.error(f"Could not find channel with ID {SYNC_REPORT_CHANNEL_ID}")
            return
            
        embed = await generate_no_discord_embed()
        embed.title = f"Weekly Discord Link Check: {embed.title}"
        embed.timestamp = datetime.now()
        
        await channel.send(embed=embed)
        log.info("Scheduled no discord check report posted successfully.")
        
    except Exception as e:
        log.error(f"ERROR in scheduled_no_discord_check: {e}\n{traceback.format_exc()}")
        try:
            if SYNC_REPORT_CHANNEL_ID:
                channel = client.get_channel(int(SYNC_REPORT_CHANNEL_ID))
                if channel:
                    await channel.send(f"⚠️ **Scheduled Discord Link Check Failed**\nError: `{e}`\nCheck bot logs for details.")
        except:
            pass

@scheduled_no_discord_check.before_loop
async def before_scheduled_no_discord_check():
    await client.wait_until_ready()
    log.info("Bot is ready. Starting scheduled no discord check task.")


@tasks.loop(time=[time(hour=0, minute=10)])
async def scheduled_clan_veteran_check():
    """Runs clan veteran check daily at 00:10 UTC but executes ONLY on the 1st of the month"""
    log.info("=== Starting scheduled clan veteran check ===")
    
    # Check if today is the 1st of the month
    if datetime.now(ZoneInfo('UTC')).day != 1:
        log.info("Not the 1st of the month. Skipping scheduled clan veteran check.")
        return
        
    try:
        if not SYNC_REPORT_CHANNEL_ID:
            log.error("SYNC_REPORT_CHANNEL_ID not configured. Skipping scheduled clan veteran check.")
            return
            
        channel = client.get_channel(int(SYNC_REPORT_CHANNEL_ID))
        if not channel:
            log.error(f"Could not find channel with ID {SYNC_REPORT_CHANNEL_ID}")
            return
            
        embed = await run_clan_veteran_check(channel.guild)
        embed.title = f"Monthly Clan Veteran Check: {embed.title}"
        embed.timestamp = datetime.now()
        
        await channel.send(embed=embed)
        log.info("Scheduled clan veteran check report posted successfully.")
        
    except Exception as e:
        log.error(f"ERROR in scheduled_clan_veteran_check: {e}\n{traceback.format_exc()}")
        try:
            if SYNC_REPORT_CHANNEL_ID:
                channel = client.get_channel(int(SYNC_REPORT_CHANNEL_ID))
                if channel:
                    await channel.send(f"⚠️ **Scheduled Clan Veteran Check Failed**\nError: `{e}`\nCheck bot logs for details.")
        except:
            pass

@scheduled_clan_veteran_check.before_loop
async def before_scheduled_clan_veteran_check():
    await client.wait_until_ready()
    log.info("Bot is ready. Starting scheduled clan veteran check task.")


# --- 19. WEEKLY BOUNTY QUEST ---

def _save_bot_state(key: str, value: str) -> None:
    """Upserts a single key in bot_state."""
    supabase.table('bot_state').upsert({'key': key, 'value': value}, on_conflict='key').execute()


async def _load_bounty_state() -> None:
    """Restores bounty_auto_enabled and bounty_active_thread_id from DB on startup."""
    global bounty_auto_enabled, bounty_active_thread_id
    try:
        rows = supabase.table('bot_state').select('key,value').in_('key', ['bounty_auto_enabled', 'bounty_active_thread_id']).execute()
        state = {r['key']: r['value'] for r in (rows.data or [])}
        bounty_auto_enabled = state.get('bounty_auto_enabled', 'false').lower() == 'true'
        raw_thread_id = state.get('bounty_active_thread_id')
        bounty_active_thread_id = int(raw_thread_id) if raw_thread_id else None
        log.info(f"Bounty state restored: auto_enabled={bounty_auto_enabled}, active_thread_id={bounty_active_thread_id}")
    except Exception as e:
        log.error(f"Failed to load bounty state from DB: {e}")


# Channel and message config — swap these out when moving from test to production
BOUNTY_ANNOUNCEMENT_CHANNEL_ID = 1054611693197602936   # test channel (#admin-playground - 1173640617453174835); swap for #event (1054611693197602936) when ready
BOUNTY_THREADS_CHANNEL_ID = 1517972125246292178        # #weekly-bounty threads channel
BOUNTY_ITEMS_THREAD_ID = 1517995249153081585           # "Full item list" thread in #weekly-bounties
BOUNTY_COMPLETIONS_CHANNEL_ID = 1077669229475663893    # #event-winners (completions are posted here)
BOUNTY_STAFF_LOG_CHANNEL_ID = 1490898354908037191      # #bots-staff (staff notifications)
BOUNTY_INFO_CHANNEL_ID = 1517994786408108224           # #weekly-bounties info thread (within weekly-bounty channel)
BOUNTY_ROLE_ID = 1518261554519212176                   # @Weekly bounty role
BOUNTY_CHECK_EMOJI_GREEN_NAME = "Green_Check"
BOUNTY_CHECK_EMOJI_WHITE = "✅"

# Runtime state for automatic bounty management
bounty_auto_enabled: bool = False
bounty_active_thread_id: int | None = None  # set when a bounty thread is created

# Word lists for event password generation (all words ≤ 8 chars, max combined length 16)
_PASSWORD_ADJECTIVES = [
    "Ancient", "Barrows", "Blazing", "Blessed", "Broken",
    "Corrupt", "Cursed", "Daring", "Divine", "Draconic",
    "Emerald", "Fiery", "Frozen", "Gilded", "Glacial",
    "Glowing", "Golden", "Grim", "Haunted", "Holy",
    "Infernal", "Iron", "Loyal", "Mystic", "Primal",
    "Runic", "Sacred", "Shadow", "Sinister", "Twisted",
]
_PASSWORD_NOUNS = [
    "Abyssal", "Adamant", "Ahrim", "Bandos", "Barrows",
    "Cerberus", "Chaos", "Crystal", "Dharok", "Dragon",
    "Duel", "Goblin", "Guthan", "Inferno", "Karil",
    "Kraken", "Mithril", "Monk", "Ranger", "Rune",
    "Scythe", "Slayer", "Thrall", "Torag", "Trident",
    "Verac", "Void", "Whip", "Wyrm", "Zulrah",
]


def _generate_event_password() -> str:
    return random.choice(_PASSWORD_ADJECTIVES) + random.choice(_PASSWORD_NOUNS)


async def fetch_bounty_items() -> list[str]:
    """
    Fetches the bounty item list from the starter message of BOUNTY_ITEMS_THREAD_ID.
    The message is expected to have one item per line (blank lines and list prefixes ignored).
    Returns a list of item name strings.
    """
    async with aiohttp.ClientSession() as session:
        # The starter message of a forum thread shares the thread's ID
        url = f"https://discord.com/api/v10/channels/{BOUNTY_ITEMS_THREAD_ID}/messages/{BOUNTY_ITEMS_THREAD_ID}"
        data = await discord_api_request(session, "GET", url)
        if not data:
            return []
        content = data.get("content", "")
        items = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            # Strip markdown list prefixes (-, *, •) so items can be formatted as a list
            line = line.lstrip("-*•").strip()
            if line:
                items.append(line)
        return items


def _wiki_url(item_name: str) -> str:
    """Returns the OSRS wiki URL for an item, with spaces replaced by underscores."""
    slug = item_name.replace(" ", "_")
    return f"https://oldschool.runescape.wiki/w/{quote(slug, safe='_')}"


def _wiki_image_url(item_name: str) -> str:
    """Returns the OSRS wiki detail image URL for an item."""
    slug = item_name.replace(" ", "_")
    encoded = quote(slug, safe="_'")
    return f"https://oldschool.runescape.wiki/images/{encoded}_detail.png"


def _next_saturday_0600_utc(from_dt: datetime) -> datetime:
    """Returns the next Saturday at 06:00 UTC on or after from_dt."""
    days_until_saturday = (5 - from_dt.weekday()) % 7
    if days_until_saturday == 0 and from_dt.hour >= 6:
        days_until_saturday = 7
    target = from_dt.replace(hour=6, minute=0, second=0, microsecond=0) + timedelta(days=days_until_saturday)
    return target


def _monday_after(close_dt: datetime) -> datetime:
    """Returns the Monday at 06:00 UTC immediately after a Saturday close datetime."""
    # Normalise to Saturday 06:00 first so the result is always exactly 2 days later
    # regardless of what time close_dt actually is.
    saturday = close_dt.replace(hour=6, minute=0, second=0, microsecond=0)
    return saturday + timedelta(days=2)


def _next_monday_0600_utc(from_dt: datetime) -> datetime:
    """Returns the next Monday at 06:00 UTC strictly after from_dt."""
    days_until_monday = (7 - from_dt.weekday()) % 7
    if days_until_monday == 0 and from_dt.hour >= 6:
        days_until_monday = 7
    return from_dt.replace(hour=6, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)


async def _run_generate_bounty(guild: discord.Guild, item_name: str | None = None) -> tuple[bool, str]:
    """
    Core logic: picks an item, creates a thread in BOUNTY_THREADS_CHANNEL_ID,
    and posts an announcement in BOUNTY_ANNOUNCEMENT_CHANNEL_ID.
    Returns (success, message).
    """
    chosen_item = item_name

    if not chosen_item:
        items = await fetch_bounty_items()
        if not items:
            return False, "Could not fetch bounty items list. Check that the reference message is accessible."
        chosen_item = random.choice(items)

    threads_channel = guild.get_channel(BOUNTY_THREADS_CHANNEL_ID)
    if not threads_channel:
        return False, f"Could not find bounty threads channel (ID `{BOUNTY_THREADS_CHANNEL_ID}`)."

    now = datetime.now(ZoneInfo("UTC"))
    week_label = now.strftime("Week of %b %d, %Y")
    thread_name = f"Weekly Bounty – {chosen_item} ({week_label})"

    close_dt = _next_saturday_0600_utc(now)
    close_ts = int(close_dt.timestamp())
    wiki_link = _wiki_url(chosen_item)
    image_url = _wiki_image_url(chosen_item)
    event_password = _generate_event_password()

    opening_post = (
        f"## Weekly Bounty: **{chosen_item}**\n\n"
        f"This week's bounty item is **[{chosen_item}]({wiki_link})**. The event password is **{event_password}**.\n\n"
        f"Post a screenshot of your drop here. Staff will react with ✅ to confirm it counts.\n\n"
        f"*Thread closes <t:{close_ts}:F>.*\n\n"
        f"{image_url}"
    )

    try:
        thread_with_msg = await threads_channel.create_thread(
            name=thread_name,
            content=opening_post,
            auto_archive_duration=10080,  # 7 days
        )
        thread = thread_with_msg.thread
    except Exception as e:
        return False, f"Failed to create thread: {e}"

    # Post announcement
    announcement_channel = guild.get_channel(BOUNTY_ANNOUNCEMENT_CHANNEL_ID)
    if announcement_channel:
        info_channel_mention = f"<#{BOUNTY_INFO_CHANNEL_ID}>"
        embed = discord.Embed(
            title="🎯 New Weekly Bounty!",
            description=(
                f"This week's bounty item is **[{chosen_item}]({wiki_link})**. The event password is **{event_password}**.\n\n"
                f"Head over to {thread.mention} to submit your drop screenshot.\n"
                f"Staff will react with ✅ to confirm eligible submissions.\n\n"
                f"**Reward:** 3 Event Points\n\n"
                f"For more information on the weekly bounty event, see {info_channel_mention}.\n\n"
                f"*Closes <t:{close_ts}:F> (<t:{close_ts}:R>)*"
            ),
            color=discord.Color.gold(),
            timestamp=now,
        )
        embed.set_thumbnail(url=image_url)
        embed.set_footer(text="Good luck, everyone!")
        role_mention = f"<@&{BOUNTY_ROLE_ID}>"
        await announcement_channel.send(content=role_mention, embed=embed)

    global bounty_active_thread_id
    bounty_active_thread_id = thread.id
    _save_bot_state('bounty_active_thread_id', str(thread.id))

    try:
        supabase.table('bounties').insert({
            'item_name': chosen_item,
            'thread_id': thread.id,
            'password': event_password,
            'date_start': now.isoformat(),
            'date_end': close_dt.isoformat(),
            'is_active': True,
        }).execute()
    except Exception as e:
        log.error(f"Failed to insert bounty row into DB: {e}")

    return True, f"Created thread **{thread_name}** and posted announcement. Thread: {thread.mention}"


async def _check_bounty_completions(thread: discord.Thread) -> list[dict]:
    """
    Scans all messages in a bounty thread.
    Returns a list of dicts {user_id, display_name, rsn} for each unique user whose
    message has a Green_Check or white_check_mark reaction from staff.
    RSN is looked up from the database via discord_id; falls back to display_name if not found.
    """
    winners: dict[int, str] = {}  # user_id -> display_name

    async for message in thread.history(limit=None, oldest_first=True):
        if not message.reactions:
            continue
        for reaction in message.reactions:
            emoji = reaction.emoji
            is_green = isinstance(emoji, discord.PartialEmoji | discord.Emoji) and emoji.name == BOUNTY_CHECK_EMOJI_GREEN_NAME
            is_white = emoji == BOUNTY_CHECK_EMOJI_WHITE or (hasattr(emoji, "name") and emoji.name == "white_check_mark")
            if is_green or is_white:
                author = message.author
                if author and not author.bot:
                    winners[author.id] = author.display_name
                break

    # Look up member_id and RSN from DB by discord_id
    result = []
    for uid, display_name in winners.items():
        rsn = None
        member_id = None
        try:
            member_res = supabase.table('members').select('id').eq('discord_id', uid).limit(1).execute()
            if member_res.data:
                member_id = member_res.data[0]['id']
                primary_res = supabase.table('member_rsns') \
                    .select('rsn') \
                    .eq('member_id', member_id) \
                    .eq('is_primary', True) \
                    .limit(1) \
                    .execute()
                if primary_res.data:
                    rsn = primary_res.data[0]['rsn']
        except Exception as e:
            log.warning(f"Could not look up RSN for discord_id {uid}: {e}")
        result.append({"user_id": uid, "display_name": display_name, "rsn": rsn, "member_id": member_id})

    return result


async def _award_bounty_ep(winners: list[dict], bounty_id: int, guild: discord.Guild) -> None:
    """
    Inserts EP transactions for each winner who hasn't already been awarded for this bounty,
    then posts a staff log summary to BOUNTY_STAFF_LOG_CHANNEL_ID.
    winners must be the list returned by _check_bounty_completions (includes member_id).
    """
    reason = f"Bounty Completion - {bounty_id}"
    awarded = []
    already_awarded = []
    for w in winners:
        if not w.get('member_id'):
            log.warning(f"_award_bounty_ep: no member_id for discord_id {w['user_id']}, skipping EP award")
            continue
        label = w['rsn'] or w['display_name']
        try:
            existing = supabase.table('event_point_transactions') \
                .select('id') \
                .eq('member_id', w['member_id']) \
                .eq('reason', reason) \
                .limit(1) \
                .execute()
            if existing.data:
                already_awarded.append(label)
                log.info(f"_award_bounty_ep: skipping {label} — EP already awarded for bounty {bounty_id}")
                continue
            supabase.table('event_point_transactions').insert({
                'member_id': w['member_id'],
                'modification': 3,
                'reason': reason,
            }).execute()
            awarded.append(label)
        except Exception as e:
            log.error(f"_award_bounty_ep: failed to process EP for member {w['member_id']}: {e}")

    staff_channel = guild.get_channel(BOUNTY_STAFF_LOG_CHANNEL_ID)
    if staff_channel:
        parts = []
        if awarded:
            rsn_list = ", ".join(f"**{r}**" for r in awarded)
            parts.append(f"3 EP awarded to: {rsn_list}")
        if already_awarded:
            skip_list = ", ".join(f"**{r}**" for r in already_awarded)
            parts.append(f"already awarded (skipped): {skip_list}")
        if parts:
            await staff_channel.send(f"✅ Bounty check complete — " + "; ".join(parts))
        else:
            await staff_channel.send(
                f"⚠️ Bounty check complete — no EP awarded (winners had no linked member records)."
            )


@client.tree.command(name="generate-new-bounty-quest", description="Generate a new weekly bounty quest thread and announcement.")
@app_commands.describe(
    item_name="Optional: specify the bounty item. If omitted, one is chosen randomly from the list.",
    publish="True to post the confirmation publicly."
)
@check_staff_role("Owner")
async def generate_new_bounty_quest(interaction: discord.Interaction, item_name: str = None, publish: bool = False):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /generate-new-bounty-quest item_name='{item_name}' publish={publish} used by {interaction.user}")
    await log_command_use(f"[{timestamp}] /generate-new-bounty-quest item_name='{item_name}' publish={publish} used by {interaction.user}")

    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)

    try:
        success, msg = await _run_generate_bounty(interaction.guild, item_name)
        if success:
            await interaction.followup.send(f"✅ {msg}", ephemeral=is_ephemeral)
        else:
            await interaction.followup.send(f"❌ {msg}", ephemeral=True)
    except Exception as e:
        log.error(f"Error in /generate-new-bounty-quest: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred: `{e}`", ephemeral=True)


@client.tree.command(name="close-bounty-quest", description="Lock a bounty quest thread.")
@app_commands.describe(
    thread_id="The ID of the bounty thread to lock.",
    publish="True to post the confirmation publicly."
)
@check_staff_role("Owner")
async def close_bounty_quest(interaction: discord.Interaction, thread_id: str, publish: bool = False):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /close-bounty-quest thread_id='{thread_id}' publish={publish} used by {interaction.user}")
    await log_command_use(f"[{timestamp}] /close-bounty-quest thread_id='{thread_id}' publish={publish} used by {interaction.user}")

    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)

    try:
        thread_id_int = int(thread_id)
    except ValueError:
        await interaction.followup.send("❌ Invalid thread ID — must be a numeric Discord snowflake.", ephemeral=True)
        return

    try:
        thread = interaction.guild.get_channel(thread_id_int)
        if not thread:
            thread = await interaction.guild.fetch_channel(thread_id_int)

        if not isinstance(thread, discord.Thread):
            await interaction.followup.send(f"❌ Channel `{thread_id}` is not a thread.", ephemeral=True)
            return

        await thread.edit(locked=True, archived=True)
        await interaction.followup.send(f"✅ Thread **{thread.name}** has been locked and archived.", ephemeral=is_ephemeral)
    except discord.NotFound:
        await interaction.followup.send(f"❌ Could not find a thread with ID `{thread_id}`.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ Bot lacks permission to lock that thread.", ephemeral=True)
    except Exception as e:
        log.error(f"Error in /close-bounty-quest: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred: `{e}`", ephemeral=True)


@client.tree.command(name="check-bounty-completion", description="Check a bounty thread for confirmed submissions (✅ reactions).")
@app_commands.describe(
    thread_id="The ID of the bounty thread to check.",
    publish="True to post the results publicly."
)
@check_staff_role("Owner")
async def check_bounty_completion(interaction: discord.Interaction, thread_id: str, publish: bool = False):
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /check-bounty-completion thread_id='{thread_id}' publish={publish} used by {interaction.user}")
    await log_command_use(f"[{timestamp}] /check-bounty-completion thread_id='{thread_id}' publish={publish} used by {interaction.user}")

    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)

    try:
        thread_id_int = int(thread_id)
    except ValueError:
        await interaction.followup.send("❌ Invalid thread ID — must be a numeric Discord snowflake.", ephemeral=True)
        return

    try:
        thread = interaction.guild.get_channel(thread_id_int)
        if not thread:
            thread = await interaction.guild.fetch_channel(thread_id_int)

        if not isinstance(thread, discord.Thread):
            await interaction.followup.send(f"❌ Channel `{thread_id}` is not a thread.", ephemeral=True)
            return

        winners = await _check_bounty_completions(thread)

        now = datetime.now(ZoneInfo("UTC"))
        week_label = now.strftime("Week of %b %d, %Y")
        # Strip "Weekly Bounty – " prefix from thread name to get just the item name
        raw_name = thread.name
        for prefix in ("Weekly Bounty – ", "Weekly Bounty - "):
            if raw_name.startswith(prefix):
                raw_name = raw_name[len(prefix):]
                break
        # Strip trailing "(Week of ...)" if present
        if " (" in raw_name:
            raw_name = raw_name[:raw_name.rfind(" (")]
        item_name = raw_name

        embed = discord.Embed(
            title=f"Weekly Bounty Completions: {item_name} ({week_label})",
            color=discord.Color.green() if winners else discord.Color.orange(),
            timestamp=datetime.now(ZoneInfo("UTC")),
        )

        if winners:
            winner_lines = "\n".join(f"• <@{w['user_id']}>" for w in winners)

            next_bounty_dt = _next_monday_0600_utc(now)
            next_bounty_ts = int(next_bounty_dt.timestamp())
            threads_channel_mention = f"<#{BOUNTY_THREADS_CHANNEL_ID}>"

            embed.description = (
                f"The following members successfully obtained the drop:\n{winner_lines}\n\n"
                f"Congratulations to you all, you've each earned 3 Event Points.\n\n"
                f"A new bounty will be live <t:{next_bounty_ts}:F> (<t:{next_bounty_ts}:R>), keep your eyes on {threads_channel_mention}!"
            )
        else:
            embed.description = "No confirmed completions found (no ✅ reactions on any messages yet)."

        embed.set_footer(text=f"Thread ID: {thread_id}")

        if publish:
            completions_channel = interaction.guild.get_channel(BOUNTY_COMPLETIONS_CHANNEL_ID)
            if completions_channel:
                await completions_channel.send(embed=embed)
                await interaction.followup.send(f"✅ Posted to {completions_channel.mention}.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Could not find completions channel (ID `{BOUNTY_COMPLETIONS_CHANNEL_ID}`).", ephemeral=True)
            if winners:
                bounty_res = supabase.table('bounties').select('id').eq('thread_id', thread_id_int).limit(1).execute()
                bounty_db_id = bounty_res.data[0]['id'] if bounty_res.data else None
                if bounty_db_id:
                    await _award_bounty_ep(winners, bounty_db_id, interaction.guild)
                else:
                    log.warning(f"/check-bounty-completion: no bounties row for thread_id {thread_id_int}, cannot award EP")
        else:
            await interaction.followup.send(embed=embed, ephemeral=True)

    except discord.NotFound:
        await interaction.followup.send(f"❌ Could not find a thread with ID `{thread_id}`.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send("❌ Bot lacks permission to read that thread.", ephemeral=True)
    except Exception as e:
        log.error(f"Error in /check-bounty-completion: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred: `{e}`", ephemeral=True)


# --- 20. AUTOMATIC BOUNTY SCHEDULED TASKS ---

@tasks.loop(time=[time(hour=6, minute=0, tzinfo=ZoneInfo("UTC"))])
async def scheduled_bounty_generate():
    """Runs every Monday at 06:00 UTC. Generates a new bounty if auto mode is enabled."""
    if not bounty_auto_enabled:
        return
    now = datetime.now(ZoneInfo("UTC"))
    if now.weekday() != 0:  # 0 = Monday
        return
    log.info("=== Starting scheduled bounty generation ===")
    guild = client.guilds[0] if client.guilds else None
    if not guild:
        log.error("scheduled_bounty_generate: no guild available.")
        return
    try:
        success, msg = await _run_generate_bounty(guild)
        if success:
            log.info(f"Scheduled bounty generation complete: {msg}")
        else:
            log.error(f"Scheduled bounty generation failed: {msg}")
    except Exception as e:
        log.error(f"ERROR in scheduled_bounty_generate: {e}\n{traceback.format_exc()}")


@tasks.loop(time=[time(hour=6, minute=0, tzinfo=ZoneInfo("UTC"))])
async def scheduled_bounty_close():
    """Runs every Saturday at 06:00 UTC. Closes the active thread and posts completions if auto mode is enabled."""
    if not bounty_auto_enabled:
        return
    now = datetime.now(ZoneInfo("UTC"))
    if now.weekday() != 5:  # 5 = Saturday
        return
    if not bounty_active_thread_id:
        log.warning("scheduled_bounty_close: no active bounty thread ID recorded, skipping.")
        return
    log.info(f"=== Starting scheduled bounty close (thread {bounty_active_thread_id}) ===")
    guild = client.guilds[0] if client.guilds else None
    if not guild:
        log.error("scheduled_bounty_close: no guild available.")
        return
    try:
        thread = guild.get_channel(bounty_active_thread_id)
        if not thread:
            thread = await guild.fetch_channel(bounty_active_thread_id)
        if not isinstance(thread, discord.Thread):
            log.error(f"scheduled_bounty_close: channel {bounty_active_thread_id} is not a thread.")
            return

        # Gather completions and post to completions channel before locking
        winners = await _check_bounty_completions(thread)

        # Mark bounty closed in DB and record winners
        try:
            bounty_res = supabase.table('bounties').select('id').eq('thread_id', bounty_active_thread_id).limit(1).execute()
            bounty_db_id = bounty_res.data[0]['id'] if bounty_res.data else None
            if bounty_db_id:
                supabase.table('bounties').update({'is_active': False, 'date_end': now.isoformat()}).eq('id', bounty_db_id).execute()
                for w in winners:
                    try:
                        member_res = supabase.table('members').select('id').eq('discord_id', w['user_id']).limit(1).execute()
                        if member_res.data:
                            supabase.table('bounty_winners').upsert(
                                {'bounty_id': bounty_db_id, 'member_id': member_res.data[0]['id']},
                                on_conflict='bounty_id,member_id'
                            ).execute()
                    except Exception as we:
                        log.warning(f"Could not insert bounty_winner for discord_id {w['user_id']}: {we}")
            else:
                log.warning(f"scheduled_bounty_close: no bounties row found for thread_id {bounty_active_thread_id}")
        except Exception as e:
            log.error(f"scheduled_bounty_close: DB update failed: {e}")

        raw_name = thread.name
        for prefix in ("Weekly Bounty – ", "Weekly Bounty - "):
            if raw_name.startswith(prefix):
                raw_name = raw_name[len(prefix):]
                break
        if " (" in raw_name:
            raw_name = raw_name[:raw_name.rfind(" (")]
        item_name = raw_name
        week_label = now.strftime("Week of %b %d, %Y")
        next_bounty_dt = _monday_after(now)
        next_bounty_ts = int(next_bounty_dt.timestamp())
        threads_channel_mention = f"<#{BOUNTY_THREADS_CHANNEL_ID}>"

        completions_channel = guild.get_channel(BOUNTY_COMPLETIONS_CHANNEL_ID)
        if winners:
            winner_lines = "\n".join(f"• <@{w['user_id']}>" for w in winners)
            embed = discord.Embed(
                title=f"Weekly Bounty Completions: {item_name} ({week_label})",
                color=discord.Color.green(),
                timestamp=now,
            )
            embed.description = (
                f"The following members successfully obtained the drop:\n{winner_lines}\n\n"
                f"Congratulations to you all, you've each earned 3 Event Points.\n\n"
                f"A new bounty will be live <t:{next_bounty_ts}:F> (<t:{next_bounty_ts}:R>), keep your eyes on {threads_channel_mention}!"
            )
            embed.set_footer(text=f"Thread ID: {bounty_active_thread_id}")
            if completions_channel:
                await completions_channel.send(embed=embed)
            log.info(f"Scheduled bounty close: posted {len(winners)} completion(s) to completions channel.")
            await _award_bounty_ep(winners, bounty_db_id, guild)
        else:
            log.info("Scheduled bounty close: no confirmed completions found, skipping completions post.")
            staff_channel = guild.get_channel(BOUNTY_STAFF_LOG_CHANNEL_ID)
            if staff_channel:
                await staff_channel.send(
                    f"📋 Weekly bounty closed: **{item_name}** ({week_label}) — no confirmed completions found. "
                    f"Thread: <#{bounty_active_thread_id}>"
                )

        await thread.edit(locked=True, archived=True)
        log.info(f"Scheduled bounty close: thread '{thread.name}' locked and archived.")
    except Exception as e:
        log.error(f"ERROR in scheduled_bounty_close: {e}\n{traceback.format_exc()}")


@scheduled_bounty_generate.before_loop
async def before_scheduled_bounty_generate():
    await client.wait_until_ready()


@scheduled_bounty_close.before_loop
async def before_scheduled_bounty_close():
    await client.wait_until_ready()


@client.tree.command(name="enable-automatic-bounties", description="Enable the automatic weekly bounty generation and close tasks.")
@check_staff_role("Owner")
async def enable_automatic_bounties(interaction: discord.Interaction):
    global bounty_auto_enabled
    bounty_auto_enabled = True
    _save_bot_state('bounty_auto_enabled', 'true')
    now = datetime.now(ZoneInfo("UTC"))
    next_generate_dt = _next_monday_0600_utc(now)
    next_generate_ts = int(next_generate_dt.timestamp())
    await interaction.response.send_message(
        f"✅ Automatic bounties enabled. The next bounty will be posted at <t:{next_generate_ts}:F> (<t:{next_generate_ts}:R>).",
        ephemeral=True,
    )
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    await log_command_use(f"[{timestamp}] /enable-automatic-bounties used by {interaction.user}")


@client.tree.command(name="disable-automatic-bounties", description="Disable the automatic weekly bounty generation and close tasks.")
@check_staff_role("Owner")
async def disable_automatic_bounties(interaction: discord.Interaction):
    global bounty_auto_enabled
    bounty_auto_enabled = False
    _save_bot_state('bounty_auto_enabled', 'false')
    await interaction.response.send_message(
        "🚫 Automatic bounties disabled. Use `/generate-new-bounty-quest` and `/close-bounty-quest` to manage bounties manually.",
        ephemeral=True,
    )
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    await log_command_use(f"[{timestamp}] /disable-automatic-bounties used by {interaction.user}")


# --- 21. RUN THE BOT ---

client.run(DISCORD_TOKEN)