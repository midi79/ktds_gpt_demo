"""Configuration management for the application."""
import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Application configuration."""
    
    # OpenAI Configuration
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    # Mattermost Configuration
    MATTERMOST_URL: str = os.getenv("MATTERMOST_URL", "")
    MATTERMOST_BOT_TOKEN: str = os.getenv("MATTERMOST_BOT_TOKEN", "")
    MATTERMOST_WEBHOOK_TOKEN: str = os.getenv("MATTERMOST_WEBHOOK_TOKEN", "")
    
    # Prometheus Configuration
    PROMETHEUS_URL: str = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
    
    # Kubernetes Configuration
    KUBERNETES_CONFIG_PATH: Optional[str] = os.getenv("KUBERNETES_CONFIG_PATH")
    ENABLE_KUBECTL_SUBPROCESS: bool = os.getenv("ENABLE_KUBECTL_SUBPROCESS", "false").lower() == "true"
    KUBECTL_PATH: str = os.getenv("KUBECTL_PATH", "kubectl")
    
    # Prefect Configuration
    PREFECT_API_URL: str = os.getenv("PREFECT_API_URL", "http://localhost:4200/api")
    
    # Application Configuration
    PORT: int = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def validate(cls) -> None:
        """Validate required configuration."""
        required_vars = {
            "OPENAI_API_KEY": cls.OPENAI_API_KEY,
            "MATTERMOST_URL": cls.MATTERMOST_URL,
            "MATTERMOST_BOT_TOKEN": cls.MATTERMOST_BOT_TOKEN
        }
        
        missing = [key for key, value in required_vars.items() if not value]
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

config = Config()