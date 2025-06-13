"""Command service for handling predefined commands."""
from typing import Optional

class CommandService:
    """Service for processing predefined commands."""
    
    @staticmethod
    def process_command(command: str) -> Optional[str]:
        """Process predefined commands and return a response if matched."""
        clean_command = command.strip()
        
        if clean_command.startswith("help"):
            return """
Available commands:
- help: Show this help message
- ping: Check if the bot is online
- status: Get system status
- metric [query]: Execute a PromQL query against Prometheus (table format)
- metric-text [query]: Execute a PromQL query against Prometheus (text format)
- kubectl [command]: Execute a kubectl command against Kubernetes (table format)
- kubectl-yaml [command]: Execute a kubectl command against Kubernetes (yaml format)
- query [natural language]: Generate and execute PromQL or kubectl commands from natural language
- query-text [natural language]: Same as query but with text formatting
- any other text: Will be processed by ChatGPT and automatically routed to appropriate service
"""
        elif clean_command.startswith("ping"):
            return "Pong! I'm online and ready to help with Prometheus and Kubernetes queries."
        elif clean_command.startswith("status"):
            return "All systems operational. Prometheus and Kubernetes integrations ready."
            
        return None