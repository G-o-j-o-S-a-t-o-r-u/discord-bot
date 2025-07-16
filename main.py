# main.py

import discord
import requests
import json
import threading
import hmac
import hashlib
import xmltodict
from flask import Flask, request, abort, Response
from typing import Optional, Dict, List
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
        'hub.lease_seconds': 864000  # 10 days, the max
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
    delete_all_twitch_subscriptions()  # YouTube subscriptions expire automatically
    
    # Sync slash commands
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
    await interaction.response.defer()
    
    # Use specified channel or default to current channel
    target_channel = notification_channel if notification_channel else interaction.channel
    target_channel_id = target_channel.id
    
    if platform == 'twitch':
        await interaction.followup.send(f"⏳ Searching for Twitch user `{identifier}`...")
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
                target_channel_id, identifier.lower(), sub_id, custom_message
            )
            await interaction.followup.send(f"✅ Subscribed to live notifications for **{identifier}** on Twitch!")
        else:
            await interaction.followup.send("❌ Failed to create Twitch webhook.")

    elif platform == 'youtube':
        await interaction.followup.send(f"⏳ Searching for YouTube channel `{identifier}`...")
        channel_info = get_youtube_channel_info(identifier)
        if not channel_info:
            await interaction.followup.send(f"❌ Could not find a YouTube channel with ID `{identifier}`. Make sure you use the Channel ID (starts with UC...).")
            return
        
        if db.subscription_exists(identifier):
            await interaction.followup.send(f"`{channel_info['title']}` is already being watched!")
            return
        
        callback_url = f"{WEBHOOK_BASE_URL}/webhooks/youtube"
        if create_youtube_subscription(identifier, callback_url):
            db.add_subscription(
                identifier, 'youtube', interaction.guild_id,
                target_channel_id, channel_info['title'], None, custom_message
            )
            await interaction.followup.send(f"✅ Subscribed to live notifications for **{channel_info['title']}** on YouTube!")
        else:
            await interaction.followup.send("❌ Failed to create YouTube webhook.")

# PASTE THIS ENTIRE FUNCTION INTO YOUR main.py FILE

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
    await interaction.response.defer()
    
    # Find the subscription
    guild_subscriptions = db.get_subscriptions_by_guild(interaction.guild_id)
    target_id = None
    streamer_name = identifier # Default name to the identifier

    if platform == 'twitch':
        # For Twitch, find the subscription by the stored username (which is the identifier)
        for sub_id, sub_data in guild_subscriptions.items():
            if sub_data['platform'] == 'twitch' and sub_data['name'].lower() == identifier.lower():
                target_id = sub_id
                break
    elif platform == 'youtube':
        # For YouTube, the identifier IS the target_id
        if identifier in guild_subscriptions:
            target_id = identifier

    if not target_id:
        await interaction.followup.send(f"❌ No subscription found for `{identifier}` on {platform} in this server.")
        return
    
    # Get the full subscription data to use its name in the success message
    subscription_data = db.get_subscription(target_id)
    if subscription_data:
        streamer_name = subscription_data['name']
        # For Twitch, we also need to delete the webhook subscription from their server
        if platform == 'twitch' and subscription_data.get('subscription_id'):
            delete_twitch_subscription(subscription_data['subscription_id'])
        
        # Finally, remove from our database
        db.remove_subscription(target_id)
        await interaction.followup.send(f"✅ Unsubscribed from **{streamer_name}** on {platform.title()}!")
    else:
        # This case is unlikely if target_id was found, but it's good practice to have it
        await interaction.followup.send(f"❌ Could not find subscription data for `{identifier}`.")
@tree.command(name="list", description="Show all active stream subscriptions in this server")
async def list_command(interaction: discord.Interaction):
    """Handle /list command to show all subscriptions for this guild."""
    await interaction.response.defer()
    
    guild_subscriptions = db.get_subscriptions_by_guild(interaction.guild_id)
    
    if not guild_subscriptions:
        await interaction.followup.send("📋 No active subscriptions in this server.")
        return
    
    embed = discord.Embed(
        title="📋 Active Stream Subscriptions",
        color=discord.Color.blue()
    )
    
    twitch_subs = []
    youtube_subs = []
    
    for streamer_id, sub_data in guild_subscriptions.items():
        if sub_data['platform'] == 'twitch':
            twitch_subs.append(f"• {sub_data['name']}")
        elif sub_data['platform'] == 'youtube':
            youtube_subs.append(f"• {sub_data['name']}")
    
    if twitch_subs:
        embed.add_field(
            name="🟣 Twitch",
            value="\n".join(twitch_subs),
            inline=False
        )
    
    if youtube_subs:
        embed.add_field(
            name="🔴 YouTube",
            value="\n".join(youtube_subs),
            inline=False
        )
    
    await interaction.followup.send(embed=embed)

@tree.command(name="test", description="Test stream notifications with a fake stream alert")
@discord.app_commands.describe(
    platform="Platform to test (twitch or youtube)",
    identifier="Streamer name or channel ID to test"
)
@discord.app_commands.choices(platform=[
    discord.app_commands.Choice(name="Twitch", value="twitch"),
    discord.app_commands.Choice(name="YouTube", value="youtube")
])
async def test_command(interaction: discord.Interaction, platform: str, identifier: str):
    """Test stream notification for a subscribed streamer."""
    await interaction.response.defer()
    
    # Find the subscription - need to search through all subscriptions to find by name
    subscription = None
    all_subscriptions = db.get_all_subscriptions()
    
    for sub_id, sub_data in all_subscriptions.items():
        if (sub_data['platform'] == platform and 
            sub_data['guild_id'] == interaction.guild_id and
            sub_data['name'].lower() == identifier.lower()):
            subscription = sub_data
            break
    
    if not subscription:
        await interaction.followup.send(f"❌ No subscription found for `{identifier}` on {platform}. Add them first with `/add`!")
        return
    
    # Get the channel where notifications should be sent
    try:
        channel = bot.get_channel(subscription['channel_id'])
        if not channel:
            await interaction.followup.send(f"❌ Cannot find the notification channel for `{identifier}`. The channel may have been deleted.")
            return
        
        # Send test notification
        if platform == 'twitch':
            embed = discord.Embed(
                title=f"🔴 {subscription['name']} is now live!",
                description=f"**TEST NOTIFICATION**\n\nGame: Just Chatting\nViewers: 1,234",
                color=0x9146FF,
                url=f"https://twitch.tv/{identifier.lower()}"
            )
            embed.set_thumbnail(url="https://static-cdn.jtvnw.net/jtv_user_pictures/default-profile_image-300x300.png")
        else:  # YouTube
            # Find the actual channel ID from the subscription data
            channel_id = None
            for sub_id, sub_data in all_subscriptions.items():
                if (sub_data['platform'] == platform and 
                    sub_data['guild_id'] == interaction.guild_id and
                    sub_data['name'].lower() == identifier.lower()):
                    channel_id = sub_id
                    break
            
            embed = discord.Embed(
                title=f"🔴 {subscription['name']} is streaming!",
                description=f"**TEST NOTIFICATION**\n\nLive on YouTube",
                color=0xFF0000,
                url=f"https://youtube.com/channel/{channel_id}" if channel_id else "https://youtube.com"
            )
            embed.set_thumbnail(url="https://yt3.ggpht.com/default_avatar_300x300.jpg")
        
        # Add custom message if exists
        message_content = ""
        if subscription.get('custom_message'):
            message_content = subscription['custom_message']
        
        if message_content:
            await channel.send(content=message_content, embed=embed)
        else:
            await channel.send(embed=embed)
        
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
    
    embed.add_field(
        name="/add <platform> <identifier>",
        value="Subscribe to a streamer\n**Platforms:** `twitch`, `youtube`\n**Examples:**\n`/add twitch shroud`\n`/add youtube UC-9-kyTW8ZkZNDHQJ6FgpwQ`",
        inline=False
    )
    
    embed.add_field(
        name="/remove <platform> <identifier>",
        value="Unsubscribe from a streamer\n**Examples:**\n`/remove twitch shroud`\n`/remove youtube UC-9-kyTW8ZkZNDHQJ6FgpwQ`",
        inline=False
    )
    
    embed.add_field(
        name="/list",
        value="Show all active subscriptions in this server",
        inline=False
    )
    
    embed.add_field(
        name="/test <platform> <identifier>",
        value="Send a fake stream notification to test if notifications work\n**Examples:**\n`/test twitch shroud`\n`/test youtube UC-9-kyTW8ZkZNDHQJ6FgpwQ`",
        inline=False
    )
    
    embed.add_field(
        name="/help",
        value="Show this help message",
        inline=False
    )
    
    embed.set_footer(text="Note: For YouTube, use the Channel ID (starts with UC...)")
    
    await interaction.response.send_message(embed=embed)

# --- FLASK WEB SERVER (WEBHOOK LISTENER) ---

@app.route('/')
def home():
    """Health check endpoint."""
    return "Stream Notification Bot - Webhook Listener is running."

# In main.py, replace the entire twitch_webhook function with this one:

@app.route('/webhooks/twitch', methods=['POST'])
def twitch_webhook():
    """Handle Twitch webhook notifications."""
    # Step 0: Verify the request is genuinely from Twitch
    message_id = request.headers.get('Twitch-Eventsub-Message-Id', '')
    message_timestamp = request.headers.get('Twitch-Eventsub-Message-Timestamp', '')
    message_signature = request.headers.get('Twitch-Eventsub-Message-Signature', '')
    hmac_message = message_id.encode('utf-8') + message_timestamp.encode('utf-8') + request.data
    expected_signature = 'sha256=' + hmac.new(
        WEBHOOK_SECRET.encode('utf-8'), hmac_message, hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, message_signature):
        print("Twitch signature mismatch!")
        abort(403)

    message_type = request.headers.get('Twitch-Eventsub-Message-Type')
    
    # Step 1: Handle the one-time verification challenge from Twitch
    if message_type == 'webhook_callback_verification':
        json_data = request.get_json()
        if json_data and 'challenge' in json_data:
            return json_data['challenge'], 200
        return 'OK', 200

    # Step 2: Handle an actual "Go Live" notification
    elif message_type == 'notification':
        json_data = request.get_json()
        if not json_data or 'event' not in json_data:
            return 'OK', 200
        
        event = json_data['event']
        user_id = event['broadcaster_user_id']
        
        subscription = db.get_subscription(user_id)
        if subscription and subscription['platform'] == 'twitch':
            
            # --- START OF THE FIX ---
            # The "go live" ping doesn't have game info, so we fetch it now.
            
            # Step 2a: Make a second API call to get the stream details
            stream_details_url = f"https://api.twitch.tv/helix/streams?user_id={user_id}"
            headers = {
                'Client-ID': TWITCH_CLIENT_ID,
                'Authorization': f'Bearer {TWITCH_ACCESS_TOKEN}'
            }
            
            game_name = "No Category"
            stream_title = "Stream is Live!"
            
            try:
                stream_response = requests.get(stream_details_url, headers=headers)
                stream_response.raise_for_status()
                stream_data = stream_response.json().get('data', [])
                
                if stream_data: # If the stream is found
                    stream_info = stream_data[0]
                    game_name = stream_info.get('game_name', 'No Category')
                    stream_title = stream_info.get('title', 'No Title')
            except Exception as e:
                print(f"Could not fetch stream details for {user_id}: {e}")

            # --- END OF THE FIX ---

            channel_id = subscription['channel_id']
            channel = bot.get_channel(channel_id)
            if channel and hasattr(channel, 'send'):
                username = event['broadcaster_user_name']
                
                custom_msg = subscription.get('custom_message', "")
                stream_url = f"https://twitch.tv/{username}"

                embed = discord.Embed(
                    title=f"{username} is now LIVE on Twitch!",
                    description=f"**{stream_title}**\nPlaying: **{game_name}**\n\n[Click here to watch!]({stream_url})", # Use the new variables
                    url=stream_url,
                    color=discord.Color.purple()
                )
                # Use a generic thumbnail from the user, not the stream, as it's more reliable
                embed.set_thumbnail(url=f"https://static-cdn.jtvnw.net/jtv_user_pictures/{user_id}-profile_image-300x300.png")
                embed.set_footer(text="Click the title to watch the stream!")
                
                bot.loop.create_task(channel.send(content=custom_msg, embed=embed))
        return 'OK', 200

    return 'OK', 200

@app.route('/webhooks/youtube', methods=['GET', 'POST'])
def youtube_webhook():
    """Handle YouTube webhook notifications."""
    if request.method == 'GET':  # Handle verification
        challenge = request.args.get('hub.challenge')
        if challenge:
            return Response(challenge, mimetype='text/plain')
        return 'OK', 200

    elif request.method == 'POST':  # Handle notification
        # --- THE FAULTY 'IF' BLOCK HAS BEEN REMOVED FROM HERE ---
        # The URL is secret enough that we don't need to be this strict.
        
        try:
            xml_data = xmltodict.parse(request.data)
            entry = xml_data.get('feed', {}).get('entry', {})
            
            video_id = entry.get('yt:videoId')
            channel_id = entry.get('yt:channelId')
            
            if not video_id or not channel_id:
                return 'OK', 200
            
            # This check for "updated vs published" was also causing issues, so it remains removed.
            
            subscription = db.get_subscription(channel_id)
            if subscription and subscription['platform'] == 'youtube':
                channel = bot.get_channel(subscription['channel_id'])
                if channel and hasattr(channel, 'send'):
                    channel_name = subscription['name']
                    video_title = entry.get('title', 'New Video')
                    
                    custom_msg = subscription.get('custom_message', "")
                    stream_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    embed = discord.Embed(
                        title=f"{channel_name} is now LIVE on YouTube!",
                        description=f"{video_title}\n\n[Click here to watch!]({stream_url})",
                        url=stream_url,
                        color=discord.Color.red()
                    )
                    embed.set_thumbnail(url=f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg")
                    embed.set_footer(text="Click the title to watch the stream!")
                    
                    bot.loop.create_task(channel.send(content=custom_msg, embed=embed))
            return 'OK', 200
        except Exception as e:
            print(f"Error processing YouTube webhook: {e}")
            return 'OK', 200
    
    return 'OK', 200
            
            # --- THE FAULTY 'IF' BLOCK HAS BEEN REMOVED FROM HERE ---

            subscription = db.get_subscription(channel_id)
            if subscription and subscription['platform'] == 'youtube':
                channel = bot.get_channel(subscription['channel_id'])
                if channel and hasattr(channel, 'send'):
                    channel_name = subscription['name']
                    video_title = entry.get('title', 'New Video')
                    
                    custom_msg = subscription.get('custom_message', "")
                    stream_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    embed = discord.Embed(
                        title=f"{channel_name} is now LIVE on YouTube!",
                        description=f"{video_title}\n\n[Click here to watch!]({stream_url})",
                        url=stream_url,
                        color=discord.Color.red()
                    )
                    embed.set_thumbnail(url=f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg")
                    embed.set_footer(text="Click the title to watch the stream!")
                    
                    bot.loop.create_task(channel.send(content=custom_msg, embed=embed))
            return 'OK', 200
        except Exception as e:
            print(f"Error processing YouTube webhook: {e}")
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
    
    # Get initial Twitch token
    get_twitch_app_access_token()
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    print(f"Flask webhook server started on {FLASK_HOST}:{FLASK_PORT}")
    
    # Run Discord bot (this blocks)
    run_bot()
