import os
import discord
from discord import app_commands, ui, Interaction
from discord.ext import tasks
from dotenv import load_dotenv
from supabase import create_client, Client
import asyncio
from io import StringIO
import traceback
from datetime import datetime, time
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

# --- 1. LOAD SECRETS & CONNECT ---
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SYNC_REPORT_CHANNEL_ID = os.getenv("SYNC_REPORT_CHANNEL_ID")
INACTIVITY_REPORT_CHANNEL_ID = os.getenv("INACTIVITY_REPORT_CHANNEL_ID")
INACTIVITY_REPORT_THREAD_ID = os.getenv("INACTIVITY_REPORT_THREAD_ID")

if not all([DISCORD_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    log.error("Missing one or more .env variables!")
    exit()

# Connect to Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Helper functions ---
def normalize_string(s: str) -> str:
    if not s: return ""
    return s.lower().replace(' ', '').replace('_', '').replace('-', '').replace('.', '')

def get_staff_member_id(interaction: discord.Interaction) -> str | None:
    try:
        user_id_int = interaction.user.id
        response = supabase.table('members').select('id').eq('discord_id', user_id_int).limit(1).execute()
        if response.data:
            return response.data[0]['id']
    except Exception as e:
        log.warning(f"Could not find member_id for staff {interaction.user}: {e}")
    return None

# --- Role-Based Permission System ---
STAFF_ROLES = ["Owner", "Colonel", "General", "Captain"] # Ordered Highest to Lowest

def get_user_role_level(interaction: discord.Interaction) -> str | None:
    """
    Returns the highest staff role the user has, or None if they have no staff role.
    Returns: "Owner", "Colonel", "General", "Captain", or None
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

intents = discord.Intents.default()
intents.message_content = True 

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

        log.info("Scheduled tasks started: ep_leaderboard (hourly), clan_sync (00:00, 12:00 UTC), inactivity_check (14:00 UTC)")
    log.info(f'Logged in as {client.user} (ID: {client.user.id})')
    log.info('Bot is ready and online.')

# --- 3. /HELP COMMAND ---
@client.tree.command(name="help", description="Shows a list of all available commands.")
@app_commands.describe(publish="True to post the help message publicly.")
async def help(interaction: discord.Interaction, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /help publish={publish} used by {interaction.user}")
    
    # Determine user's role level
    user_role = get_user_role_level(interaction)
    
    embed = discord.Embed(
        title="IronAssistant Help",
        description="Here are the commands you can use.\n`[publish:True]` can be added to any command to make the reply public.",
        color=discord.Color.greyple()
    )
    embed.set_thumbnail(url=client.user.avatar.url if client.user.avatar else None)
    
    # All users can see these commands
    user_commands = [
        "`/help [publish]`\nShows this help message.",
        "`/memberinfo <rsn> [publish]`\nGets a member's rank, join date, current EP, and past RSNs.",
        "`/rankhistory <rsn> [num_changes] [publish]`\nGets a member's recent rank changes."
    ]
    
    embed.add_field(
        name="📋 User Commands",
        value="\n\n".join(user_commands),
        inline=False
    )
    
    # Captain commands (and higher)
    if user_role in ["Captain", "General", "Colonel", "Owner"]:
        captain_commands = [
            "`/rankup <rsn> <rank_name> [publish]`\nManually promotes/demotes a single member.",
            "`/bulkrankup <rank_name> <rsn_list> [publish]`\nUpdates multiple members to the same rank.",
            "`/linkrsn <rsn> <@user> [publish]`\nLinks a member's RSN to their Discord account.",
            "`/addpoints <rsn> <points> <reason> [publish]`\nAdds Event Points for a member.",
            "`/removepoints <rsn> <points> <reason> [publish]`\nRemoves Event Points from a member.",
            "`/bulkaddpoints <points> <reason> <rsn_list> [publish]`\nAdds Event Points to multiple members at once.",
            "`/addpointsbotm <first> <second> <third> <participants> [publish]`\nAdds points for Boss of the Month.",
            "`/addpointssotm <first> <second> <third> <participants> [publish]`\nAdds points for Skill of the Month.",
            "`/addpointsbigbooty <first> <second> <third> <participants> [publish]`\nAdds points for Big Booty (Clue of the Month)."
        ]
        
        embed.add_field(
            name="👮 Captain Commands",
            value="\n\n".join(captain_commands),
            inline=False
        )
    
    # General commands (and higher)
    if user_role in ["General", "Colonel", "Owner"]:
        general_commands = [
            "`/syncclan [dry_run] [force_run] [publish]`\nRuns the clan sync with WOM.",
            "`/addexempt <rsn> <reason> [publish]`\nGrants a member 3-month immunity from inactivity tracking.",
            "`/checkinactives [publish]`\nChecks for members with 0 XP gain in their check period."
        ]
        
        embed.add_field(
            name="⭐ General Commands",
            value="\n\n".join(general_commands),
            inline=False
        )
    
    # Colonel commands (and higher)
    if user_role in ["Colonel", "Owner"]:
        colonel_commands = [
            "`/purgemember <rsn>`\n**⚠️ IRREVERSIBLE.** Deletes a member and all their associated data from the database."
        ]
        
        embed.add_field(
            name="🔥 Colonel Commands (DANGER ZONE)",
            value="\n\n".join(colonel_commands),
            inline=False
        )
    
    # Add footer showing user's role level
    if user_role:
        embed.set_footer(text=f"Your role: {user_role} • You can use all commands at your level and below.")
    else:
        embed.set_footer(text="Your role: Member • You can use all User Commands.")
    
    is_ephemeral = not publish
    await interaction.response.send_message(embed=embed, ephemeral=is_ephemeral)

# --- 4. /MEMBERINFO COMMAND (UPDATED) ---
@client.tree.command(name="memberinfo", description="Get info for a clan member (shows primary RSN).")
@app_commands.describe(
    rsn="The RSN (current or past) of the member to look up.",
    publish="True to post the member info publicly."
)
async def member_info(interaction: discord.Interaction, rsn: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /memberinfo rsn='{rsn}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral) 

    try:
        response = supabase.rpc('get_member_info', {'rsn_query': rsn}).execute()
        
        if not response.data:
            await interaction.followup.send(f"Sorry, I couldn't find anyone with an RSN matching `{rsn}`.", ephemeral=True)
            return

        member = response.data[0]
        
        join_date_obj = discord.utils.parse_time(member['date_joined'])
        formatted_date = f"<t:{int(join_date_obj.timestamp())}:D>"

        embed = discord.Embed(
            title=f"Member Info: {member['primary_rsn']}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Current Rank", value=member['rank_name'], inline=True)
        embed.add_field(name="Current EP", value=f"{member['total_ep']:,}", inline=True)
        embed.add_field(name="Join Date", value=formatted_date, inline=True)
        
        # --- NEW: Add Discord ID (plaintext) ---
        discord_id = member.get('discord_id')
        if discord_id:
            # Use backticks to format it as code and prevent pings
            embed.add_field(name="Linked Discord ID", value=f"`{discord_id}`", inline=False)
        # --- END NEW ---

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
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral) 

    try:
        response = supabase.rpc('get_rank_history', {'rsn_query': rsn, 'limit_count': num_changes}).execute()
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
    is_ephemeral = not publish 
    await interaction.response.defer(ephemeral=is_ephemeral)
    if force_run and dry_run:
        await interaction.followup.send("Error: Cannot use `force_run=True` with `dry_run=True`. No action taken.", ephemeral=True)
        return
    try:
        report_string = await asyncio.to_thread(
            clan_sync_logic.run_sync, 
            supabase, 
            dry_run=dry_run, 
            force_run=force_run
        )
        log.info("Sync function complete. Sending report.")
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
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        try:
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
@check_staff_role("Colonel")
async def purge_member(interaction: discord.Interaction, rsn: str):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /purgemember rsn='{rsn}' used by {interaction.user}")
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
    publish="True to post the confirmation publicly."
)
@check_staff_role("Captain")
async def rankup(interaction: discord.Interaction, rsn: str, rank_name: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /rankup rsn='{rsn}' rank_name='{rank_name}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)

    try:
        staff_member_id = get_staff_member_id(interaction)
        
        normalized_rank_name = normalize_string(rank_name)
        rank_res = supabase.table('ranks').select('id, name').ilike('name', normalized_rank_name).limit(1).execute()
        
        if not rank_res.data:
            await interaction.followup.send(f"Error: The rank `{rank_name}` does not exist in the database.", ephemeral=True)
            return
        
        new_rank = rank_res.data[0]
        new_rank_id = new_rank['id']
        new_rank_name = new_rank['name'] 

        member_res = supabase.table('member_rsns') \
            .select('member_id, rsn, members(current_rank_id)') \
            .ilike('rsn', rsn) \
            .limit(1) \
            .execute()

        if not member_res.data:
            await interaction.followup.send(f"Error: RSN `{rsn}` not found in the database.", ephemeral=True)
            return

        member_id = member_res.data[0]['member_id']
        member_rsn = member_res.data[0]['rsn']
        old_rank_id = member_res.data[0]['members']['current_rank_id']

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
        
        await interaction.followup.send(f"✅ Success! `{member_rsn}`'s rank has been updated to **{new_rank_name}**.", ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in /rankup command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 9. /BULKRANKUP COMMAND ---
@client.tree.command(name="bulkrankup", description="Promote or demote multiple members to the same rank.")
@app_commands.describe(
    rank_name="The new rank to assign all members (e.g., 'Beast').",
    rsn_list="A comma-separated list of RSNs.",
    publish="True to post the confirmation publicly."
)
@check_staff_role("Captain")
async def bulkrankup(interaction: discord.Interaction, rank_name: str, rsn_list: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /bulkrankup rank_name='{rank_name}' rsn_list='{rsn_list}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        staff_member_id = get_staff_member_id(interaction)

        normalized_rank_name = normalize_string(rank_name)
        rank_res = supabase.table('ranks').select('id, name').ilike('name', normalized_rank_name).limit(1).execute()
        
        if not rank_res.data:
            await interaction.followup.send(f"Error: The rank `{rank_name}` does not exist in the database.", ephemeral=True)
            return
        
        new_rank = rank_res.data[0]
        new_rank_id = new_rank['id']
        new_rank_name = new_rank['name']

        log.info("Building RSN map for bulk rankup...")
        rsns_res = supabase.table('member_rsns') \
            .select('rsn, member_id, members(current_rank_id)') \
            .execute()
        
        rsn_map = {}
        for item in rsns_res.data:
            if item.get('members'):
                rsn_map[normalize_string(item['rsn'])] = {
                    "member_id": item['member_id'],
                    "original_rsn": item['rsn'],
                    "old_rank_id": item['members']['current_rank_id']
                }
        log.info("RSN map built.")

        rsns_to_process = [r.strip() for r in rsn_list.split(',')]
        
        member_ids_to_update = []
        history_payload = []
        report_success = []
        report_fail_not_found = []
        report_fail_already_rank = []

        for rsn in rsns_to_process:
            if not rsn: continue
            
            normalized_rsn = normalize_string(rsn)
            member_data = rsn_map.get(normalized_rsn)

            if not member_data:
                report_fail_not_found.append(rsn)
                continue
            
            if member_data['old_rank_id'] == new_rank_id:
                report_fail_already_rank.append(member_data['original_rsn'])
                continue
                
            member_ids_to_update.append(member_data['member_id'])
            history_payload.append({
                'member_id': member_data['member_id'], 
                'previous_rank_id': member_data['old_rank_id'], 
                'new_rank_id': new_rank_id,
                'enacted_by_member_id': staff_member_id
            })
            report_success.append(member_data['original_rsn'])

        if member_ids_to_update:
            log.info(f"Updating {len(member_ids_to_update)} members to rank {new_rank_name}...")
            supabase.table('members').update({'current_rank_id': new_rank_id}).in_('id', member_ids_to_update).execute()
            supabase.table('rank_history').insert(history_payload).execute()
            log.info("Batch update complete.")
        else:
            log.info("No members valid for update.")

        embed = discord.Embed(
            title=f"Bulk Rank Update to '{new_rank_name}' Complete",
            color=discord.Color.green() if not report_fail_not_found else discord.Color.orange()
        )
        
        if report_success:
            embed.add_field(name=f"✅ Success ({len(report_success)})", value="```\n" + "\n".join(report_success) + "\n```", inline=False)
        if report_fail_already_rank:
            embed.add_field(name=f"ℹ️ No Change ({len(report_fail_already_rank)})", value="```\n" + "\n".join(report_fail_already_rank) + "\n```", inline=False)
        if report_fail_not_found:
            embed.add_field(name=f"❌ Failed: RSN Not Found ({len(report_fail_not_found)})", value="```\n" + "\n".join(report_fail_not_found) + "\n```", inline=False)
        
        if not report_success and not report_fail_already_rank and not report_fail_not_found:
            embed.description = "No RSNs were provided or found."

        await interaction.followup.send(embed=embed, ephemeral=is_ephemeral)

    except Exception as e:
        log.error(f"Error in /bulkrankup command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)

# --- 10. /LINK-RSN COMMAND ---
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
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        # 1. Find the member by RSN
        member_res = supabase.table('member_rsns') \
            .select('member_id, rsn, members(discord_id)') \
            .ilike('rsn', rsn) \
            .limit(1) \
            .execute()

        if not member_res.data:
            await interaction.followup.send(f"Error: RSN `{rsn}` not found in the database.", ephemeral=True)
            return

        member_id = member_res.data[0]['member_id']
        member_rsn = member_res.data[0]['rsn']
        
        # 2. Check if they are already linked
        if member_res.data[0].get('members') and member_res.data[0]['members'].get('discord_id'):
            old_discord_id = member_res.data[0]['members']['discord_id']
            if old_discord_id == user.id:
                await interaction.followup.send(f"ℹ️ No change: `{member_rsn}` is already linked to {user.mention}.", ephemeral=True)
                return
            else:
                await interaction.followup.send(f"Warning: `{member_rsn}` is already linked to a different user (<@{old_discord_id}>). Please /unlink them first.", ephemeral=True)
                return
        
        # 3. Execute the update
        supabase.table('members').update({'discord_id': user.id}).eq('id', member_id).execute()
        
        await interaction.followup.send(f"✅ Success! `{member_rsn}` is now linked to {user.mention}.", ephemeral=is_ephemeral)

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
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    if points < 0:
        await interaction.followup.send(f"⛔ Please use `/remove-points` to subtract points.", ephemeral=True)
        return

    try:
        # 1. Find the member
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
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    if points < 0:
        await interaction.followup.send(f"⛔ Please enter a positive number (e.g., 10) to remove points.", ephemeral=True)
        return

    try:
        # 1. Find the member
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
@client.tree.command(name="addexempt", description="Grant a member 3-month immunity from inactivity tracking.")
@app_commands.describe(
    rsn="The member's RSN (current or past).",
    reason="The reason for this exemption (e.g., 'Taking a break from the game').",
    publish="True to post the confirmation publicly."
)
@check_staff_role("General")
async def add_exempt(interaction: discord.Interaction, rsn: str, reason: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /addexempt rsn='{rsn}' reason='{reason}' publish={publish} used by {interaction.user}")
    
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
        
        # 4. Calculate expiration date (3 months from now)
        from dateutil.relativedelta import relativedelta
        expiration_date = datetime.now() + relativedelta(months=3)
        
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
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)

    # 1. Collect all RSNs to resolve
    # We map normalized_rsn -> {'rank': '1st'/'2nd'/'3rd'/'participation', 'original': 'RsN'}
    # Note: If a user is in multiple slots (unlikely but possible), we'll just take the highest value or process sequentially.
    # For simplicity, we'll process them as a list of transactions.
    
    targets = []
    if first: targets.append({'rsn': first.strip(), 'points': points_map['1st'], 'rank': '1st Place'})
    if second: targets.append({'rsn': second.strip(), 'points': points_map['2nd'], 'rank': '2nd Place'})
    if third: targets.append({'rsn': third.strip(), 'points': points_map['3rd'], 'rank': '3rd Place'})
    
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
    first="RSN of 1st place (12 pts)",
    second="RSN of 2nd place (7 pts)",
    third="RSN of 3rd place (5 pts)",
    participants="Comma-separated list of other participants (3 pts each)",
    publish="True to post publicly"
)
@check_staff_role("Captain")
async def add_points_botm(interaction: discord.Interaction, first: str, second: str, third: str, participants: str, publish: bool = False):
    points = {'1st': 12, '2nd': 7, '3rd': 5, 'participation': 3}
    await process_competition_points(interaction, first, second, third, participants, points, "boss of the month", publish)


@client.tree.command(name="addpointssotm", description="Add points for Skill of the Month.")
@app_commands.describe(
    first="RSN of 1st place (12 pts)",
    second="RSN of 2nd place (7 pts)",
    third="RSN of 3rd place (5 pts)",
    participants="Comma-separated list of other participants (3 pts each)",
    publish="True to post publicly"
)
@check_staff_role("Captain")
async def add_points_sotm(interaction: discord.Interaction, first: str, second: str, third: str, participants: str, publish: bool = False):
    points = {'1st': 12, '2nd': 7, '3rd': 5, 'participation': 3}
    await process_competition_points(interaction, first, second, third, participants, points, "skill of the month", publish)


@client.tree.command(name="addpointsbigbooty", description="Add points for Big Booty (Clue of the Month).")
@app_commands.describe(
    first="RSN of 1st place (20 pts)",
    second="RSN of 2nd place (15 pts)",
    third="RSN of 3rd place (10 pts)",
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


# --- 17. EP LEADERBOARD HELPER FUNCTIONS ---
def get_ep_leaderboard_message_ids():
    """Retrieve stored EP leaderboard message IDs from database"""
    try:
        response = supabase.table('bot_config').select('value').eq('key', 'ep_leaderboard_message_ids').limit(1).execute()
        if response.data and response.data[0]['value']:
            import json
            return json.loads(response.data[0]['value'])
        return []
    except Exception as e:
        log.error(f"Error retrieving EP leaderboard message IDs: {e}")
        return []
def save_ep_leaderboard_message_ids(message_ids):
    """Save EP leaderboard message IDs to database"""
    try:
        import json
        value = json.dumps(message_ids)
        # Upsert the value
        supabase.table('bot_config').upsert({
            'key': 'ep_leaderboard_message_ids',
            'value': value
        }).execute()
        log.info(f"Saved {len(message_ids)} EP leaderboard message IDs to database")
    except Exception as e:
        log.error(f"Error saving EP leaderboard message IDs: {e}")

# --- 17. /UPDATE-EP-LEADERBOARD COMMAND ---
@client.tree.command(name="updateepleaderboard", description="Manually update the EP leaderboard.")
@app_commands.describe(
    publish="False (default). True to post the confirmation publicly."
)
@check_staff_role("Colonel")
async def update_ep_leaderboard_command(interaction: discord.Interaction, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log.info(f"[{timestamp}] /updateepleaderboard publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral)
    
    try:
        # Get the sync report channel
        if not SYNC_REPORT_CHANNEL_ID:
            await interaction.followup.send("Error: SYNC_REPORT_CHANNEL_ID not configured.", ephemeral=True)
            return
        
        channel = client.get_channel(int(SYNC_REPORT_CHANNEL_ID))
        if not channel:
            await interaction.followup.send(f"Error: Could not find channel with ID {SYNC_REPORT_CHANNEL_ID}", ephemeral=True)
            return
        
        # Fetch active members with non-zero EP
        log.info("Fetching members with event points...")
        response = supabase.table('members') \
            .select('id, total_ep, member_rsns!inner(rsn, is_primary)') \
            .eq('status', 'Active') \
            .gt('total_ep', 0) \
            .eq('member_rsns.is_primary', True) \
            .order('total_ep', desc=True) \
            .execute()
        
        members = response.data
        
        if not members:
            await interaction.followup.send("No members with event points found.", ephemeral=is_ephemeral)
            return
        
        # Pagination
        members_per_page = 50
        total_pages = (len(members) + members_per_page - 1) // members_per_page
        
        # Get stored message IDs
        stored_message_ids = get_ep_leaderboard_message_ids()
        stored_messages_map = {msg['page']: msg['message_id'] for msg in stored_message_ids}
        
        # Build and send/edit messages
        new_message_ids = []
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
        
        for page in range(1, total_pages + 1):
            start_idx = (page - 1) * members_per_page
            end_idx = min(start_idx + members_per_page, len(members))
            page_members = members[start_idx:end_idx]
            
            # Build message content
            lines = [
                f"📊 **Current EP Leaderboard** (Page {page}/{total_pages})",
                f"Last Updated: {current_time}",
                "",
                "```",
                "RSN - Event Points",
                "─" * 40
            ]
            
            for member in page_members:
                rsn = member['member_rsns'][0]['rsn']
                ep = member['total_ep']
                lines.append(f"{rsn} - {ep:,}")
            
            lines.append("```")
            message_content = "\n".join(lines)
            
            # Send or edit message
            if page in stored_messages_map:
                try:
                    message = await channel.fetch_message(int(stored_messages_map[page]))
                    await message.edit(content=message_content)
                    new_message_ids.append({'page': page, 'message_id': stored_messages_map[page]})
                except discord.NotFound:
                    new_msg = await channel.send(message_content)
                    new_message_ids.append({'page': page, 'message_id': str(new_msg.id)})
            else:
                new_msg = await channel.send(message_content)
                new_message_ids.append({'page': page, 'message_id': str(new_msg.id)})
        
        # Delete extra messages
        for page in stored_messages_map:
            if page > total_pages:
                try:
                    message = await channel.fetch_message(int(stored_messages_map[page]))
                    await message.delete()
                except:
                    pass
        
        # Save updated message IDs
        save_ep_leaderboard_message_ids(new_message_ids)
        
        await interaction.followup.send(
            f"✅ EP leaderboard updated successfully! ({len(members)} members across {total_pages} page(s))",
            ephemeral=is_ephemeral
        )
        
    except Exception as e:
        log.error(f"Error in /updateepleaderboard command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)

# --- 18. SCHEDULED TASKS ---
@tasks.loop(hours=1)
async def scheduled_ep_leaderboard():
    """Runs EP leaderboard update hourly"""
    log.info("=== Starting scheduled EP leaderboard update ===")
    
    try:
        # Get the sync report channel (using for testing)
        if not SYNC_REPORT_CHANNEL_ID:
            log.error("SYNC_REPORT_CHANNEL_ID not configured. Skipping EP leaderboard update.")
            return
        
        channel = client.get_channel(int(SYNC_REPORT_CHANNEL_ID))
        if not channel:
            log.error(f"Could not find channel with ID {SYNC_REPORT_CHANNEL_ID}")
            return
        
        # Fetch active members with non-zero EP, ordered by EP descending
        log.info("Fetching members with event points...")
        response = supabase.table('members') \
            .select('id, total_ep, member_rsns!inner(rsn, is_primary)') \
            .eq('status', 'Active') \
            .gt('total_ep', 0) \
            .eq('member_rsns.is_primary', True) \
            .order('total_ep', desc=True) \
            .execute()
        
        members = response.data
        log.info(f"Found {len(members)} members with event points")
        
        if not members:
            log.info("No members with event points found. Skipping leaderboard update.")
            return
        
        # Pagination: 50 members per message
        members_per_page = 50
        total_pages = (len(members) + members_per_page - 1) // members_per_page
        
        # Get stored message IDs
        stored_message_ids = get_ep_leaderboard_message_ids()
        stored_messages_map = {msg['page']: msg['message_id'] for msg in stored_message_ids}
        
        # Build and send/edit messages
        new_message_ids = []
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
        
        for page in range(1, total_pages + 1):
            start_idx = (page - 1) * members_per_page
            end_idx = min(start_idx + members_per_page, len(members))
            page_members = members[start_idx:end_idx]
            
            # Build message content
            lines = [
                f"📊 **Current EP Leaderboard** (Page {page}/{total_pages})",
                f"Last Updated: {current_time}",
                "",
                "```",
                "RSN - Event Points",
                "─" * 40
            ]
            
            for member in page_members:
                rsn = member['member_rsns'][0]['rsn']  # Get the primary RSN
                ep = member['total_ep']
                lines.append(f"{rsn} - {ep:,}")
            
            lines.append("```")
            message_content = "\\n".join(lines)
            
            # Send or edit message
            try:
                if page in stored_messages_map:
                    # Try to edit existing message
                    message_id = stored_messages_map[page]
                    try:
                        message = await channel.fetch_message(int(message_id))
                        await message.edit(content=message_content)
                        new_message_ids.append({'page': page, 'message_id': message_id})
                        log.info(f"Updated leaderboard page {page}")
                    except discord.NotFound:
                        # Message was deleted, create a new one
                        log.warning(f"Message for page {page} not found, creating new message")
                        new_msg = await channel.send(message_content)
                        new_message_ids.append({'page': page, 'message_id': str(new_msg.id)})
                        log.info(f"Created new leaderboard page {page}")
                else:
                    # Create new message
                    new_msg = await channel.send(message_content)
                    new_message_ids.append({'page': page, 'message_id': str(new_msg.id)})
                    log.info(f"Created new leaderboard page {page}")
            except Exception as e:
                log.error(f"Error updating/creating page {page}: {e}")
        
        # Delete extra messages if member count decreased
        for page in stored_messages_map:
            if page > total_pages:
                try:
                    message_id = stored_messages_map[page]
                    message = await channel.fetch_message(int(message_id))
                    await message.delete()
                    log.info(f"Deleted extra leaderboard page {page}")
                except Exception as e:
                    log.warning(f"Could not delete extra page {page}: {e}")
        
        # Save updated message IDs
        save_ep_leaderboard_message_ids(new_message_ids)
        log.info("EP leaderboard update complete")
        
    except Exception as e:
        log.error(f"ERROR in scheduled_ep_leaderboard: {e}\\n{traceback.format_exc()}")
        # Try to post error to channel
        try:
            if SYNC_REPORT_CHANNEL_ID:
                channel = client.get_channel(int(SYNC_REPORT_CHANNEL_ID))
                if channel:
                    await channel.send(f"⚠️ **Automated EP Leaderboard Update Failed**\\nError: `{e}`\\nCheck bot logs for details.")
        except:
            pass  # If we can't post the error, just log it


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
        report_string = await asyncio.to_thread(
            clan_sync_logic.run_sync,
            supabase,
            dry_run=False,
            force_run=False
        )
        
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


# --- 19. RUN THE BOT ---

client.run(DISCORD_TOKEN)