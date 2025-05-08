import os
import asyncio
from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import JSONResponse
import httpx
import uvicorn
import time
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Mattermost ChatGPT Integration")

# Environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MATTERMOST_URL = os.getenv("MATTERMOST_URL")
MATTERMOST_BOT_TOKEN = os.getenv("MATTERMOST_BOT_TOKEN")
MATTERMOST_WEBHOOK_TOKEN = os.getenv("MATTERMOST_WEBHOOK_TOKEN")  # For verification

# Response model for Mattermost
class MattermostResponse(BaseModel):
    text: str
    response_type: str = "in_channel"  # "in_channel" or "ephemeral"
    
# Service for handling predefined commands
class CommandService:
    @staticmethod
    def process_command(command: str) -> Optional[str]:
        """Process predefined commands and return a response if matched."""
        # Strip the command if needed
        clean_command = command.strip()
        
        # Check for predefined commands
        if clean_command.startswith("help"):
            return """
Available commands:
- help: Show this help message
- ping: Check if the bot is online
- status: Get system status
- any other text: Will be processed by ChatGPT
"""
        elif clean_command.startswith("ping"):
            return "Pong! I'm online and ready to help."
        elif clean_command.startswith("status"):
            return "All systems operational. Ready to process your requests."
            
        # If no predefined command matches, return None so it can be processed by ChatGPT
        return None

# Service for ChatGPT integration
class ChatGPTService:
    # Class variable to track requests and implement rate limiting
    request_count = 0
    max_retries = 3
    
    @staticmethod
    async def get_response(message: str) -> str:
        """Get response from ChatGPT with retry logic and rate limiting."""
        if not OPENAI_API_KEY:
            return "Error: OpenAI API key is not configured. Please contact the administrator."
            
        logger.info(f"Sending message to ChatGPT: {message}")
        
        # Increment request counter (simple rate limiting)
        ChatGPTService.request_count += 1
        
        # Basic rate limiting - skip if too many recent requests
        if ChatGPTService.request_count > 45:  # Adjust based on your rate limits
            logger.warning("Rate limit preemptively applied")
            ChatGPTService.request_count = max(0, ChatGPTService.request_count - 5)  # Decay mechanism
            return "I'm getting too many requests right now. Please try again in a few moments."
        
        # Implement retry with exponential backoff
        retry_delay = 1  # Starting delay in seconds
        
        for attempt in range(ChatGPTService.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENAI_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "gpt-4o-mini",  # Using a more available model as backup
                            "messages": [
                                {"role": "system", "content": "You are a helpful assistant integrated with Mattermost. Keep responses concise and under 2000 characters."},
                                {"role": "user", "content": message}
                            ],
                            "temperature": 0.7,
                            "max_tokens": 1000,  # Limit token usage
                        },
                        timeout=30.0
                    )
                    
                    # If we get here, the request succeeded
                    response.raise_for_status()
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Too Many Requests
                    if attempt < ChatGPTService.max_retries - 1:
                        logger.warning(f"Rate limit hit, retrying in {retry_delay} seconds (attempt {attempt+1}/{ChatGPTService.max_retries})")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        logger.error("Rate limit persisted after max retries")
                        return "I'm currently experiencing high demand. Please try again in a few minutes."
                else:
                    logger.error(f"HTTP error from OpenAI API: {e.response.status_code}")
                    return f"Sorry, there was an issue with the AI service (HTTP {e.response.status_code}). Please try again later."
                    
            except httpx.RequestError as e:
                logger.error(f"Request error connecting to OpenAI: {str(e)}")
                return "Sorry, I couldn't connect to the AI service. Please check your internet connection and try again."
                
            except Exception as e:
                logger.error(f"Unexpected error with ChatGPT: {str(e)}")
                return "Sorry, an unexpected error occurred. Please try again with a simpler question."

# Service for sending messages back to Mattermost
class MattermostService:
    @staticmethod
    async def send_response(channel_id: str, message: str) -> None:
        """Send a response back to Mattermost."""
        if not MATTERMOST_URL or not MATTERMOST_BOT_TOKEN:
            raise ValueError("Mattermost URL or token is not set")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{MATTERMOST_URL}/api/v4/posts",
                    headers={
                        "Authorization": f"Bearer {MATTERMOST_BOT_TOKEN}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "channel_id": channel_id,
                        "message": message
                    },
                    timeout=10.0
                )
                
                response.raise_for_status()
                logger.info(f"Message sent to Mattermost channel {channel_id}")
                
        except Exception as e:
            logger.error(f"Error sending message to Mattermost: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error sending message to Mattermost: {str(e)}")

@app.post("/webhook")
async def mattermost_webhook(
    token: str = Form(...),
    team_id: str = Form(...),
    channel_id: str = Form(...),
    user_id: str = Form(...),
    user_name: str = Form(...),
    text: str = Form(...),
    command: str = Form(...),
    response_url: Optional[str] = Form(None),
    trigger_id: Optional[str] = Form(None),
    team_domain: Optional[str] = Form(None),
    channel_name: Optional[str] = Form(None)
):
    """Handle incoming slash commands from Mattermost."""
    # Verify the token
    if MATTERMOST_WEBHOOK_TOKEN and token != MATTERMOST_WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    logger.info(f"Received slash command: {command} with text: {text} from user: {user_name}")
    
    # First send an immediate response to acknowledge receipt
    # This prevents Mattermost from timing out (it expects a response within 3000ms)
    if text.lower() != "help" and text.lower() != "ping" and text.lower() != "status":
        # For longer queries that might take time, acknowledge receipt immediately
        # We'll use a background task to send the actual response
        asyncio.create_task(process_and_respond_later(text, channel_id, user_name, response_url))
        return MattermostResponse(
            text="Processing your request... I'll respond shortly.",
            response_type="ephemeral"  # Only visible to the requesting user
        )
    
    # For quick commands, process immediately
    command_service = CommandService()
    response = command_service.process_command(text)
    
    # If it's a quick command that wasn't matched, use ChatGPT
    if response is None:
        chatgpt_service = ChatGPTService()
        response = await chatgpt_service.get_response(text)
    
    # Return the response directly to Mattermost
    return MattermostResponse(text=response)

async def process_and_respond_later(text: str, channel_id: str, user_name: str, response_url: str):
    """Process a request in the background and send response when ready."""
    try:
        # Get response from ChatGPT
        chatgpt_service = ChatGPTService()
        response = await chatgpt_service.get_response(text)
        
        # Format response
        formatted_response = f"@{user_name} asked: \"{text}\"\n\n{response}"
        
        # Send response back to Mattermost
        if response_url:
            # Use the response_url if available (preferred method)
            async with httpx.AsyncClient() as client:
                await client.post(
                    response_url,
                    json={"text": formatted_response, "response_type": "in_channel"},
                    timeout=10.0
                )
        else:
            # Fall back to using the Mattermost API
            mattermost_service = MattermostService()
            await mattermost_service.send_response(channel_id, formatted_response)
            
    except Exception as e:
        logger.error(f"Error in background processing: {str(e)}")
        # Send error message
        try:
            if response_url:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        response_url,
                        json={"text": f"Sorry, I encountered an error: {str(e)}", "response_type": "ephemeral"},
                        timeout=10.0
                    )
            else:
                mattermost_service = MattermostService()
                await mattermost_service.send_response(
                    channel_id, 
                    f"@{user_name} I encountered an error processing your request: {str(e)}"
                )
        except Exception as inner_e:
            logger.error(f"Failed to send error message: {str(inner_e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8999))
    uvicorn.run("main:app", host="localhost", port=port, reload=True)