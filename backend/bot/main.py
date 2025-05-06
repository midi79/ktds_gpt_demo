import logging
import json
import requests
from mattermostdriver import Driver
import asyncio
import threading
import time
from urllib.parse import urlparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MattermostBot:
    def __init__(self, 
                 mattermost_url, 
                 bot_token, 
                 backend_url, 
                 team_name=None, 
                 channel_name=None, 
                 bot_username=None):
        """
        Initialize the Mattermost bot with necessary configuration.
        
        Args:
            mattermost_url: URL of the Mattermost server
            bot_token: Bot access token for authentication
            backend_url: URL of the FastAPI backend
            team_name: Optional team name to join
            channel_name: Optional channel name to join
            bot_username: Optional username of the bot account
        """
        self.mattermost_url = mattermost_url
        self.bot_token = bot_token
        self.backend_url = backend_url
        self.team_name = team_name
        self.channel_name = channel_name
        self.bot_username = bot_username
        self.driver = None
        self.event_handler = None
        self.running = False
        self.bot_user_id = None
        self.websocket_thread = None
        
    def connect(self):
        """Connect to the Mattermost server and initialize the driver"""
        logger.info(f"Connecting to Mattermost server at {self.mattermost_url}")
        
        # Parse the URL to get the correct components
        parsed_url = urlparse(self.mattermost_url)
        scheme = parsed_url.scheme or 'http'
        
        # Handle hostname correctly whether netloc is provided or just path
        if parsed_url.netloc:
            hostname = parsed_url.netloc
        else:
            hostname = parsed_url.path
        
        # Remove port from hostname if included
        if ':' in hostname:
            hostname = hostname.split(':')[0]
            
        # Get port from URL or use default
        port = parsed_url.port
        if not port:
            # Common Mattermost ports: 8065 (default), 443 (HTTPS), 80 (HTTP)
            port = 443 if scheme == 'https' else 31492
            
        logger.info(f"Connecting with scheme: {scheme}, hostname: {hostname}, port: {port}")
        
        # Configure the Mattermost driver with more flexible options
        driver_options = {
            'url': hostname,
            'token': self.bot_token,
            'scheme': scheme,
            'port': port,
            'basepath': '/api/v4',
            'verify': False,  # Allow self-signed certificates for testing
            'timeout': 30,    # Increase timeout
        }
        
        logger.info(f"Driver configuration: {driver_options}")
        self.driver = Driver(driver_options)
        
        try:
            # Try to login 
            logger.info("Attempting to login with token...")
            self.driver.login()
            
            # Get the bot's user ID
            self.bot_user_id = self.driver.users.get_user('me')['id']
            logger.info(f"Connected as user ID: {self.bot_user_id}")
            
            # Join the team and channel if specified
            if self.team_name and self.channel_name:
                self._join_team_and_channel()
                
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            raise
            
    def _join_team_and_channel(self):
        """Join the specified team and channel"""
        try:
            # Get all teams and find the specified team
            teams = self.driver.teams.get_teams()
            team_id = None
            
            for team in teams:
                if team['name'] == self.team_name or team['display_name'] == self.team_name:
                    team_id = team['id']
                    break
                    
            if not team_id:
                logger.error(f"Team '{self.team_name}' not found")
                return
                
            # Join the team if not already a member
            my_teams = self.driver.teams.get_user_teams(self.bot_user_id)
            if team_id not in [team['id'] for team in my_teams]:
                self.driver.teams.add_user_to_team(team_id, {'team_id': team_id, 'user_id': self.bot_user_id})
                
            # Get all channels in the team
            logger.info(f"Getting channels for team ID: {team_id}")
            try:
                # Try the method that might exist in newer versions
                channels = self.driver.channels.get_channels_for_team(team_id)
            except AttributeError:
                # Fallback for older versions
                logger.info("Falling back to get_public_channels method")
                try:
                    channels = self.driver.channels.get_public_channels(team_id)
                except AttributeError:
                    # Another fallback - list team channels
                    logger.info("Falling back to get_team_channels")
                    channels = []
                    try:
                        channels = self.driver.channels.get_team_channels(team_id)
                    except AttributeError:
                        logger.error("Could not find a method to list channels")
                        # Just continue with empty channels list
                
            logger.info(f"Found {len(channels)} channels")
            
            channel_id = None
            # Search for the channel by name
            for channel in channels:
                if channel['name'] == self.channel_name:
                    channel_id = channel['id']
                    break
                    
            if not channel_id:
                logger.error(f"Channel '{self.channel_name}' not found in team '{self.team_name}'")
                # Let's list available channels to help the user
                logger.info("Available channels:")
                for channel in channels:
                    logger.info(f" - {channel['name']} (ID: {channel['id']})")
                return
                
            # Join the channel
            logger.info(f"Attempting to join channel {channel_id}")
            
            # Try multiple methods to join the channel
            joined = False
            
            # Method 1: add_channel_member
            try:
                self.driver.channels.add_channel_member(channel_id, {'user_id': self.bot_user_id})
                joined = True
                logger.info("Joined channel using add_channel_member")
            except AttributeError:
                logger.info("add_channel_member not available, trying alternative methods")
            
            # Method 2: add_user
            if not joined:
                try:
                    self.driver.channels.add_user(channel_id, {'user_id': self.bot_user_id})
                    joined = True
                    logger.info("Joined channel using add_user")
                except (AttributeError, Exception) as e:
                    logger.info(f"add_user method failed: {str(e)}")
            
            # Method 3: Direct API call using the base driver
            if not joined:
                try:
                    endpoint = f'/channels/{channel_id}/members'
                    self.driver.client.make_request('post', endpoint, options={'user_id': self.bot_user_id})
                    joined = True
                    logger.info("Joined channel using direct API call")
                except Exception as e:
                    logger.info(f"Direct API call failed: {str(e)}")
            
            # Check if already a member
            if not joined:
                try:
                    # Check if already a member - this might throw an error if not a member
                    member = self.driver.channels.get_channel_member(channel_id, self.bot_user_id)
                    logger.info("Already a member of the channel")
                    joined = True
                except Exception as e:
                    if "not a member" in str(e).lower():
                        logger.error("Failed to join channel and not already a member")
                    else:
                        logger.error(f"Error checking channel membership: {str(e)}")
            
            if joined:
                logger.info(f"Successfully joined team '{self.team_name}' and channel '{self.channel_name}'")
            else:
                logger.error("Could not join channel with any available method")
            
        except Exception as e:
            logger.error(f"Error joining team and channel: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _init_websocket_in_thread(self):
        """Initialize the WebSocket connection in a separate thread"""
        # Create a new event loop for the thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Initialize the WebSocket connection
            self.driver.init_websocket(self._handle_websocket_event)
            
            # Run the event loop until self.running is False
            while self.running:
                loop.run_until_complete(asyncio.sleep(1))
                
        except Exception as e:
            logger.error(f"WebSocket thread error: {str(e)}")
        finally:
            # Clean up the event loop
            loop.close()
            logger.info("WebSocket thread has ended")
    
    def start(self):
        """Start the bot and listen for events"""
        if self.running:
            logger.warning("Bot is already running")
            return
            
        self.running = True
        logger.info("Starting Mattermost bot")
        
        # Start WebSocket in a separate thread
        self.websocket_thread = threading.Thread(target=self._init_websocket_in_thread)
        self.websocket_thread.daemon = True
        self.websocket_thread.start()
        
        # Keep the main thread running
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Shutting down...")
            self.stop()
            
    def stop(self):
        """Stop the bot and disconnect from the server"""
        logger.info("Stopping Mattermost bot")
        self.running = False
        
        if self.driver:
            try:
                if hasattr(self.driver, 'websocket') and self.driver.websocket:
                    self.driver.disconnect()
            except Exception as e:
                logger.error(f"Error during disconnection: {str(e)}")
            self.driver = None
            
        # Wait for the WebSocket thread to finish
        if self.websocket_thread and self.websocket_thread.is_alive():
            self.websocket_thread.join(timeout=5)
            
    def _handle_websocket_event(self, event):
        """
        Handle WebSocket events from Mattermost
        
        Args:
            event: The event received from Mattermost WebSocket
        """
        # Parse the event
        try:
            event_data = json.loads(event)
            event_type = event_data.get('event')
            
            # Handle posted messages
            if event_type == 'posted':
                self._handle_message(event_data)
                
        except json.JSONDecodeError:
            logger.error(f"Failed to parse WebSocket event: {event}")
            
    def _handle_message(self, event_data):
        """
        Handle incoming message events
        
        Args:
            event_data: The event data containing the message
        """
        try:
            post_data = json.loads(event_data.get('data', {}).get('post', '{}'))
            
            # Ignore messages from the bot itself
            if post_data.get('user_id') == self.bot_user_id:
                return
                
            # Get message details
            message = post_data.get('message', '')
            channel_id = post_data.get('channel_id')
            user_id = post_data.get('user_id')
            post_id = post_data.get('id')
            
            # Check if the message is mentioning the bot or is a direct message
            is_direct_channel = self._is_direct_channel(channel_id)
            mentions_bot = f'@{self.bot_username}' in message if self.bot_username else False
            
            # Process the message if it's a direct message or mentions the bot
            if is_direct_channel or mentions_bot:
                # Remove bot mention from the message if present
                if mentions_bot and self.bot_username:
                    message = message.replace(f'@{self.bot_username}', '').strip()
                
                # Process the message and send the response
                self._process_message(message, channel_id, user_id)
                
        except Exception as e:
            logger.error(f"Error handling message: {str(e)}")
            
    def _is_direct_channel(self, channel_id):
        """
        Check if a channel is a direct message channel
        
        Args:
            channel_id: The ID of the channel to check
            
        Returns:
            bool: True if it's a direct message channel, False otherwise
        """
        try:
            channel = self.driver.channels.get_channel(channel_id)
            return channel.get('type') == 'D'
        except Exception:
            return False
            
    def _process_message(self, message, channel_id, user_id):
        """
        Process a message by sending it to the backend and returning the response
        
        Args:
            message: The message text
            channel_id: The ID of the channel where the message was sent
            user_id: The ID of the user who sent the message
        """
        try:
            # Get user info for context
            user = self.driver.users.get_user(user_id)
            username = user.get('username', '')
            
            # Prepare the request to the backend
            request_data = {
                'message': message,
                'user_id': user_id,
                'username': username,
                'channel_id': channel_id
            }
            
            logger.info(f"Sending message to backend: {message}")
            
            # Send the request to the backend
            response = requests.post(
                f"{self.backend_url}/process",
                json=request_data,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                response_data = response.json()
                reply_text = response_data.get('response', 'Sorry, I encountered an error processing your request.')
                
                # Send the response back to Mattermost
                self.driver.posts.create_post({
                    'channel_id': channel_id,
                    'message': reply_text
                })
                
                logger.info(f"Sent response to user {username}: {reply_text[:50]}...")
            else:
                logger.error(f"Backend error: {response.status_code} - {response.text}")
                
                # Send error message back to Mattermost
                self.driver.posts.create_post({
                    'channel_id': channel_id,
                    'message': "Sorry, I encountered an error processing your request. Please try again later."
                })
                
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}")
            
            # Try to send error message back to Mattermost
            try:
                self.driver.posts.create_post({
                    'channel_id': channel_id,
                    'message': "Sorry, I encountered an internal error. Please try again later."
                })
            except:
                logger.error("Failed to send error message to Mattermost")


def main():
    """Main function to run the bot"""
    import os
    from dotenv import load_dotenv
    
    # Load environment variables from .env file
    load_dotenv()
    
    # Get configuration from environment variables
    mattermost_url = os.getenv('MATTERMOST_URL')
    bot_token = os.getenv('MATTERMOST_BOT_TOKEN')
    backend_url = os.getenv('BACKEND_URL')
    team_name = os.getenv('MATTERMOST_TEAM')
    channel_name = os.getenv('MATTERMOST_CHANNEL')
    bot_username = os.getenv('MATTERMOST_BOT_USERNAME')
    
    # Print configuration for debugging (hide token partially)
    token_preview = bot_token[:4] + "..." + bot_token[-4:] if bot_token and len(bot_token) > 8 else "Not set"
    logger.info(f"Configuration loaded:")
    logger.info(f"  Mattermost URL: {mattermost_url}")
    logger.info(f"  Bot Token: {token_preview}")
    logger.info(f"  Backend URL: {backend_url}")
    logger.info(f"  Team: {team_name}")
    logger.info(f"  Channel: {channel_name}")
    logger.info(f"  Bot Username: {bot_username}")
    
    # Validate required configuration
    if not all([mattermost_url, bot_token, backend_url]):
        logger.error("Missing required environment variables. Please check your .env file.")
        return
    
    # Create and start the bot
    bot = MattermostBot(
        mattermost_url=mattermost_url,
        bot_token=bot_token,
        backend_url=backend_url,
        team_name=team_name,
        channel_name=channel_name,
        bot_username=bot_username
    )
    
    try:
        # Connect to Mattermost
        bot.connect()
        
        # Start the bot
        bot.start()
    except Exception as e:
        logger.error(f"Bot error: {str(e)}")
    finally:
        # Check if the bot has a driver before trying to stop
        if hasattr(bot, 'driver') and bot.driver:
            bot.stop()


if __name__ == '__main__':
    main()