"""Mattermost service for sending messages."""
import logging
import httpx
from fastapi import HTTPException

from app.config import config

logger = logging.getLogger(__name__)

class MattermostService:
    """Service for interacting with Mattermost."""
    
    @staticmethod
    async def send_response(channel_id: str, message: str) -> None:
        """Send a response back to Mattermost."""
        if not config.MATTERMOST_URL or not config.MATTERMOST_BOT_TOKEN:
            raise ValueError("Mattermost URL or token is not set")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{config.MATTERMOST_URL}/api/v4/posts",
                    headers={
                        "Authorization": f"Bearer {config.MATTERMOST_BOT_TOKEN}",
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