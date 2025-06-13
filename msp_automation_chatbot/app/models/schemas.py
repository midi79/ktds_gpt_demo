"""Pydantic models for request/response schemas."""
from pydantic import BaseModel
from typing import Optional

class MattermostResponse(BaseModel):
    """Response model for Mattermost."""
    text: str
    response_type: str = "in_channel"

class WebhookRequest(BaseModel):
    """Request model for Mattermost webhook."""
    token: str
    team_id: str
    channel_id: str
    user_id: str
    user_name: str
    text: str
    command: str
    response_url: Optional[str] = None
    trigger_id: Optional[str] = None
    team_domain: Optional[str] = None
    channel_name: Optional[str] = None