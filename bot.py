import discord
from discord.ext import commands, tasks
import requests
import os
import datetime
import asyncio
import json
import random
from dotenv import load_dotenv
from typing import Dict, List, Optional, Tuple

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GEOGUESSR_TOKEN = os.getenv('GEOGUESSR_TOKEN')

# Channel configuration - add your specific channel IDs here
ALLOWED_CHANNELS = [1386753541309468702, 1386746260819804220]

# Alternative: use environment variables for flexibility
# ALLOWED_CHANNELS = [int(x) for x in os.getenv('ALLOWED_CHANNELS', '1386753541309468702,1386746260819804220').split(',') if x]

# Enhanced configuration with multiple maps and game modes
GAME_MODES = {
    'nomove': {
        'name': 'No Move',
        'settings': {
            'forbidMoving': True,
            'forbidZooming': True,
            'forbidRotating': True,
            'timeLimit': 120
        }
    },
    'move': {
        'name': 'Moving',
        'settings': {
            'forbidMoving': False,
            'forbidZooming': False,
            'forbidRotating': False,
            'timeLimit': 300
        }
    },
    'nmpz': {
        'name': 'NMPZ',
        'settings': {
            'forbidMoving': True,
            'forbidZooming': True,
            'forbidRotating': True,
            'timeLimit': 90
        }
    }
}

# Map configurations
MAPS = {
    'community_world': {
        'id': '62a44b22040f04bd36e8a914',
        'name': 'A Community World'
    },
    'informed_world': {
        'id': '676340ae2f718dbabdf30331',
        'name': 'An Informed World'
    },
    'pro_world': {
        'id': '6620b311f64a7b842b2ca83a',
        'name': 'A Pro World'
    },
    'arbitrary_rural': {
        'id': '643dbc7ccc47d3a344307998',
        'name': 'An Arbitrary Rural World'
    },
    'rainbolt_world': {
        'id': '65c86935d327035509fd616f',
        'name': 'A Rainbolt World'
    }
}

# Daily rotation schedule
DAILY_ROTATION = [
    {'map': 'community_world', 'mode': 'move'},      # Monday
    {'map': 'pro_world', 'mode': 'nomove'},          # Tuesday  
    {'map': 'arbitrary_rural', 'mode': 'nmpz'},      # Wednesday
    {'map': 'informed_world', 'mode': 'move'},       # Thursday
    {'map': 'community_world', 'mode': 'nomove'},    # Friday
    {'map': 'rainbolt_world', 'mode': 'nmpz'},       # Saturday
    {'map': 'informed_world', 'mode': 'nomove'}      # Sunday
]

# Enhanced storage for multiple challenges
challenge_history = []
current_challenge = {
    'id': None,
    'url': None,
    'map': None,
    'mode': None,
    'created_at': None,
    'day_number': 0
}

# Set up bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

class GeoGuessrAPI:
    """Enhanced GeoGuessr API wrapper with multiple game mode support."""
    
    @staticmethod
    def create_challenge(map_id: str, game_mode: str) -> Tuple[Optional[str], Optional[str]]:
        """Creates a new GeoGuessr challenge with specified map and game mode."""
        if game_mode not in GAME_MODES:
            return None, None
            
        url = "https://www.geoguessr.com/api/v3/challenges"
        headers = {"Content-Type": "application/json"}
        cookies = {"_ncfa": GEOGUESSR_TOKEN}
        
        # Get game mode settings
        mode_settings = GAME_MODES[game_mode]['settings']
        
        payload = {
            "map": map_id,
            **mode_settings  # Unpack the mode-specific settings
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
    
    @staticmethod
    def get_challenge_results(challenge_id: str) -> Optional[dict]:
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

def get_today_rotation() -> Dict[str, str]:
    """Gets today's map and mode based on the weekly rotation."""
    today = datetime.datetime.now().weekday()  # Monday = 0, Sunday = 6
    return DAILY_ROTATION[today]

def format_leaderboard(results: dict, max_players: int = 10) -> List[str]:
    """Formats challenge results into a leaderboard."""
    leaderboard = []
    
    if 'items' in results and isinstance(results['items'], list):
        player_list = results['items'][:max_players]  # Limit to top players
        
        for i, player_data in enumerate(player_list, 1):
            if 'game' in player_data and 'player' in player_data['game']:
                player = player_data['game']['player']
                nick = player.get('nick', 'Unknown')
                score = player.get('totalScore', {}).get('amount', '0')
                
                # Add medal emojis for top 3
                medal = ""
                if i == 1:
                    medal = "🥇 "
                elif i == 2:
                    medal = "🥈 "
                elif i == 3:
                    medal = "🥉 "
                
                leaderboard.append(f"{medal}{i}. **{nick}** - {score:,}")
    
    return leaderboard

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    print(f'Available maps: {", ".join(MAPS.keys())}')
    print(f'Available modes: {", ".join(GAME_MODES.keys())}')

@tasks.loop(time=datetime.time(hour=12, minute=0))  # Post at 12:00 PM UTC
async def daily_challenge_cycle():
    """Posts previous day's results and creates a new daily challenge."""
    # Use the first allowed channel for daily posts
    target_channel = bot.get_channel(ALLOWED_CHANNELS[0])
    
    if not target_channel:
        print("❌ No valid channel found for daily challenge posting!")
        return
    
    # First, post results from yesterday's challenge if it exists
    if current_challenge['id']:
        await post_previous_results(target_channel)
        await asyncio.sleep(2)  # Small delay between messages
    
    # Create today's new challenge
    await create_todays_challenge(target_channel)

async def post_previous_results(channel):
    """Posts results from the previous challenge."""
    results = GeoGuessrAPI.get_challenge_results(current_challenge['id'])
    
    if not results:
        await channel.send("⚠️ Could not retrieve results from yesterday's challenge.")
        return
    
    # Get previous challenge info
    prev_map = MAPS.get(current_challenge['map'], {})
    prev_mode = GAME_MODES.get(current_challenge['mode'], {})
    
    leaderboard = format_leaderboard(results)
    
    embed = discord.Embed(
        title=f"Final Results - Day #{current_challenge['day_number']}",
        description=f"**{prev_map.get('name', 'Unknown')}** | **{prev_mode.get('name', 'Unknown')}**",
        color=0xFF6B6B
    )
    
    if leaderboard:
        embed.add_field(
            name="Leaderboard",
            value="\n".join(leaderboard),
            inline=False
        )
        
        # Add some stats
        total_players = len(results.get('items', []))
        embed.add_field(name="Total Players", value=str(total_players), inline=True)
        
        if total_players > 0:
            # Get winner info
            winner_data = results['items'][0]['game']['player']
            winner_score = winner_data.get('totalScore', {}).get('amount', 0)
            embed.add_field(name="Winning Score", value=f"{winner_score:,}", inline=True)
    else:
        embed.add_field(
            name="No Results",
            value="No one completed yesterday's challenge.",
            inline=False
        )
    
    await channel.send(embed=embed)

async def create_todays_challenge(channel):
    """Creates and posts today's new challenge."""
    rotation = get_today_rotation()
    map_key = rotation['map']
    mode_key = rotation['mode']
    
    map_config = MAPS.get(map_key)
    mode_config = GAME_MODES.get(mode_key)
    
    if not map_config or not mode_config:
        await channel.send("❌ Invalid map or mode configuration for today.")
        return
    
    # Create the challenge
    challenge_id, challenge_url = GeoGuessrAPI.create_challenge(
        map_config['id'], 
        mode_key
    )
    
    if not challenge_id:
        await channel.send("❌ Failed to create today's challenge. Please try again later.")
        return
    
    # Update current challenge info
    global current_challenge
    current_challenge = {
        'id': challenge_id,
        'url': challenge_url,
        'map': map_key,
        'mode': mode_key,
        'created_at': datetime.datetime.now(),
        'day_number': current_challenge['day_number'] + 1
    }
    
    # Add to history
    challenge_history.append(current_challenge.copy())
    
    # Create clean embed
    embed = discord.Embed(
        title=f"Daily Challenge #{current_challenge['day_number']}",
        description=f"**{map_config['name']}** | **{mode_config['name']}** | **{mode_config['settings']['timeLimit']}s**",
        color=0x4ECDC4
    )
    
    embed.add_field(
        name="Play Challenge",
        value=f"[Click here to play]({challenge_url})",
        inline=False
    )
    
    await channel.send(embed=embed)

# Enhanced Commands

@bot.command(name='challenge')
async def manual_challenge(ctx, map_name: str = None, mode_name: str = None):
    """Creates a custom challenge with specified map and mode."""
    if not is_allowed_channel(ctx):
        return
    
    # If no parameters, use today's rotation
    if not map_name or not mode_name:
        rotation = get_today_rotation()
        map_name = rotation['map']
        mode_name = rotation['mode']
        await ctx.send(f"Using today's rotation: {map_name} + {mode_name}")
    
    # Validate inputs
    if map_name not in MAPS:
        available_maps = ", ".join(MAPS.keys())
        await ctx.send(f"❌ Invalid map. Available maps: `{available_maps}`")
        return
    
    if mode_name not in GAME_MODES:
        available_modes = ", ".join(GAME_MODES.keys())
        await ctx.send(f"❌ Invalid mode. Available modes: `{available_modes}`")
        return
    
    await ctx.send("Creating custom challenge...")
    
    map_config = MAPS[map_name]
    challenge_id, challenge_url = GeoGuessrAPI.create_challenge(map_config['id'], mode_name)
    
    if not challenge_id:
        await ctx.send("❌ Failed to create challenge.")
        return
    
    mode_config = GAME_MODES[mode_name]
    
    embed = discord.Embed(
        title="Custom Challenge Created",
        description=f"**{map_config['name']}** | **{mode_config['name']}** | **{mode_config['settings']['timeLimit']}s**",
        color=0x9B59B6
    )
    
    embed.add_field(name="Play Challenge", value=f"[Click here to play]({challenge_url})", inline=False)
    embed.add_field(name="Challenge ID", value=f"`{challenge_id}`", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='leaderboard', aliases=['lb'])
async def get_leaderboard(ctx, challenge_id: str = None):
    """Gets the leaderboard for current or specified challenge."""
    if not is_allowed_channel(ctx):
        return
    
    # Use current challenge if no ID specified
    if not challenge_id:
        if not current_challenge['id']:
            await ctx.send("❌ No active challenge. Create one with `!challenge`")
            return
        challenge_id = current_challenge['id']
        is_current = True
    else:
        is_current = False
    
    await ctx.send("Fetching leaderboard...")
    
    results = GeoGuessrAPI.get_challenge_results(challenge_id)
    if not results:
        await ctx.send("❌ Could not retrieve leaderboard.")
        return
    
    leaderboard = format_leaderboard(results)
    
    if is_current:
        map_config = MAPS.get(current_challenge['map'], {})
        mode_config = GAME_MODES.get(current_challenge['mode'], {})
        title = f"Current Leaderboard - Day #{current_challenge['day_number']}"
        description = f"**{map_config.get('name', 'Unknown')}** | **{mode_config.get('name', 'Unknown')}**"
    else:
        title = f"Challenge Leaderboard"
        description = f"Challenge ID: `{challenge_id}`"
    
    embed = discord.Embed(title=title, description=description, color=0x3498DB)
    
    if leaderboard:
        embed.add_field(
            name="Rankings",
            value="\n".join(leaderboard),
            inline=False
        )
        
        total_players = len(results.get('items', []))
        embed.add_field(name="Players", value=str(total_players), inline=True)
        
        if is_current:
            embed.add_field(
                name="Join Challenge",
                value=f"[Play now]({current_challenge['url']})",
                inline=True
            )
    else:
        embed.add_field(
            name="No Results Yet",
            value="No one has completed this challenge yet.",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='schedule')
async def show_schedule(ctx):
    """Shows the weekly rotation schedule."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    embed = discord.Embed(
        title="Weekly Challenge Schedule",
        description="Here's what to expect each day of the week:",
        color=0xE67E22
    )
    
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    for i, day in enumerate(days):
        rotation = DAILY_ROTATION[i]
        map_config = MAPS[rotation['map']]
        mode_config = GAME_MODES[rotation['mode']]
        
        is_today = i == datetime.datetime.now().weekday()
        day_name = f"**{day}**" if is_today else day
        if is_today:
            day_name += " (Today)"
        
        embed.add_field(
            name=day_name,
            value=f"{map_config['name']} | {mode_config['name']}",
            inline=True
        )
    
    embed.set_footer(text="Use !challenge [map] [mode] for custom challenges")
    await ctx.send(embed=embed)

@bot.command(name='maps')
async def list_maps(ctx):
    """Lists all available maps."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    embed = discord.Embed(
        title="Available Maps",
        color=0x27AE60
    )
    
    move_maps = [
        "`community_world` - A Community World",
        "`informed_world` - An Informed World"
    ]
    
    nomove_maps = [
        "`community_world` - A Community World", 
        "`informed_world` - An Informed World",
        "`pro_world` - A Pro World"
    ]
    
    nmpz_maps = [
        "`arbitrary_rural` - An Arbitrary Rural World",
        "`rainbolt_world` - A Rainbolt World"
    ]
    
    embed.add_field(name="Move Mode", value="\n".join(move_maps), inline=False)
    embed.add_field(name="No Move Mode", value="\n".join(nomove_maps), inline=False) 
    embed.add_field(name="NMPZ Mode", value="\n".join(nmpz_maps), inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='modes')
async def list_modes(ctx):
    """Lists all available game modes."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    embed = discord.Embed(
        title="Available Game Modes",
        color=0x8E44AD
    )
    
    for key, mode_config in GAME_MODES.items():
        settings = mode_config['settings']
        time_limit = settings['timeLimit']
        
        restrictions = []
        if settings['forbidMoving']:
            restrictions.append("No Moving")
        if settings['forbidZooming']:
            restrictions.append("No Zooming")
        if settings['forbidRotating']:
            restrictions.append("No Rotating")
        
        if not restrictions:
            restrictions.append("Full Movement")
        
        embed.add_field(
            name=mode_config['name'],
            value=f"`{key}` - {time_limit}s | {', '.join(restrictions)}",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='status')
async def check_status(ctx):
    """Shows detailed status of the current challenge and bot."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    embed = discord.Embed(
        title="Bot Status",
        color=0x95A5A6
    )
    
    if current_challenge['id']:
        map_config = MAPS.get(current_challenge['map'], {})
        mode_config = GAME_MODES.get(current_challenge['mode'], {})
        
        created_time = current_challenge['created_at']
        time_ago = datetime.datetime.now() - created_time
        hours_ago = int(time_ago.total_seconds() / 3600)
        
        embed.add_field(
            name="Current Challenge",
            value=f"Day #{current_challenge['day_number']}\n{map_config.get('name', 'Unknown')} | {mode_config.get('name', 'Unknown')}",
            inline=False
        )
        
        embed.add_field(name="Challenge ID", value=f"`{current_challenge['id']}`", inline=True)
        embed.add_field(name="Created", value=f"{hours_ago}h ago", inline=True)
        embed.add_field(name="Play", value=f"[Link]({current_challenge['url']})", inline=True)
    else:
        embed.add_field(
            name="No Active Challenge",
            value="Use `!challenge` to create one",
            inline=False
        )
    
    # Daily task status
    task_status = "Running" if not daily_challenge_cycle.is_cancelled() else "Stopped"
    embed.add_field(name="Daily Tasks", value=task_status, inline=True)
    
    # Next daily challenge time
    now = datetime.datetime.now()
    tomorrow_noon = (now + datetime.timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    time_until = tomorrow_noon - now
    hours_until = int(time_until.total_seconds() / 3600)
    
    embed.add_field(name="Next Daily", value=f"in {hours_until}h", inline=True)
    
    embed.add_field(name="Total Challenges", value=str(len(challenge_history)), inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='start_daily')
async def start_daily_task(ctx):
    """Starts the daily challenge cycle."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    if not daily_challenge_cycle.is_cancelled():
        await ctx.send("✅ Daily challenges are already running!")
        return
    
    daily_challenge_cycle.start()
    await ctx.send("🚀 Daily challenge cycle started! New challenges will post at 12:00 PM UTC.")

@bot.command(name='stop_daily')
async def stop_daily_task(ctx):
    """Stops the daily challenge cycle."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    daily_challenge_cycle.cancel()
    await ctx.send("⏹️ Daily challenge cycle stopped.")

@bot.command(name='force_daily')
async def force_daily_cycle(ctx):
    """Manually triggers the daily cycle (results + new challenge)."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    await ctx.send("🔄 Manually triggering daily cycle...")
    await daily_challenge_cycle()

@bot.command(name='help_geo')
async def help_geo(ctx):
    """Shows comprehensive help for all bot commands."""
    if ctx.channel.id != CHANNEL_ID:
        return
    
    embed = discord.Embed(
        title="GeoGuessr Multi-Mode Challenge Bot",
        description="Your GeoGuessr challenge companion",
        color=0x2ECC71
    )
    
    # Basic Commands
    embed.add_field(
        name="Challenge Commands",
        value=(
            "`!challenge` - Create today's scheduled challenge\n"
            "`!challenge [map] [mode]` - Create custom challenge\n"
            "`!leaderboard` - Show current challenge leaderboard\n"
            "`!leaderboard [id]` - Show specific challenge results"
        ),
        inline=False
    )
    
    # Information Commands  
    embed.add_field(
        name="Information Commands",
        value=(
            "`!schedule` - View weekly rotation schedule\n"
            "`!maps` - List all available maps\n" 
            "`!modes` - List all available game modes\n"
            "`!status` - Show bot and challenge status"
        ),
        inline=False
    )
    
    # Admin Commands
    embed.add_field(
        name="Admin Commands",
        value=(
            "`!start_daily` - Start automatic daily challenges\n"
            "`!stop_daily` - Stop automatic daily challenges\n"
            "`!force_daily` - Manually trigger daily cycle"
        ),
        inline=False
    )
    
    embed.add_field(
        name="Features",
        value=(
            "Multiple maps and game modes\n"
            "Weekly rotation schedule\n"
            "Automatic daily results posting\n"
            "Custom challenge creation"
        ),
        inline=False
    )
    
    await ctx.send(embed=embed)

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore unknown commands
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument. Use `!help_geo` for command help.")
    else:
        print(f"Error: {error}")
        await ctx.send(f"❌ An error occurred: {str(error)}")

# Run the bot
if __name__ == "__main__":
    print("🚀 Starting Enhanced GeoGuessr Challenge Bot...")
    bot.run(TOKEN)
