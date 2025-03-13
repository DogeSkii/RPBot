import discord
from discord.ext import commands
import aiosqlite
import asyncio
import datetime

# Use all intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=".", intents=intents)

DATABASE = "rp_database.db"
db = None

async def initialize_database():
    global db
    db = await aiosqlite.connect(DATABASE)
    
    # Create the table if it doesn't exist (initially with only user_id).
    await db.execute("""
        CREATE TABLE IF NOT EXISTS rp_data (
            user_id TEXT PRIMARY KEY
        )
    """)
    await db.commit()

    # Check existing columns and add missing ones.
    async with db.execute("PRAGMA table_info(rp_data)") as cursor:
        columns = await cursor.fetchall()
    existing_columns = {col[1] for col in columns}
    
    if "weekly_rp" not in existing_columns:
        await db.execute("ALTER TABLE rp_data ADD COLUMN weekly_rp INTEGER DEFAULT 0")
    if "historical_rp" not in existing_columns:
        await db.execute("ALTER TABLE rp_data ADD COLUMN historical_rp INTEGER DEFAULT 0")
    await db.commit()

async def weekly_reset():
    # Move weekly RP to historical RP and reset weekly_rp for all users.
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
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Error syncing commands: {e}")
    # Start the weekly reset background task.
    bot.loop.create_task(weekly_reset_task())

@bot.tree.command(name="rp", description="Add RP to your account.")
async def rp(interaction: discord.Interaction, amount: int):
    user_id = str(interaction.user.id)
    async with db.execute("SELECT weekly_rp FROM rp_data WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
    
    if row is None:
        new_total = amount
        await db.execute("INSERT INTO rp_data (user_id, weekly_rp) VALUES (?, ?)", (user_id, new_total))
    else:
        new_total = row[0] + amount
        await db.execute("UPDATE rp_data SET weekly_rp = ? WHERE user_id = ?", (new_total, user_id))
    await db.commit()
    
    embed = discord.Embed(
        title="RP Added",
        description=f"Added **{amount} RP** to your account.\nYour weekly total is now **{new_total} RP**.",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="revoke-rp", description="Revoke RP from your account.")
async def revoke_rp(interaction: discord.Interaction, amount: int):
    user_id = str(interaction.user.id)
    async with db.execute("SELECT weekly_rp FROM rp_data WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
    
    if row is None:
        embed = discord.Embed(
            title="No RP Found",
            description="You don't have any RP to revoke.",
            color=discord.Color.red()
        )
        return await interaction.response.send_message(embed=embed)
    
    new_total = max(row[0] - amount, 0)
    await db.execute("UPDATE rp_data SET weekly_rp = ? WHERE user_id = ?", (new_total, user_id))
    await db.commit()
    
    embed = discord.Embed(
        title="RP Revoked",
        description=f"Revoked **{amount} RP** from your account.\nYour weekly total is now **{new_total} RP**.",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="leaderboard", description="Show the weekly RP leaderboard.")
async def leaderboard(interaction: discord.Interaction):
    # Exclude users with 0 weekly RP.
    async with db.execute("SELECT user_id, weekly_rp FROM rp_data WHERE weekly_rp > 0 ORDER BY weekly_rp DESC LIMIT 10") as cursor:
        rows = await cursor.fetchall()
    
    if not rows:
        embed = discord.Embed(
            title="Leaderboard",
            description="No RP records found.",
            color=discord.Color.blue()
        )
        return await interaction.response.send_message(embed=embed)
    
    description = ""
    for position, (user_id, rp_amount) in enumerate(rows, start=1):
        member = bot.get_user(int(user_id))
        name = member.name if member else f"User {user_id}"
        description += f"**{position}. {name}** — **{rp_amount} RP**\n"
    
    embed = discord.Embed(
        title="Weekly RP Leaderboard",
        description=description,
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="historical-rp", description="Show your historical RP total.")
async def historical_rp(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    async with db.execute("SELECT historical_rp, weekly_rp FROM rp_data WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
    
    if row is None:
        historical, weekly = 0, 0
    else:
        historical, weekly = row[0], row[1]
    
    embed = discord.Embed(
        title="Your RP Totals",
        description=(
            f"**Historical RP:** {historical} RP\n"
            f"**Current Weekly RP:** {weekly} RP"
        ),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="simulate-weekly-wipe", description="Simulate a weekly wipe immediately.")
async def simulate_weekly_wipe(interaction: discord.Interaction):
    await weekly_reset()
    embed = discord.Embed(
        title="Weekly Wipe Simulated",
        description="Weekly RP has been wiped and moved to historical RP.",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="revoke-historical-rp", description="Revoke RP from your historical total.")
async def revoke_historical_rp(interaction: discord.Interaction, amount: int):
    user_id = str(interaction.user.id)
    async with db.execute("SELECT historical_rp FROM rp_data WHERE user_id = ?", (user_id,)) as cursor:
        row = await cursor.fetchone()
    
    if row is None:
        embed = discord.Embed(
            title="No Historical RP Found",
            description="You don't have any historical RP to revoke.",
            color=discord.Color.red()
        )
        return await interaction.response.send_message(embed=embed)
    
    new_total = max(row[0] - amount, 0)
    await db.execute("UPDATE rp_data SET historical_rp = ? WHERE user_id = ?", (new_total, user_id))
    await db.commit()
    
    embed = discord.Embed(
        title="Historical RP Revoked",
        description=f"Revoked **{amount} RP** from your historical RP total.\nYour new total is **{new_total} RP**.",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed)



# Read the token from a file named "token".
with open("token", "r") as token_file:
    TOKEN = token_file.read().strip()

bot.run(TOKEN)
