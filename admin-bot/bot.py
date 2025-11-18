import os
import discord
from discord import app_commands, ui, Interaction
from dotenv import load_dotenv
from supabase import create_client, Client
import asyncio
from io import StringIO
import traceback
from datetime import datetime

# --- Import your logic module ---
import clan_sync_logic

# --- 1. LOAD SECRETS & CONNECT ---
load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not all([DISCORD_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
    print("Error: Missing one or more .env variables!")
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
        print(f"Warning: Could not find member_id for staff {interaction.user}: {e}")
    return None

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
            print(f"--- Attempting to SYNC commands GLOBALLY ---")
            # guild=None means we are syncing all commands globally
            await client.tree.sync(guild=None) 
            print(f"--- Global command sync complete ---")
        except Exception as e:
            print(f"CRITICAL ERROR during global on_ready sync: {e}")
        
        client.synced_on_startup = True 

    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('Bot is ready and online.')

# --- 3. /HELP COMMAND ---
# (This is the correct version with /link-rsn)
@client.tree.command(name="help", description="Shows a list of all available commands.")
@app_commands.describe(publish="True to post the help message publicly.")
async def help(interaction: discord.Interaction, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] /help publish={publish} used by {interaction.user}")
    
    embed = discord.Embed(
        title="IronAssistant Help",
        description="Here is a list of all my available commands.\n`[publish:True]` can be added to any command to make the reply public.",
        color=discord.Color.greyple()
    )
    embed.set_thumbnail(url=client.user.avatar.url if client.user.avatar else None)
    embed.add_field(
        name="User Commands", 
        value="`/help [publish]`\nShows this help message.\n\n" \
              "`/memberinfo <rsn> [publish]`\nGets a member's rank, join date, current EP, and past RSNs.\n\n" \
              "`/rankhistory <rsn> [publish]`\nGets a member's 3 most recent rank changes.",
        inline=False
    )
    embed.add_field(
        name="Staff Commands (Requires Permissions)",
        value="`/sync-clan [dry_run] [force_run] [publish]`\n" \
              "Runs the clan sync with WOM. `publish=True` makes the report public.\n\n" \
              "`/rankup <rsn> <rank_name> [publish]`\n" \
              "Manually promotes/demotes a single member.\n\n" \
              "`/bulkrankup <rank_name> <rsn_list> [publish]`\n" \
              "Updates multiple members to the same rank. RSNs must be comma-separated.\n\n" \
              "`/link-rsn <rsn> <@user> [publish]`\n" \
              "Links an existing member's RSN to their Discord account.\n\n" \
              "--- *Planned Commands* ---\n" \
              "`/add-member <rsn> <@user> [date] [publish]`\n" \
              "`/remove-member <rsn> [publish]`\n" \
              "`/add-points <rsn> <points> <reason> [publish]`\n\n" \
              "--- *DANGER ZONE* ---\n" \
              "`/purge-member <rsn>`\n" \
              "**IRREVERSIBLE.** Deletes a member and all their associated data from the database.",
        inline=False
    )
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
    print(f"[{timestamp}] /memberinfo rsn='{rsn}' publish={publish} used by {interaction.user}")
    
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
        print(f"Error in /memberinfo command: {e}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)
        
                
# --- 5. /RANKHISTORY COMMAND ---
@client.tree.command(name="rankhistory", description="Get a member's 3 most recent rank changes.")
@app_commands.describe(
    rsn="The RSN (current or past) of the member to look up.",
    publish="True to post the history publicly."
)
async def rankhistory(interaction: discord.Interaction, rsn: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] /rankhistory rsn='{rsn}' publish={publish} used by {interaction.user}")
    
    is_ephemeral = not publish
    await interaction.response.defer(ephemeral=is_ephemeral) 

    try:
        response = supabase.rpc('get_rank_history', {'rsn_query': rsn}).execute()
        if not response.data:
            await interaction.followup.send(f"Sorry, I couldn't find anyone with an RSN matching `{rsn}` (or they have no rank history).", ephemeral=True)
            return
        history_list = response.data
        primary_rsn = history_list[0]['primary_rsn']
        embed = discord.Embed(
            title=f"Rank History: {primary_rsn}",
            description="Showing the 3 most recent rank changes.",
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
        print(f"Error in /rankhistory command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)

# --- 6. /SYNC-CLAN COMMAND ---
@app_commands.default_permissions(manage_guild=True) 
@client.tree.command(name="sync-clan", description="Manually run the daily sync with WOM.")
@app_commands.describe(
    dry_run="True (default) to just see the report. False to execute changes.",
    force_run="False (default). True to bypass the rank mismatch safety check.",
    publish="False (default). True to post the final report publicly."
)
async def sync_clan(
    interaction: discord.Interaction, 
    dry_run: bool = True, 
    force_run: bool = False, 
    publish: bool = False
):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] /sync-clan dry_run={dry_run} force_run={force_run} publish={publish} used by {interaction.user}")
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
        print("Sync function complete. Sending report.")
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
        print(f"CRITICAL Error in /sync-clan command:")
        traceback.print_exc() 
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
        print(f"Purge command for {self.rsn} timed out.")
    @ui.button(label="Yes, Purge This Member", style=discord.ButtonStyle.danger, emoji="🔥")
    async def confirm_button(self, interaction: discord.Interaction, button: ui.Button):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] /purge-member CONFIRMED for rsn='{self.rsn}' by {interaction.user}")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        try:
            data = supabase.table('members').delete().eq('id', self.member_id).execute()
            if not data.data:
                await interaction.followup.send(f"Error: Could not find member with ID {self.member_id} to delete.", ephemeral=True)
                return
            print(f"Member {self.rsn} (ID: {self.member_id}) was purged by {self.original_author}.")
            embed = discord.Embed(title="🔥 Purge Complete", description=f"Successfully purged **{self.rsn}** and all their associated data from the database.", color=discord.Color.dark_red())
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            print(f"Error during purge: {e}")
            await interaction.followup.send(f"An error occurred during the purge: `{e}`", ephemeral=True)
    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Purge operation cancelled.", embed=None, view=self)

@app_commands.default_permissions(administrator=True) 
@client.tree.command(name="purge-member", description="DANGER: Permanently deletes a member and all their data.")
@app_commands.describe(rsn="The RSN of the member to purge (must be an exact, case-sensitive match).")
async def purge_member(interaction: discord.Interaction, rsn: str):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] /purge-member rsn='{rsn}' used by {interaction.user}")
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
        print(f"Error in /purge-member command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)

# --- 8. /RANKUP COMMAND ---
@app_commands.default_permissions(manage_guild=True)
@client.tree.command(name="rankup", description="Promote or demote a single member.")
@app_commands.describe(
    rsn="The member's RSN (current or past).",
    rank_name="The new rank to assign (e.g., 'Ruby', 'Beast').",
    publish="True to post the confirmation publicly."
)
async def rankup(interaction: discord.Interaction, rsn: str, rank_name: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] /rankup rsn='{rsn}' rank_name='{rank_name}' publish={publish} used by {interaction.user}")
    
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
        print(f"Error in /rankup command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 9. /BULKRANKUP COMMAND ---
@app_commands.default_permissions(manage_guild=True)
@client.tree.command(name="bulkrankup", description="Promote or demote multiple members to the same rank.")
@app_commands.describe(
    rank_name="The new rank to assign all members (e.g., 'Beast').",
    rsn_list="A comma-separated list of RSNs.",
    publish="True to post the confirmation publicly."
)
async def bulkrankup(interaction: discord.Interaction, rank_name: str, rsn_list: str, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] /bulkrankup rank_name='{rank_name}' rsn_list='{rsn_list}' publish={publish} used by {interaction.user}")
    
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

        print("Building RSN map for bulk rankup...")
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
        print("RSN map built.")

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
            print(f"Updating {len(member_ids_to_update)} members to rank {new_rank_name}...")
            supabase.table('members').update({'current_rank_id': new_rank_id}).in_('id', member_ids_to_update).execute()
            supabase.table('rank_history').insert(history_payload).execute()
            print("Batch update complete.")
        else:
            print("No members valid for update.")

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
        print(f"Error in /bulkrankup command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)

# --- 10. /LINK-RSN COMMAND ---
@app_commands.default_permissions(manage_guild=True)
@client.tree.command(name="link-rsn", description="Links a member's RSN to their Discord account.")
@app_commands.describe(
    rsn="The member's RSN (current or past).",
    user="The @discord user to link.",
    publish="True to post the confirmation publicly."
)
async def link_rsn(interaction: discord.Interaction, rsn: str, user: discord.Member, publish: bool = False):
    
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] /link-rsn rsn='{rsn}' user='{user}' publish={publish} used by {interaction.user}")
    
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
        print(f"Error in /link-rsn command: {e}\n{traceback.format_exc()}")
        await interaction.followup.send(f"An error occurred. Please tell an admin: `{e}`", ephemeral=True)


# --- 11. RUN THE BOT ---
client.run(DISCORD_TOKEN)