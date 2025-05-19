import discord
from discord.ext import commands, tasks
import requests
import os
import datetime
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GEOGUESSR_TOKEN = os.getenv('GEOGUESSR_TOKEN')
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
MAP_ID = os.getenv('MAP_ID')

# Global variables instead of file storage
current_challenge = {
    'id': None,
    'url': None,
    'created_at': None
}
challenge_count = 0

# Set up bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# GeoGuessr API functions
def create_challenge(map_id):
    """Creates a new GeoGuessr challenge using the provided map ID."""
    url = "https://www.geoguessr.com/api/v3/challenges"
    headers = {"Content-Type": "application/json"}
    cookies = {"_ncfa": GEOGUESSR_TOKEN}
    payload = {
        "map": map_id,
        "forbidMoving": False,
        "forbidZooming": False,
        "forbidRotating": False,
        "timeLimit": 300  # 5 minutes in seconds
    }
    
    try:
        response = requests.post(url, headers=headers, cookies=cookies, json=payload)
        response.raise_for_status()
        data = response.json()
        challenge_id = data.get('token')
        challenge_url = f"https://www.geoguessr.com/challenge/{challenge_id}"
        return challenge_id, challenge_url
    except requests.RequestException as e:
        print(f"Error creating challenge: {e}")
        return None, None

def get_challenge_results(challenge_id):
    """Gets the results/leaderboard for a specific challenge."""
    url = f"https://www.geoguessr.com/api/v3/results/highscores/{challenge_id}"
    cookies = {"_ncfa": GEOGUESSR_TOKEN}
    
    try:
        response = requests.get(url, cookies=cookies)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error getting challenge results: {e}")
        return None

# Bot events and commands
@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    # Don't automatically start the challenge on startup
    # create_daily_challenge.start()

@tasks.loop(time=datetime.time(hour=12, minute=0))  # Post at 12:00 PM UTC
async def create_daily_challenge():
    """Creates and posts a new daily challenge."""
    channel = bot.get_channel(CHANNEL_ID)
    
    # Create a new challenge
    challenge_id, challenge_url = create_challenge(MAP_ID)
    if not challenge_id:
        await channel.send("Failed to create today's GeoGuessr challenge. Please try again later.")
        return
    
    # Store challenge information in memory
    global current_challenge, challenge_count
    current_challenge['id'] = challenge_id
    current_challenge['url'] = challenge_url
    current_challenge['created_at'] = datetime.datetime.now()
    challenge_count += 1
    
    # Post challenge to Discord
    embed = discord.Embed(
        title=f"Daily Challenge #{challenge_count}",
        description=f"A new GeoGuessr challenge has been created! Click the link below to play:",
        color=0x00ff00
    )
    embed.add_field(name="Challenge Link", value=challenge_url, inline=False)
    embed.set_footer(text=f"Use !post_results to post the leaderboard when you're ready")
    
    await channel.send(embed=embed)

async def post_results(challenge_id):
    """Posts the results for a challenge."""
    channel = bot.get_channel(CHANNEL_ID)
    
    # Get challenge results
    results = get_challenge_results(challenge_id)
    if not results:
        await channel.send("Failed to retrieve leaderboard for the challenge.")
        return
    
    # Format leaderboard
    leaderboard = []
    
    # Process the JSON response structure we now understand
    if 'items' in results and isinstance(results['items'], list):
        player_list = results['items']
        
        for i, player_data in enumerate(player_list, 1):
            if 'game' in player_data and 'player' in player_data['game']:
                player = player_data['game']['player']
                nick = player.get('nick', 'Unknown')
                score = player.get('totalScore', {}).get('amount', '0')
                leaderboard.append(f"{i}. {nick} ({score})")
    
    # Create and send embed
    embed = discord.Embed(
        title=f"Leaderboard from the challenge:",
        description="\n".join(leaderboard) if leaderboard else "No players have completed this challenge yet.",
        color=0x0000ff
    )
    embed.set_footer(text=f"Use !challenge to create a new challenge!")
    
    await channel.send(embed=embed)

@bot.command(name='challenge')
async def manual_challenge(ctx):
    """Manually creates a new challenge."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    await ctx.send("Creating a new GeoGuessr challenge...")
    # Run the task function directly rather than through the task system
    await create_daily_challenge()

@bot.command(name='post_results')
async def manual_post_results(ctx):
    """Manually posts the results for the current challenge."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    if not current_challenge['id']:
        await ctx.send("No active challenge found. Create one with !challenge first.")
        return
    
    await ctx.send("Posting leaderboard for the current challenge...")
    await post_results(current_challenge['id'])

@bot.command(name='post_results_for')
async def post_results_for_challenge(ctx, challenge_id: str):
    """Manually posts the results for a specific challenge ID."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    if not challenge_id:
        await ctx.send("Please provide a challenge ID. Usage: !post_results_for [challenge_id]")
        return
    
    await ctx.send(f"Posting leaderboard for challenge {challenge_id}...")
    await post_results(challenge_id)

@bot.command(name='leaderboard')
async def get_leaderboard(ctx):
    """Gets the leaderboard for the current challenge."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    if not current_challenge['id']:
        await ctx.send("No active challenge found. Create one with !challenge first.")
        return
    
    await ctx.send("Fetching leaderboard for the current challenge...")
    await post_results(current_challenge['id'])

@bot.command(name='status')
async def check_status(ctx):
    """Checks the status of the current challenge."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    if not current_challenge['id']:
        await ctx.send("No active challenge found. Create one with !challenge.")
        return
    
    created_time = current_challenge['created_at']
    time_ago = datetime.datetime.now() - created_time
    hours_ago = int(time_ago.total_seconds() / 3600)
    
    embed = discord.Embed(
        title=f"Current Challenge Status",
        description=f"Challenge #{challenge_count} is active.",
        color=0x00ff00
    )
    embed.add_field(name="Challenge ID", value=current_challenge['id'], inline=False)
    embed.add_field(name="Challenge Link", value=current_challenge['url'], inline=False)
    embed.add_field(name="Created", value=f"{hours_ago} hours ago", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='start_daily')
async def start_daily_task(ctx):
    """Starts the daily challenge task."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    create_daily_challenge.start()
    await ctx.send("Daily challenges have been scheduled to post at 12:00 PM UTC.")

@bot.command(name='stop_daily')
async def stop_daily_task(ctx):
    """Stops the daily challenge task."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    create_daily_challenge.cancel()
    await ctx.send("Daily challenges have been stopped.")

@bot.command(name='help_geo')
async def help_geo(ctx):
    """Shows help for GeoGuessr bot commands."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    embed = discord.Embed(
        title="GeoGuessr Challenge Bot Commands",
        description="Here are the available commands:",
        color=0x4caf50
    )
    
    embed.add_field(name="!challenge", value="Creates a new GeoGuessr challenge", inline=False)
    embed.add_field(name="!leaderboard", value="Shows the current challenge leaderboard", inline=False)
    embed.add_field(name="!post_results", value="Posts the leaderboard for the current challenge", inline=False)
    embed.add_field(name="!post_results_for [id]", value="Posts the leaderboard for a specific challenge ID", inline=False)
    embed.add_field(name="!status", value="Shows the status of the current challenge", inline=False)
    embed.add_field(name="!start_daily", value="Schedules daily challenges at 12:00 PM UTC", inline=False)
    embed.add_field(name="!stop_daily", value="Stops the scheduled daily challenges", inline=False)
    
    await ctx.send(embed=embed)

# Run the bot
if __name__ == "__main__":
    bot.run(TOKEN)