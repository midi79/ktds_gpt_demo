"""ChatGPT service for natural language processing."""
import logging
import asyncio
import httpx

from app.config import config

logger = logging.getLogger(__name__)

class ChatGPTService:
    """Service for interacting with OpenAI's ChatGPT."""
    
    request_count = 0
    max_retries = 3
    
    @staticmethod
    async def get_response(message: str, system_prompt: str = None) -> str:
        """Get response from ChatGPT with retry logic and rate limiting."""
        if not config.OPENAI_API_KEY:
            return "Error: OpenAI API key is not configured. Please contact the administrator."
            
        logger.info(f"Sending message to ChatGPT: {message}")
        
        ChatGPTService.request_count += 1
        
        if ChatGPTService.request_count > 45:
            logger.warning("Rate limit preemptively applied")
            ChatGPTService.request_count = max(0, ChatGPTService.request_count - 5)
            return "I'm getting too many requests right now. Please try again in a few moments."
        
        if system_prompt is None:
            system_prompt = """You are a helpful assistant integrated with Mattermost. Keep responses concise and under 2000 characters.

When users ask about monitoring, metrics, or Prometheus (in any language including Korean):
- Always provide PromQL queries in code blocks with ```promql
- For filesystem questions (파일시스템, 디스크, 저장공간), use node_filesystem metrics
- Example filesystem query: ```promql
node_filesystem_avail_bytes{fstype!="tmpfs"} / node_filesystem_size_bytes{fstype!="tmpfs"} * 100
When users ask about Kubernetes, pods, services, deployments, or kubectl commands:

Provide kubectl commands in code blocks with ```bash
For Korean requests about pods (파드), nodes (노드), services (서비스), use appropriate kubectl commands

Always format your scripts in properly tagged code blocks.
Respond in Korean when the user writes in Korean."""
        retry_delay = 1
        
        for attempt in range(ChatGPTService.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": "gpt-4o-mini",
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": message}
                            ],
                            "temperature": 0.7,
                            "max_tokens": 1000,
                            "top_p": 1,
                            "frequency_penalty": 0,
                            "presence_penalty": 0
                        },
                        timeout=30.0
                    )
                    
                    response.raise_for_status()
                    data = response.json()
                    logger.info(f"Response from ChatGPT received")
                    return data["choices"][0]["message"]["content"]
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    if attempt < ChatGPTService.max_retries - 1:
                        logger.warning(f"Rate limit hit, retrying in {retry_delay} seconds")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        logger.error("Rate limit persisted after max retries")
                        return "I'm currently experiencing high demand. Please try again in a few minutes."
                else:
                    logger.error(f"HTTP error from OpenAI API: {e.response.status_code}")
                    return f"Sorry, there was an issue with the AI service (HTTP {e.response.status_code})."
                    
            except httpx.RequestError as e:
                logger.error(f"Request error connecting to OpenAI: {str(e)}")
                return "Sorry, I couldn't connect to the AI service. Please try again."
                
            except Exception as e:
                logger.error(f"Unexpected error with ChatGPT: {str(e)}")
                return "Sorry, an unexpected error occurred. Please try again."