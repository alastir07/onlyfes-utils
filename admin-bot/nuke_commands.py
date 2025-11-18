import os
import discord
from dotenv import load_dotenv

print("--- RUNNING NUKE SCRIPT (v3 - Global & Guild) ---")

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
STAFF_GUILD_ID = os.getenv("STAFF_GUILD_ID")

if not all([DISCORD_TOKEN, STAFF_GUILD_ID]):
    print("Error: Missing DISCORD_BOT_TOKEN or STAFF_GUILD_ID in .env file!")
    exit()

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

guild_obj = discord.Object(id=int(STAFF_GUILD_ID))

@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    
    try:
        # 1. Clear GUILD commands
        print(f"--- Attempting to CLEAR commands from Guild {STAFF_GUILD_ID} ---")
        tree.clear_commands(guild=guild_obj)
        await tree.sync(guild=guild_obj)
        print("--- SUCCESSFULLY CLEARED GUILD COMMANDS ---")
        
        # 2. Clear GLOBAL commands
        print(f"--- Attempting to CLEAR GLOBAL commands ---")
        tree.clear_commands(guild=None) # guild=None means global
        await tree.sync(guild=None)
        print("--- SUCCESSFULLY CLEARED GLOBAL COMMANDS ---")
        
    except Exception as e:
        print(f"--- ERROR during clear: {e} ---")
        
    finally:
        print("--- Logging out. ---")
        await client.close()

try:
    client.run(DISCORD_TOKEN)
except Exception as e:
    print(f"Error logging in: {e}")

print("--- NUKE SCRIPT FINISHED ---")