# database.py
import json
import os
from typing import Dict, Optional, List

class StreamDatabase:
    """Simple file-based database for storing stream subscriptions."""
    
    def __init__(self, db_file: str = 'streams.json'):
        self.db_file = db_file
        self.data = self._load_data()
    
    def _load_data(self) -> Dict:
        """Load data from JSON file or create empty structure."""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading database: {e}")
                return {}
        return {}
    
    def _save_data(self) -> None:
        """Save data to JSON file."""
        try:
            with open(self.db_file, 'w') as f:
                json.dump(self.data, f, indent=2)
        except IOError as e:
            print(f"Error saving database: {e}")
    
    def add_subscription(self, streamer_id: str, platform: str, guild_id: int, 
                        channel_id: int, name: str, subscription_id: Optional[str] = None, 
                        custom_message: Optional[str] = None) -> None:
        """Add a new stream subscription."""
        self.data[streamer_id] = {
            'platform': platform,
            'guild_id': guild_id,
            'channel_id': channel_id,
            'name': name,
            'subscription_id': subscription_id,
            'custom_message': custom_message
        }
        self._save_data()
    
    def remove_subscription(self, streamer_id: str) -> Optional[Dict]:
        """Remove a stream subscription and return the removed data."""
        removed = self.data.pop(streamer_id, None)
        if removed:
            self._save_data()
        return removed
    
    def get_subscription(self, streamer_id: str) -> Optional[Dict]:
        """Get a specific subscription."""
        return self.data.get(streamer_id)
    
    def get_subscriptions_by_guild(self, guild_id: int) -> Dict[str, Dict]:
        """Get all subscriptions for a specific Discord guild."""
        return {
            streamer_id: data for streamer_id, data in self.data.items()
            if data['guild_id'] == guild_id
        }
    
    def get_all_subscriptions(self) -> Dict[str, Dict]:
        """Get all subscriptions."""
        return self.data.copy()
    
    def subscription_exists(self, streamer_id: str) -> bool:
        """Check if a subscription exists."""
        return streamer_id in self.data
    
    def get_subscriptions_by_platform(self, platform: str) -> Dict[str, Dict]:
        """Get all subscriptions for a specific platform."""
        return {
            streamer_id: data for streamer_id, data in self.data.items()
            if data['platform'] == platform
        }
