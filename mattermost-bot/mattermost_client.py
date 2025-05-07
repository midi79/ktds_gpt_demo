import os
import asyncio
from typing import Dict, Any, List, Optional
import httpx
import uvicorn
from fastapi import FastAPI, Request, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import logging
from dotenv import load_dotenv
from websocket_client import MattermostWebSocketClient

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Environment variables
MATTERMOST_URL = os.getenv("MATTERMOST_URL", "https://your-mattermost-instance.com")
MATTERMOST_BOT_TOKEN = os.getenv("MATTERMOST_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4-turbo")

# Initialize FastAPI app
app = FastAPI(title="Mattermost Bot Backend")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class MattermostRequest(BaseModel):
    token: str
    team_id: str
    team_domain: str
    channel_id: str
    channel_name: str
    user_id: str
    user_name: str
    post_id: str
    text: str
    trigger_word: Optional[str] = None
    file_ids: Optional[List[str]] = None
    
class MattermostResponse(BaseModel):
    text: str
    response_type: str = "in_channel"  # or "ephemeral" for private responses
    props: Dict[str, Any] = Field(default_factory=dict)

# Predefined commands and their handlers
class CommandService:
    @staticmethod
    def help_command() -> str:
        """Return help information about available commands"""
        return """
Available commands:
- help: Show this help message
- status: Check system status
- weather <location>: Get weather information for a location
        """
    
    @staticmethod
    def status_command() -> str:
        """Return system status"""
        return "All systems operational. Bot is running correctly."
    
    @staticmethod
    def weather_command(location: str) -> str:
        """Simulated weather command - in production, would call a weather API"""
        # In a real implementation, you would call a weather API here
        return f"Weather information for {location}: Simulated weather data (replace with actual API call)"
        
    # Add more commands as needed

# Create a client for making HTTP requests
class APIClient:
    def __init__(self):
        self.openai_client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            timeout=60.0
        )
        self.mattermost_client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {MATTERMOST_BOT_TOKEN}"},
            timeout=30.0
        )
        
    async def close(self):
        await self.openai_client.aclose()
        await self.mattermost_client.aclose()
        
    async def call_openai(self, message: str) -> str:
        """Call OpenAI API to process a message"""
        try:
            response = await self.openai_client.post(
                "https://api.openai.com/v1/chat/completions",
                json={
                    "model": OPENAI_MODEL,
                    "messages": [{"role": "user", "content": message}],
                    "max_tokens": 1000
                }
            )
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Error calling OpenAI API: {e}")
            return f"Sorry, I encountered an error when processing your request: {str(e)}"
            
    async def post_to_mattermost(self, channel_id: str, message: str) -> Dict[str, Any]:
        """Post a message to a Mattermost channel"""
        try:
            response = await self.mattermost_client.post(
                f"{MATTERMOST_URL}/api/v4/posts",
                json={
                    "channel_id": channel_id,
                    "message": message
                }
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error posting to Mattermost: {e}")
            return {"error": str(e)}

# Dependency to get API client
async def get_api_client():
    client = APIClient()
    try:
        yield client
    finally:
        await client.close()

# Process incoming messages
async def process_message(data: MattermostRequest, client: APIClient) -> str:
    """Process incoming message and return appropriate response"""
    text = data.text.strip()
    
    # Extract command and arguments
    parts = text.split(maxsplit=1)
    command = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    
    # Handle predefined commands
    if command == "help":
        return CommandService.help_command()
    elif command == "status":
        return CommandService.status_command()
    elif command == "weather":
        return CommandService.weather_command(args)
    
    # If not a predefined command, forward to OpenAI
    logger.info(f"Forwarding message to OpenAI: {text}")
    return await client.call_openai(text)

# API endpoint to handle incoming messages from Mattermost
@app.post("/bot/receive", response_model=MattermostResponse)
async def receive_message(
    request: Request,
    data: MattermostRequest,
    client: APIClient = Depends(get_api_client)
):
    # Verify request is from Mattermost (implement proper verification in production)
    # In production, add proper token verification here
    
    # Process the message
    response_text = await process_message(data, client)
    
    # Return response to Mattermost
    return MattermostResponse(
        text=response_text,
        response_type="in_channel"  # Makes the response visible to all in the channel
    )

# Background task to handle asynchronous processing
@app.post("/bot/async", status_code=202)
async def async_receive(
    data: MattermostRequest,
    background_tasks: BackgroundTasks,
    client: APIClient = Depends(get_api_client)
):
    # For longer running tasks to avoid timeout issues
    async def process_and_respond():
        response = await process_message(data, client)
        await client.post_to_mattermost(data.channel_id, response)
    
    background_tasks.add_task(process_and_respond)
    return {"status": "processing"}

# Global WebSocket client
ws_client = None

@app.get("/health")
def health_check():
    """Simple health check endpoint"""
    return {"status": "healthy"}

# WebSocket message handler that will be called when messages are received
async def handle_mattermost_message(message_data: Dict[str, Any]):
    """Handle incoming messages from Mattermost WebSocket
    
    Args:
        message_data: Message data from WebSocket
    """
    logger.info(f"Received message via WebSocket: {message_data}")
    
    # Create API client to process the message
    client = APIClient()
    try:
        # Process the message
        text = message_data.get("text", "").strip()
        
        # Create a MattermostRequest object from the WebSocket data
        request_data = MattermostRequest(
            token="",  # No token needed as we are already authenticated
            team_id=message_data.get("team_id", ""),
            team_domain="",  # May not be available from WebSocket
            channel_id=message_data.get("channel_id", ""),
            channel_name="",  # May not be available from WebSocket
            user_id=message_data.get("user_id", ""),
            user_name="",  # May not be available from WebSocket
            post_id=message_data.get("post_id", ""),
            text=text,
            trigger_word="",  # Not applicable for WebSocket
            file_ids=[]  # May not be available from WebSocket
        )
        
        # Extract mention of the bot from the text
        # Format is typically "@bot_name message_text"
        parts = text.split(maxsplit=1)
        if len(parts) > 1 and parts[0].startswith("@"):
            # Remove the bot mention from the text
            actual_text = parts[1]
            response_text = await process_message(
                MattermostRequest(**{**request_data.dict(), "text": actual_text}), 
                client
            )
        else:
            # If no clear mention format, process the whole text
            response_text = await process_message(request_data, client)
        
        # Send response back to Mattermost
        await client.post_to_mattermost(message_data.get("channel_id", ""), response_text)
    finally:
        await client.close()

# Startup event to initialize WebSocket client
@app.on_event("startup")
async def startup_event():
    global ws_client
    
    # Initialize WebSocket client
    ws_client = MattermostWebSocketClient(
        message_handler=handle_mattermost_message
    )
    
    # Start WebSocket client in the background
    asyncio.create_task(ws_client.start())
    logger.info("Started WebSocket client for Mattermost")

# Shutdown event to clean up WebSocket client
@app.on_event("shutdown")
async def shutdown_event():
    global ws_client
    
    if ws_client:
        await ws_client.stop()
        logger.info("Stopped WebSocket client for Mattermost")

if __name__ == "__main__":
    # Run the server
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)