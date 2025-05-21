import discord
from discord.ext import commands
import aiosqlite
import asyncio
import datetime
from discord import app_commands
import traceback
import requests
from typing import Callable, Any, Coroutine
import random

# Webhook URL for logging
#read webhook from a file called webhook with no extention
with open("webhook", "r") as webhook_file:
    WEBHOOK_URL = webhook_file.read().strip()

THUMBNAIL_URL = "https://cdn.discordapp.com/icons/1268882588345565264/fc3caa6e5ad9997c1cace451f9d76029.webp?size=80&quality=lossless"

URLS = [
    "https://github.com/DogeSkii/RPBot",
    "https://discord.gg/62x6Hxaged"
]

# Function to send logs to the webhook
def log_to_webhook(message: str):
    try:
        requests.post(WEBHOOK_URL, json={"content": message})
    except Exception as e:
        print(f"Failed to send log to webhook: {e}")

# Log function calls
def log_function_call(func_name: str, *args, **kwargs):
    log_to_webhook(f"Function `{func_name}` called with args: {args}, kwargs: {kwargs}")

# Use all intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="(0000)", intents=intents)

DATABASE = "rp_database.db"
db = None

start_time = datetime.datetime.utcnow()

WHITELISTED_USERS = {1118843189323898910,1037103122251780207}  # Replace with actual Discord user IDs


async def initialize_database():
    global db
    db = await aiosqlite.connect(DATABASE)
    
    # Create the table with server_id and user_id as composite primary key
    await db.execute("""
        CREATE TABLE IF NOT EXISTS rp_data (
            server_id TEXT,
            user_id TEXT,
            weekly_rp INTEGER DEFAULT 0,
            historical_rp INTEGER DEFAULT 0,
            PRIMARY KEY (server_id, user_id)
        )
    """)
    await db.commit()

async def send_final_leaderboard():
    channel_id = 123456789012345678  # Replace with your channel ID
    channel = bot.get_channel(channel_id)
    
    if channel is None:
        print(f"Channel with ID {channel_id} not found.")
        return

    async with db.execute("SELECT user_id, weekly_rp FROM rp_data WHERE weekly_rp > 0 ORDER BY weekly_rp DESC LIMIT 10") as cursor:
        rows = await cursor.fetchall()
    
    if not rows:
        description = "No RP records found."
    else:
        description = ""
        for position, (user_id, rp_amount) in enumerate(rows, start=1):
            member = bot.get_user(int(user_id))
            name = member.name if member else f"User {user_id}"
            description += f"**{position}. {name}** — **{rp_amount} RP**\n"
    
    embed = create_embed(
        title="Final Weekly RP Leaderboard - LUNATIC FTW",
        description=description,
        color=discord.Color.purple()
    )
    await channel.send(embed=embed)




async def weekly_reset():
    # Move weekly RP to historical RP and reset weekly_rp for all users.
    await send_final_leaderboard()
    await db.execute("""
        UPDATE rp_data
        SET historical_rp = historical_rp + weekly_rp,
            weekly_rp = 0
    """)
    await db.commit()
    print("Weekly RP reset completed.")

def seconds_until_next_monday_midnight_utc() -> float:
    now = datetime.datetime.utcnow()
    # Target is next Monday at 00:00 UTC.
    # Python's weekday(): Monday is 0, Sunday is 6.
    days_until_monday = (7 - now.weekday()) % 7
    # If today is Monday and we're already past midnight, schedule for next Monday.
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=days_until_monday)
    return (next_monday - now).total_seconds()

async def weekly_reset_task():
    await bot.wait_until_ready()  # Ensure the bot is fully ready.
    while not bot.is_closed():
        sleep_duration = seconds_until_next_monday_midnight_utc()
        print(f"Next weekly reset in {sleep_duration:.0f} seconds.")
        await asyncio.sleep(sleep_duration)
        await weekly_reset()

@bot.event
async def on_ready():
    await initialize_database()
    log_to_webhook(f"Bot is ready. Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    # Start the weekly reset background task.
    bot.loop.create_task(weekly_reset_task())

def get_random_url():
    return random.choice(URLS)

# Modify embed creation to include random URL in title
def create_embed(title: str, description: str, color: discord.Color) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        url=get_random_url()
    )
    embed.set_thumbnail(url=THUMBNAIL_URL)
    return embed

@bot.tree.command(name="rp", description="Add RP to your account.")
async def rp(interaction: discord.Interaction, amount: int):
    log_function_call("rp", interaction=interaction, amount=amount)
    user_id = str(interaction.user.id)
    server_id = str(interaction.guild.id)
    
    async with db.execute(
        "SELECT weekly_rp FROM rp_data WHERE server_id = ? AND user_id = ?",
        (server_id, user_id)
    ) as cursor:
        row = await cursor.fetchone()
    
    if row is None:
        await db.execute(
            "INSERT INTO rp_data (server_id, user_id, weekly_rp) VALUES (?, ?, ?)",
            (server_id, user_id, amount)
        )
        new_total = amount
    else:
        new_total = row[0] + amount
        await db.execute(
            "UPDATE rp_data SET weekly_rp = ? WHERE server_id = ? AND user_id = ?",
            (new_total, server_id, user_id)
        )
    await db.commit()
    
    embed = create_embed(
        title="RP Added - LUNATIC FTW",
        description=f"Added **{amount} RP** to your account.\nYour weekly total is now **{new_total} RP**.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="revoke-rp", description="Revoke RP from your account.")
async def revoke_rp(interaction: discord.Interaction, amount: int):
    log_function_call("revoke_rp", interaction=interaction, amount=amount)
    user_id = str(interaction.user.id)
    server_id = str(interaction.guild.id)
    
    async with db.execute(
        "SELECT weekly_rp FROM rp_data WHERE server_id = ? AND user_id = ?",
        (server_id, user_id)
    ) as cursor:
        row = await cursor.fetchone()
    
    if row is None:
        embed = create_embed(
            title="No RP Found - LUNATIC FTW",
            description="You don't have any RP to revoke.",
            color=discord.Color.red()
        )
        return await interaction.response.send_message(embed=embed)
    
    new_total = max(row[0] - amount, 0)
    await db.execute(
        "UPDATE rp_data SET weekly_rp = ? WHERE server_id = ? AND user_id = ?",
        (new_total, server_id, user_id)
    )
    await db.commit()
    
    embed = create_embed(
        title="RP Revoked - LUNATIC FTW",
        description=f"Revoked **{amount} RP** from your account.\nYour weekly total is now **{new_total} RP**.",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="Show the weekly RP leaderboard.")
async def leaderboard(interaction: discord.Interaction):
    log_function_call("leaderboard", interaction=interaction)
    server_id = str(interaction.guild.id)
    # Exclude users with 0 weekly RP.
    async with db.execute(
        "SELECT user_id, weekly_rp FROM rp_data WHERE server_id = ? AND weekly_rp > 0 ORDER BY weekly_rp DESC LIMIT 10",
        (server_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    
    if not rows:
        embed = create_embed(
            title="Leaderboard - LUNATIC FTW",
            description="No RP records found.",
            color=discord.Color.blue()
        )
        return await interaction.response.send_message(embed=embed)
    
    description = ""
    for position, (user_id, rp_amount) in enumerate(rows, start=1):
        member = bot.get_user(int(user_id))
        name = member.name if member else f"User {user_id}"
        description += f"**{position}. {name}** — **{rp_amount} RP**\n"
    
    embed = create_embed(
        title="Weekly RP Leaderboard - LUNATIC FTW",
        description=description,
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="historical-leaderboard", description="Show the historical RP leaderboard.")
async def leaderboard(interaction: discord.Interaction):
    log_function_call("historical_leaderboard", interaction=interaction)
    server_id = str(interaction.guild.id)
    # Exclude users with 0 weekly RP.
    async with db.execute(
        "SELECT user_id, historical_rp FROM rp_data WHERE server_id = ? AND historical_rp > 0 ORDER BY historical_rp DESC LIMIT 10",
        (server_id,)
    ) as cursor:
        rows = await cursor.fetchall()
    
    if not rows:
        embed = create_embed(
            title="Historical Leaderboard - LUNATIC FTW",
            description="No RP records found.",
            color=discord.Color.blue()
        )
        return await interaction.response.send_message(embed=embed)
    
    description = ""
    for position, (user_id, rp_amount) in enumerate(rows, start=1):
        member = bot.get_user(int(user_id))
        name = member.name if member else f"User {user_id}"
        description += f"**{position}. {name}** — **{rp_amount} RP**\n"
    
    embed = create_embed(
        title="Historical RP Leaderboard - LUNATIC FTW",
        description=description,
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="historical-rp", description="Show your historical RP total.")
async def historical_rp(interaction: discord.Interaction):
    log_function_call("historical_rp", interaction=interaction)
    user_id = str(interaction.user.id)
    server_id = str(interaction.guild.id)
    async with db.execute(
        "SELECT historical_rp, weekly_rp FROM rp_data WHERE server_id = ? AND user_id = ?",
        (server_id, user_id)
    ) as cursor:
        row = await cursor.fetchone()
    
    if row is None:
        historical, weekly = 0, 0
    else:
        historical, weekly = row[0], row[1]
    
    embed = create_embed(
        title="Your RP Totals - LUNATIC FTW",
        description=(
            f"**Historical RP:** {historical} RP\n"
            f"**Current Weekly RP:** {weekly} RP"
        ),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="simulate-weekly-wipe", description="Manually trigger the weekly RP reset. (Whitelisted users only)")
async def simulate_weekly_wipe(interaction: discord.Interaction):
    log_function_call("simulate_weekly_wipe", interaction=interaction)
    if interaction.user.id not in WHITELISTED_USERS:
        embed = create_embed(
            title="Access Denied - LUNATIC FTW",
            description="You are not authorized to perform this action.",
            color=discord.Color.red()
        )
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    async with db.execute("UPDATE rp_data SET historical_rp = historical_rp + weekly_rp, weekly_rp = 0") as cursor:
        await db.commit()

    embed = create_embed(
        title="Weekly RP Reset Completed - LUNATIC FTW",
        description="All weekly RP has been moved to historical RP, and the leaderboard has been reset.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="revoke-historical-rp", description="Revoke RP from your historical total.")
async def revoke_historical_rp(interaction: discord.Interaction, amount: int):
    log_function_call("revoke_historical_rp", interaction=interaction, amount=amount)
    user_id = str(interaction.user.id)
    server_id = str(interaction.guild.id)
    async with db.execute(
        "SELECT historical_rp FROM rp_data WHERE server_id = ? AND user_id = ?",
        (server_id, user_id)
    ) as cursor:
        row = await cursor.fetchone()
    
    if row is None:
        embed = create_embed(
            title="No Historical RP Found - LUNATIC FTW",
            description="You don't have any historical RP to revoke.",
            color=discord.Color.red()
        )
        return await interaction.response.send_message(embed=embed)
    
    new_total = max(row[0] - amount, 0)
    await db.execute(
        "UPDATE rp_data SET historical_rp = ? WHERE server_id = ? AND user_id = ?",
        (new_total, server_id, user_id)
    )
    await db.commit()
    
    embed = create_embed(
        title="Historical RP Revoked - LUNATIC FTW",
        description=f"Revoked **{amount} RP** from your historical RP total.\nYour new total is **{new_total} RP**.",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="time-to-next-reset", description="Shows the time remaining until the next weekly RP reset.")
async def time_to_next_reset(interaction: discord.Interaction):
    log_function_call("time_to_next_reset", interaction=interaction)
    seconds_remaining = seconds_until_next_monday_midnight_utc()
    time_remaining = datetime.timedelta(seconds=int(seconds_remaining))

    embed = create_embed(
        title="Time Until Next Weekly Reset - LUNATIC FTW",
        description=f"The next RP reset will occur in **{time_remaining}**.",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="uptime", description="Shows how long the bot has been running.")
async def uptime(interaction: discord.Interaction):
    log_function_call("uptime", interaction=interaction)
    uptime_duration = datetime.datetime.utcnow() - start_time

    embed = create_embed(
        title="Bot Uptime - LUNATIC FTW",
        description=f"The bot has been running for **{str(uptime_duration).split('.')[0]}**.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="admin-rp", description="Modify another user's RP. (Whitelisted users only)")
@app_commands.describe(user="The user to modify.", amount="Amount of RP.", action="Add, remove, or set RP.")
@app_commands.choices(action=[
    discord.app_commands.Choice(name="Add", value="add"),
    discord.app_commands.Choice(name="Remove", value="remove"),
    discord.app_commands.Choice(name="Set", value="set")
])
async def admin_rp(interaction: discord.Interaction, user: discord.Member, amount: int, action: str):
    log_function_call("admin_rp", interaction=interaction, user=user, amount=amount, action=action)
    if interaction.user.id not in WHITELISTED_USERS:
        embed = create_embed(
            title="Access Denied - LUNATIC FTW",
            description="You are not authorized to use this command.",
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=THUMBNAIL_URL)
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    user_id = str(user.id)
    server_id = str(interaction.guild.id)

    # Fetch the current RP
    async with db.execute(
        "SELECT weekly_rp FROM rp_data WHERE server_id = ? AND user_id = ?",
        (server_id, user_id)
    ) as cursor:
        row = await cursor.fetchone()
    
    current_rp = row[0] if row else 0

    # Perform the action
    if action == "add":
        new_rp = current_rp + amount
    elif action == "remove":
        new_rp = max(current_rp - amount, 0)  # Ensure RP doesn't go negative
    elif action == "set":
        new_rp = max(amount, 0)  # Ensure RP isn't negative
    else:
        return await interaction.response.send_message("Invalid action.", ephemeral=True)

    # Update the database
    await db.execute(
        "INSERT INTO rp_data (server_id, user_id, weekly_rp) VALUES (?, ?, ?) ON CONFLICT(server_id, user_id) DO UPDATE SET weekly_rp = ?", 
        (server_id, user_id, new_rp, new_rp)
    )
    await db.commit()

    # Send a confirmation embed
    embed = create_embed(
        title="RP Modified - LUNATIC FTW",
        description=f"**{user.display_name}**'s weekly RP has been updated:\n**New RP Total:** {new_rp}",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="ping", description="Tests the bot's response time")
async def ping(interaction: discord.Interaction):
    log_function_call("ping", interaction=interaction)
    embed = create_embed(
        title="Pong! - LUNATIC FTW",
        description=f"Latency: {round(bot.latency * 1000)}ms",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)


# add eval command for db
@bot.tree.command(name="eval-sql", description="Execute raw SQL commands. (Whitelisted users only)")
async def eval_sql(interaction: discord.Interaction, query: str):
    log_function_call("eval_sql", interaction=interaction, query=query)
    if interaction.user.id not in WHITELISTED_USERS:
        embed = create_embed(
            title="Access Denied - LUNATIC FTW",
            description="You are not authorized to perform this action.",
            color=discord.Color.red()
        )
        embed.set_thumbnail(url=THUMBNAIL_URL)
        return await interaction.response.send_message(embed=embed, ephemeral=True)

    try:
        async with db.execute(query) as cursor:
            if query.strip().lower().startswith("select"):
                rows = await cursor.fetchall()
                result = "\n".join(str(row) for row in rows)
            else:
                await db.commit()
                result = "Query executed successfully."
    except Exception as e:
        result = f"An error occurred: {e}"

    embed = create_embed(
        title="SQL Query Result - LUNATIC FTW",
        description=f"```{result}```",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed)

# Global error handler
@bot.event
async def on_command_error(ctx, error):
    error_message = f"Error in command `{ctx.command}`: {str(error)}"
    log_to_webhook(error_message)
    traceback.print_exc()

@bot.event
async def on_error(event_method, *args, **kwargs):
    error_message = f"Error in event `{event_method}`: {traceback.format_exc()}"
    log_to_webhook(error_message)
    traceback.print_exc()

# Read the token from a file named "token".
with open("token", "r") as token_file:
    TOKEN = token_file.read().strip()

bot.run(TOKEN)
