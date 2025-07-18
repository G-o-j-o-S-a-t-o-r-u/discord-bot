# main.py (Final Version)

import discord
import requests
import json
import threading
import hmac
import hashlib
import xmltodict
from flask import Flask, request, abort, Response
from typing import Optional, Dict
from database import StreamDatabase
from config import *

# Initialize Discord Bot client
intents = discord.Intents.default()
intents.guilds = True
bot = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(bot)

# Initialize Flask web server
app = Flask(__name__)

# Initialize Database
db = StreamDatabase()

# Stores the Twitch App Access Token
TWITCH_ACCESS_TOKEN = None

# --- TWITCH API HELPER FUNCTIONS ---

def get_twitch_app_access_token() -> Optional[str]:
    """Get Twitch application access token."""
    global TWITCH_ACCESS_TOKEN
    params = {
        'client_id': TWITCH_CLIENT_ID,
        'client_secret': TWITCH_CLIENT_SECRET,
        'grant_type': 'client_credentials'
    }
    try:
        response = requests.post(TWITCH_TOKEN_URL, params=params)
        response.raise_for_status()
        TWITCH_ACCESS_TOKEN = response.json()['access_token']
        print("Successfully refreshed Twitch App Access Token.")
        return TWITCH_ACCESS_TOKEN
    except Exception as e:
        print(f"Error getting Twitch token: {e}")
        TWITCH_ACCESS_TOKEN = None
        return None

def get_twitch_user_id(username: str) -> Optional[str]:
    """Get Twitch user ID from username."""
    if not TWITCH_ACCESS_TOKEN:
        get_twitch_app_access_token()
    if not TWITCH_ACCESS_TOKEN:
        return None
    
    headers = {
        'Client-ID': TWITCH_CLIENT_ID,
        'Authorization': f'Bearer {TWITCH_ACCESS_TOKEN}'
    }
    params = {'login': username.lower()}
    
    try:
        response = requests.get(TWITCH_USERS_URL, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        return data['data'][0]['id'] if data.get('data') else None
    except Exception as e:
        print(f"Error getting Twitch user ID for {username}: {e}")
        return None

def create_twitch_subscription(user_id: str, callback_url: str) -> Optional[str]:
    """Create Twitch EventSub subscription."""
    if not TWITCH_ACCESS_TOKEN:
        get_twitch_app_access_token()
    if not TWITCH_ACCESS_TOKEN:
        return None
    
    headers = {
        'Client-ID': TWITCH_CLIENT_ID,
        'Authorization': f'Bearer {TWITCH_ACCESS_TOKEN}',
        'Content-Type': 'application/json'
    }
    payload = {
        'type': 'stream.online',
        'version': '1',
        'condition': {'broadcaster_user_id': user_id},
        'transport': {
            'method': 'webhook',
            'callback': callback_url,
            'secret': WEBHOOK_SECRET
        }
    }
    
    response = None
    try:
        response = requests.post(TWITCH_EVENTSUB_URL, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()['data'][0]['id']
    except Exception as e:
        print(f"Error creating Twitch subscription: {e}")
        if response and hasattr(response, 'text'):
            print(f"Response: {response.text}")
        return None

def delete_twitch_subscription(subscription_id: str) -> bool:
    """Delete a specific Twitch subscription."""
    if not TWITCH_ACCESS_TOKEN:
        get_twitch_app_access_token()
    if not TWITCH_ACCESS_TOKEN:
        return False
    
    headers = {
        'Client-ID': TWITCH_CLIENT_ID,
        'Authorization': f'Bearer {TWITCH_ACCESS_TOKEN}'
    }
    
    try:
        response = requests.delete(f'{TWITCH_EVENTSUB_URL}?id={subscription_id}', headers=headers)
        response.raise_for_status()
        print(f"Deleted Twitch subscription {subscription_id}")
        return True
    except Exception as e:
        print(f"Error deleting Twitch subscription {subscription_id}: {e}")
        return False

def delete_all_twitch_subscriptions() -> None:
    """Delete all existing Twitch subscriptions."""
    if not TWITCH_ACCESS_TOKEN:
        get_twitch_app_access_token()
    if not TWITCH_ACCESS_TOKEN:
        return
    
    headers = {
        'Client-ID': TWITCH_CLIENT_ID,
        'Authorization': f'Bearer {TWITCH_ACCESS_TOKEN}'
    }
    
    try:
        response = requests.get(TWITCH_EVENTSUB_URL, headers=headers)
        response.raise_for_status()
        subscriptions = response.json().get('data', [])
        for sub in subscriptions:
            requests.delete(f'{TWITCH_EVENTSUB_URL}?id={sub["id"]}', headers=headers)
            print(f"Deleted old Twitch subscription {sub['id']}")
    except Exception as e:
        print(f"An error occurred while deleting Twitch subscriptions: {e}")

# --- YOUTUBE API HELPER FUNCTIONS ---

def get_youtube_channel_info(channel_id: str) -> Optional[Dict]:
    """Get YouTube channel information."""
    params = {
        'part': 'snippet',
        'id': channel_id,
        'key': YOUTUBE_API_KEY
    }
    
    try:
        response = requests.get(YOUTUBE_CHANNELS_URL, params=params)
        response.raise_for_status()
        data = response.json()
        return data['items'][0]['snippet'] if data.get('items') else None
    except Exception as e:
        print(f"Error getting YouTube channel info for {channel_id}: {e}")
        return None

def create_youtube_subscription(channel_id: str, callback_url: str) -> bool:
    """Subscribe to YouTube channel's PubSubHubbub feed."""
    topic_url = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={channel_id}"
    data = {
        'hub.mode': 'subscribe',
        'hub.topic': topic_url,
        'hub.callback': callback_url,
        'hub.secret': WEBHOOK_SECRET,
        'hub.lease_seconds': 864000  # 10 days
    }
    
    try:
        response = requests.post(YOUTUBE_PUBSUB_URL, data=data)
        return response.status_code in [200, 202, 204]
    except Exception as e:
        print(f"Error creating YouTube subscription: {e}")
        return False

# --- DISCORD BOT EVENTS & COMMANDS ---

@bot.event
async def on_ready():
    """Bot ready event handler."""
    print(f'Logged in as {bot.user}')
    print("Deleting all old Twitch subscriptions...")
    delete_all_twitch_subscriptions()
    
    try:
        synced = await tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    
    print("Bot is ready.")

@tree.command(name="add", description="Subscribe to a Twitch streamer or YouTube channel")
@discord.app_commands.describe(
    platform="Choose the platform (twitch or youtube)",
    identifier="Twitch username or YouTube channel ID (starts with UC...)",
    notification_channel="Channel to send notifications to (optional, defaults to current channel)",
    custom_message="Custom message to show when they go live (optional)"
)
@discord.app_commands.choices(platform=[
    discord.app_commands.Choice(name="Twitch", value="twitch"),
    discord.app_commands.Choice(name="YouTube", value="youtube")
])
async def add_command(interaction: discord.Interaction, platform: str, identifier: str, 
                     notification_channel: discord.TextChannel = None, custom_message: str = None):
    """Handle /add command to subscribe to a streamer."""
    await interaction.response.defer(ephemeral=True)
    
    target_channel = notification_channel if notification_channel else interaction.channel
    
    if platform == 'twitch':
        user_id = get_twitch_user_id(identifier)
        if not user_id:
            await interaction.followup.send(f"❌ Could not find a Twitch user named `{identifier}`.")
            return

        if db.subscription_exists(user_id):
            await interaction.followup.send(f"`{identifier}` is already being watched!")
            return
        
        callback_url = f"{WEBHOOK_BASE_URL}/webhooks/twitch"
        sub_id = create_twitch_subscription(user_id, callback_url)
        if sub_id:
            db.add_subscription(
                user_id, 'twitch', interaction.guild_id, 
                target_channel.id, identifier.lower(), sub_id, custom_message
            )
            await interaction.followup.send(f"✅ Subscribed to live notifications for **{identifier}** on Twitch!")
        else:
            await interaction.followup.send("❌ Failed to create Twitch webhook.")

    elif platform == 'youtube':
        channel_info = get_youtube_channel_info(identifier)
        if not channel_info:
            await interaction.followup.send(f"❌ Could not find a YouTube channel with ID `{identifier}`.")
            return
        
        if db.subscription_exists(identifier):
            await interaction.followup.send(f"`{channel_info['title']}` is already being watched!")
            return
        
        callback_url = f"{WEBHOOK_BASE_URL}/webhooks/youtube"
        if create_youtube_subscription(identifier, callback_url):
            db.add_subscription(
                identifier, 'youtube', interaction.guild_id,
                target_channel.id, channel_info['title'], None, custom_message
            )
            await interaction.followup.send(f"✅ Subscribed to live notifications for **{channel_info['title']}** on YouTube!")
        else:
            await interaction.followup.send("❌ Failed to create YouTube webhook.")

@tree.command(name="remove", description="Unsubscribe from a Twitch streamer or YouTube channel")
@discord.app_commands.describe(
    platform="Choose the platform (twitch or youtube)",
    identifier="Twitch username or YouTube channel ID"
)
@discord.app_commands.choices(platform=[
    discord.app_commands.Choice(name="Twitch", value="twitch"),
    discord.app_commands.Choice(name="YouTube", value="youtube")
])
async def remove_command(interaction: discord.Interaction, platform: str, identifier: str):
    """Handle /remove command to unsubscribe from a streamer."""
    await interaction.response.defer(ephemeral=True)
    
    guild_subscriptions = db.get_subscriptions_by_guild(interaction.guild_id)
    target_id = None
    streamer_name = identifier

    if platform == 'twitch':
        for sub_id, sub_data in guild_subscriptions.items():
            if sub_data['platform'] == 'twitch' and sub_data['name'].lower() == identifier.lower():
                target_id = sub_id
                break
    elif platform == 'youtube':
        if identifier in guild_subscriptions:
            target_id = identifier

    if not target_id:
        await interaction.followup.send(f"❌ No subscription found for `{identifier}` on {platform} in this server.")
        return
    
    subscription_data = db.get_subscription(target_id)
    if subscription_data:
        streamer_name = subscription_data['name']
        if platform == 'twitch' and subscription_data.get('subscription_id'):
            delete_twitch_subscription(subscription_data['subscription_id'])
        
        db.remove_subscription(target_id)
        await interaction.followup.send(f"✅ Unsubscribed from **{streamer_name}** on {platform.title()}!")
    else:
        await interaction.followup.send(f"❌ Could not find subscription data for `{identifier}`.")

@tree.command(name="list", description="Show all active stream subscriptions in this server")
async def list_command(interaction: discord.Interaction):
    """Handle /list command to show all subscriptions for this guild."""
    await interaction.response.defer(ephemeral=True)
    
    guild_subscriptions = db.get_subscriptions_by_guild(interaction.guild_id)
    
    if not guild_subscriptions:
        await interaction.followup.send("📋 No active subscriptions in this server.")
        return
    
    embed = discord.Embed(title="📋 Active Stream Subscriptions", color=discord.Color.blue())
    
    twitch_subs = [f"• {s['name']}" for s in guild_subscriptions.values() if s['platform'] == 'twitch']
    youtube_subs = [f"• {s['name']}" for s in guild_subscriptions.values() if s['platform'] == 'youtube']
    
    if twitch_subs:
        embed.add_field(name="🟣 Twitch", value="\n".join(twitch_subs), inline=False)
    
    if youtube_subs:
        embed.add_field(name="🔴 YouTube", value="\n".join(youtube_subs), inline=False)
    
    await interaction.followup.send(embed=embed)

@tree.command(name="test", description="Test stream notifications with a fake stream alert")
@discord.app_commands.describe(
    platform="Platform to test (twitch or youtube)",
    identifier="Twitch username or YouTube channel ID to test"
)
@discord.app_commands.choices(platform=[
    discord.app_commands.Choice(name="Twitch", value="twitch"),
    discord.app_commands.Choice(name="YouTube", value="youtube")
])
async def test_command(interaction: discord.Interaction, platform: str, identifier: str):
    """Test stream notification for a subscribed streamer."""
    await interaction.response.defer(ephemeral=True)
    
    subscription = None
    streamer_id = None

    for sub_id, sub_data in db.get_subscriptions_by_guild(interaction.guild_id).items():
        if sub_data['platform'] != platform:
            continue
        
        search_key = sub_data['name'] if platform == 'twitch' else sub_id
        if search_key.lower() == identifier.lower():
            subscription = sub_data
            streamer_id = sub_id
            break

    if not subscription:
        await interaction.followup.send(f"❌ No subscription found for `{identifier}` on {platform}. Add them first with `/add`!")
        return
    
    try:
        channel = bot.get_channel(subscription['channel_id'])
        if not channel:
            await interaction.followup.send(f"❌ Cannot find the notification channel. It may have been deleted.")
            return
        
        if platform == 'twitch':
            embed = discord.Embed(
                title=f"🔴 {subscription['name']} is now live!",
                description=f"**TEST NOTIFICATION**\n\nGame: Just Chatting\nViewers: 1,234",
                color=0x9146FF,
                url=f"https://twitch.tv/{subscription['name']}"
            )
            embed.set_thumbnail(url="https://static-cdn.jtvnw.net/jtv_user_pictures/default-profile_image-300x300.png")
        else:
            embed = discord.Embed(
                title=f"🔴 {subscription['name']} is streaming!",
                description=f"**TEST NOTIFICATION**\n\nLive on YouTube",
                color=0xFF0000,
                url=f"https://youtube.com/channel/{streamer_id}"
            )
            embed.set_thumbnail(url="https://yt3.ggpht.com/default_avatar_300x300.jpg")
        
        custom_message = subscription.get('custom_message', "")
        await channel.send(content=custom_message, embed=embed)
        await interaction.followup.send(f"✅ Test notification sent to {channel.mention} for `{subscription['name']}`!")
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error sending test notification: {str(e)}")

@tree.command(name="help", description="Show all available bot commands")
async def help_command(interaction: discord.Interaction):
    """Handle /help command to show available commands."""
    embed = discord.Embed(
        title="🤖 Stream Bot Commands",
        description="Monitor Twitch and YouTube streams with real-time notifications!",
        color=discord.Color.green()
    )
    embed.add_field(name="/add <platform> <identifier>", value="Subscribe to a streamer.", inline=False)
    embed.add_field(name="/remove <platform> <identifier>", value="Unsubscribe from a streamer.", inline=False)
    embed.add_field(name="/list", value="Show all active subscriptions in this server.", inline=False)
    embed.add_field(name="/test <platform> <identifier>", value="Send a fake stream notification.", inline=False)
    embed.set_footer(text="Note: For YouTube, use the Channel ID (starts with UC...)")
    await interaction.response.send_message(embed=embed)

# --- FLASK WEB SERVER (WEBHOOK LISTENER) ---

@app.route('/')
def home():
    """Health check endpoint."""
    return "Stream Notification Bot - Webhook Listener is running."

@app.route('/webhooks/twitch', methods=['POST'])
def twitch_webhook():
    """Handle Twitch webhook notifications."""
    message_id = request.headers.get('Twitch-Eventsub-Message-Id', '')
    message_timestamp = request.headers.get('Twitch-Eventsub-Message-Timestamp', '')
    message_signature = request.headers.get('Twitch-Eventsub-Message-Signature', '')
    hmac_message = message_id.encode('utf-8') + message_timestamp.encode('utf-8') + request.data
    expected_signature = 'sha256=' + hmac.new(WEBHOOK_SECRET.encode('utf-8'), hmac_message, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_signature, message_signature):
        print("Twitch signature mismatch!")
        abort(403)

    message_type = request.headers.get('Twitch-Eventsub-Message-Type')
    
    if message_type == 'webhook_callback_verification':
        json_data = request.get_json()
        if json_data and 'challenge' in json_data:
            return json_data['challenge'], 200
        return 'OK', 200

    elif message_type == 'notification':
        event = request.get_json().get('event', {})
        user_id = event.get('broadcaster_user_id')
        
        if not user_id: return 'OK', 200
        
        subscription = db.get_subscription(user_id)
        if subscription and subscription['platform'] == 'twitch':
            stream_details_url = f"https://api.twitch.tv/helix/streams?user_id={user_id}"
            headers = {'Client-ID': TWITCH_CLIENT_ID, 'Authorization': f'Bearer {TWITCH_ACCESS_TOKEN}'}
            game_name, stream_title = "No Category", "Stream is Live!"
            
            try:
                stream_response = requests.get(stream_details_url, headers=headers)
                stream_response.raise_for_status()
                stream_data = stream_response.json().get('data', [])
                if stream_data:
                    stream_info = stream_data[0]
                    game_name = stream_info.get('game_name', 'No Category')
                    stream_title = stream_info.get('title', 'No Title')
            except Exception as e:
                print(f"Could not fetch stream details for {user_id}: {e}")

            discord_channel = bot.get_channel(subscription['channel_id'])
            if discord_channel and hasattr(discord_channel, 'send'):
                username = event['broadcaster_user_name']
                custom_msg = subscription.get('custom_message', "")
                stream_url = f"https://twitch.tv/{username}"
                embed = discord.Embed(
                    title=f"{username} is now LIVE on Twitch!",
                    description=f"**{stream_title}**\nPlaying: **{game_name}**\n\n[Click here to watch!]({stream_url})",
                    url=stream_url, color=discord.Color.purple()
                )
                embed.set_thumbnail(url=f"https://static-cdn.jtvnw.net/jtv_user_pictures/{user_id}-profile_image-300x300.png")
                embed.set_footer(text="Click the title to watch the stream!")
                bot.loop.create_task(discord_channel.send(content=custom_msg, embed=embed))
        return 'OK', 200

    return 'OK', 200

@app.route('/webhooks/youtube', methods=['GET', 'POST'])
def youtube_webhook():
    """Handle YouTube webhook notifications."""
    if request.method == 'GET':
        challenge = request.args.get('hub.challenge')
        if challenge:
            return Response(challenge, mimetype='text/plain')
        return 'OK', 200

    elif request.method == 'POST':
        try:
            xml_data = xmltodict.parse(request.data)
            entry = xml_data.get('feed', {}).get('entry', {})
            video_id = entry.get('yt:videoId')
            channel_id = entry.get('yt:channelId')
            
            if not video_id or not channel_id:
                return 'OK', 200
        except Exception as e:
            print(f"Error parsing potential YouTube webhook, ignoring: {e}")
            return 'OK', 200
        
        subscription = db.get_subscription(channel_id)
        if subscription and subscription['platform'] == 'youtube':
            discord_channel = bot.get_channel(subscription['channel_id'])
            if discord_channel and hasattr(discord_channel, 'send'):
                channel_name = subscription['name']
                video_title = entry.get('title', 'New Video')
                custom_msg = subscription.get('custom_message', "")
                stream_url = f"https://www.youtube.com/watch?v={video_id}"
                
                embed = discord.Embed(
                    title=f"{channel_name} is now LIVE on YouTube!",
                    description=f"{video_title}\n\n[Click here to watch!]({stream_url})",
                    url=stream_url, color=discord.Color.red()
                )
                embed.set_thumbnail(url=f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg")
                embed.set_footer(text="Click the title to watch the stream!")
                bot.loop.create_task(discord_channel.send(content=custom_msg, embed=embed))
        
        return 'OK', 200
    
    return 'OK', 200

# --- RUNNING THE BOT AND SERVER ---

def run_flask():
    """Run Flask webhook server."""
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)

def run_bot():
    """Run Discord bot."""
    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    print("Starting Stream Notification Bot...")
    
    get_twitch_app_access_token()
    
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    print(f"Flask webhook server started on {FLASK_HOST}:{FLASK_PORT}")
    
    run_bot()
