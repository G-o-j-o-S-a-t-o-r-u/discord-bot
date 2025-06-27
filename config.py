# config.py (Corrected for Railway and other hosts)
import os

# --- Discord Bot Configuration ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# --- Twitch API Configuration ---
TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')

# --- YouTube API Configuration ---
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

# --- Webhook Security ---
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')

# --- Server Configuration ---
# Use the WEBHOOK_BASE_URL environment variable you will set in the hosting platform's secrets.
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL')

# Use the PORT environment variable provided by the host.
FLASK_PORT = int(os.getenv('PORT', 8080))
FLASK_HOST = '0.0.0.0'

# --- API Endpoints (These are correct) ---
TWITCH_TOKEN_URL = 'https://id.twitch.tv/oauth2/token'
TWITCH_USERS_URL = 'https://api.twitch.tv/helix/users'
TWITCH_EVENTSUB_URL = 'https://api.twitch.tv/helix/eventsub/subscriptions'
YOUTUBE_CHANNELS_URL = 'https://www.googleapis.com/youtube/v3/channels'
YOUTUBE_PUBSUB_URL = 'https://pubsubhubbub.appspot.com/subscribe'
