import logging
import os
from typing import Dict, Any, Optional, List
import openai
from fastapi import FastAPI, HTTPException, Body, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load API keys and configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-o4-mini")
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are a helpful assistant.")

# Configure OpenAI client
openai.api_key = OPENAI_API_KEY

# Define request and response models
class MessageRequest(BaseModel):
    message: str
    user_id: str
    username: str
    channel_id: str

class MessageResponse(BaseModel):
    response: str
    source: str  # "command" or "chatgpt"

# Initialize FastAPI app
app = FastAPI(title="Mattermost Chat Bot Backend")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dictionary of command handlers
command_handlers = {}

# Command registry decorator
def register_command(command_name: str):
    """
    Decorator to register command handlers
    
    Args:
        command_name: The command name to register
    """
    def decorator(func):
        command_handlers[command_name] = func
        return func
    return decorator

# Command parsing utility
def parse_command(message: str) -> Optional[tuple]:
    """
    Parse a message to check if it's a command
    
    Args:
        message: The message to parse
        
    Returns:
        tuple: (command_name, args) if the message is a command, None otherwise
    """
    # Define command prefix (e.g., /, !, $)
    command_prefix = "/"
    
    # Check if the message starts with the command prefix
    if message.startswith(command_prefix):
        # Split the message into command and arguments
        parts = message[len(command_prefix):].strip().split(maxsplit=1)
        command_name = parts[0].lower()
        
        # Get the arguments if any
        args = parts[1] if len(parts) > 1 else ""
        
        return command_name, args
    
    return None

# Function to call ChatGPT API
async def call_chatgpt(message: str, user_context: Dict[str, Any]) -> str:
    """
    Call the ChatGPT API with the given message
    
    Args:
        message: The message to send to ChatGPT
        user_context: The context information about the user
        
    Returns:
        str: The response from ChatGPT
    """
    try:
        # Create a message structure for the ChatGPT API
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message}
        ]
        
        # Call the ChatGPT API
        response = await openai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
        )
        
        # Extract and return the assistant's message
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Error calling ChatGPT API: {str(e)}")
        raise HTTPException(status_code=500, detail=f"ChatGPT API error: {str(e)}")

# Example command handlers
@register_command("help")
async def handle_help(args: str, user_context: Dict[str, Any]) -> str:
    """
    Handle the /help command
    
    Args:
        args: Any arguments passed to the command
        user_context: The context information about the user
        
    Returns:
        str: The help message
    """
    available_commands = list(command_handlers.keys())
    
    help_text = "Available commands:\n\n"
    
    for cmd in sorted(available_commands):
        if cmd == "help":
            help_text += f"/{cmd} - Show this help message\n"
        elif cmd == "echo":
            help_text += f"/{cmd} [text] - Echo back the provided text\n"
        elif cmd == "weather":
            help_text += f"/{cmd} [location] - Get weather information for the specified location\n"
        else:
            help_text += f"/{cmd}\n"
    
    help_text += "\nFor any other inquiries, just type your message and I'll respond with help from ChatGPT."
    
    return help_text

@register_command("echo")
async def handle_echo(args: str, user_context: Dict[str, Any]) -> str:
    """
    Echo back the arguments
    
    Args:
        args: The text to echo back
        user_context: The context information about the user
        
    Returns:
        str: The echoed text
    """
    if not args:
        return "You didn't provide any text to echo back."
    
    return f"Echo: {args}"

@register_command("weather")
async def handle_weather(args: str, user_context: Dict[str, Any]) -> str:
    """
    A mock weather command (would be replaced with actual API call)
    
    Args:
        args: The location to get weather for
        user_context: The context information about the user
        
    Returns:
        str: Weather information
    """
    if not args:
        return "Please specify a location. Usage: /weather [location]"
    
    # This is a mock implementation
    # In a real application, you would call a weather API here
    return f"Weather forecast for {args}: Sunny with a chance of clouds. Temperature: 72°F / 22°C"

# Main endpoint to process messages
@app.post("/process", response_model=MessageResponse)
async def process_message(request: MessageRequest = Body(...)):
    """
    Process incoming messages from the Mattermost bot
    
    Args:
        request: The message request containing the message and user information
        
    Returns:
        MessageResponse: The response to send back to the user
    """
    try:
        message = request.message
        user_context = {
            "user_id": request.user_id,
            "username": request.username,
            "channel_id": request.channel_id
        }
        
        logger.info(f"Received message from {request.username}: {message}")
        
        # Check if the message is a command
        command_info = parse_command(message)
        
        if command_info:
            command_name, args = command_info
            
            # Check if we have a handler for this command
            if command_name in command_handlers:
                # Execute the command handler
                response = await command_handlers[command_name](args, user_context)
                return MessageResponse(response=response, source="command")
        
        # If not a command or no handler found, use ChatGPT
        response = await call_chatgpt(message, user_context)
        return MessageResponse(response=response, source="chatgpt")
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing message: {str(e)}")

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

# Get available commands endpoint
@app.get("/commands")
async def get_commands():
    """List all available commands"""
    commands = list(command_handlers.keys())
    return {"commands": commands}

# Main function to run the application
def main():
    """Run the FastAPI application"""
    import uvicorn
    
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8999"))
    
    # Start the application
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main()