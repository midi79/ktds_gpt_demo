"""Webhook handlers for processing Mattermost requests."""
import logging
import asyncio
import httpx
from typing import Optional

from app.models.schemas import MattermostResponse
from app.services import (
    KubernetesService,
    PrometheusService,
    ChatGPTService,
    MattermostService,
    CommandService
)
from app.utils import ScriptDiscriminator

logger = logging.getLogger(__name__)

# Initialize services
kubernetes_service = KubernetesService()
prometheus_service = PrometheusService()
chatgpt_service = ChatGPTService()
mattermost_service = MattermostService()
command_service = CommandService()
script_discriminator = ScriptDiscriminator()

async def process_webhook_request(
    text: str,
    channel_id: str,
    user_name: str,
    response_url: Optional[str] = None
) -> MattermostResponse:
    """Process incoming webhook request and return appropriate response."""
    
    # Direct Prometheus command
    if text.lower().startswith("metric "):
        parts = text.split(" ", 1)
        if len(parts) > 1:
            query = parts[1].strip()
            asyncio.create_task(process_prometheus_query(query, channel_id, user_name, response_url, "table"))
            return MattermostResponse(
                text="Processing your Prometheus query as a table... I'll respond shortly.",
                response_type="ephemeral"
            )
    
    # Direct Kubernetes command
    elif text.lower().startswith("kubectl "):
        parts = text.split(" ", 1)
        if len(parts) > 1:
            kubectl_command = parts[1].strip()
            asyncio.create_task(process_kubernetes_command(kubectl_command, channel_id, user_name, response_url, "table"))
            return MattermostResponse(
                text="Processing your kubectl command as a table... I'll respond shortly.",
                response_type="ephemeral"
            )
    
    # Text format variants
    elif text.lower().startswith("metric-text "):
        parts = text.split(" ", 1)
        if len(parts) > 1:
            query = parts[1].strip()
            asyncio.create_task(process_prometheus_query(query, channel_id, user_name, response_url, "default"))
            return MattermostResponse(
                text="Processing your Prometheus query with text formatting... I'll respond shortly.",
                response_type="ephemeral"
            )
    
    elif text.lower().startswith("kubectl-yaml "):
        parts = text.split(" ", 1)
        if len(parts) > 1:
            kubectl_command = parts[1].strip()
            asyncio.create_task(process_kubernetes_command(kubectl_command, channel_id, user_name, response_url, "yaml"))
            return MattermostResponse(
                text="Processing your kubectl command with YAML formatting... I'll respond shortly.",
                response_type="ephemeral"
            )
    
    # Natural language query
    elif text.lower().startswith("query "):
        parts = text.split(" ", 1)
        if len(parts) > 1:
            natural_language_query = parts[1].strip()
            asyncio.create_task(process_natural_language_query(natural_language_query, channel_id, user_name, response_url, "table"))
            return MattermostResponse(
                text="Processing your natural language query... I'll respond shortly.",
                response_type="ephemeral"
            )
    
    elif text.lower().startswith("query-text "):
        parts = text.split(" ", 1)
        if len(parts) > 1:
            natural_language_query = parts[1].strip()
            asyncio.create_task(process_natural_language_query(natural_language_query, channel_id, user_name, response_url, "default"))
            return MattermostResponse(
                text="Processing your natural language query with text formatting... I'll respond shortly.",
                response_type="ephemeral"
            )
    
    # Check for predefined commands
    response = command_service.process_command(text)
    
    if response is not None:
        return MattermostResponse(text=response)
    
    # For any other text, process with ChatGPT
    asyncio.create_task(process_with_chatgpt_and_route(text, channel_id, user_name, response_url))
    return MattermostResponse(
        text="Processing your request... I'll respond shortly.",
        response_type="ephemeral"
    )

async def process_prometheus_query(query: str, channel_id: str, user_name: str, response_url: str, format_type: str = "table"):
    """Process a Prometheus query in the background."""
    try:
        response = await prometheus_service.execute_query(query, format_type)
        formatted_response = f"@{user_name} requested metrics: \"{query}\"\n\n{response}"
        
        if response_url:
            async with httpx.AsyncClient() as client:
                await client.post(
                    response_url,
                    json={"text": formatted_response, "response_type": "in_channel"},
                    timeout=10.0
                )
        else:
            await mattermost_service.send_response(channel_id, formatted_response)
            
    except Exception as e:
        logger.error(f"Error in Prometheus query processing: {str(e)}")
        error_message = f"Sorry, I encountered an error with your Prometheus query: {str(e)}"
        try:
            if response_url:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        response_url,
                        json={"text": error_message, "response_type": "ephemeral"},
                        timeout=10.0
                    )
            else:
                await mattermost_service.send_response(channel_id, f"@{user_name} {error_message}")
        except Exception as inner_e:
            logger.error(f"Failed to send error message: {str(inner_e)}")

async def process_kubernetes_command(kubectl_command: str, channel_id: str, user_name: str, response_url: str, format_type: str = "table"):
    """Process a Kubernetes command in the background."""
    try:
        logger.info(f"k8s Command: {kubectl_command}, format_type: {format_type}")
        results = await kubernetes_service.execute_kubectl_command(kubectl_command, format_type)
        formatted_response = f"@{user_name} requested kubectl: \"{kubectl_command}\"\n\n{results}"
        
        if response_url:
            async with httpx.AsyncClient() as client:
                await client.post(
                    response_url,
                    json={"text": formatted_response, "response_type": "in_channel"},
                    timeout=10.0
                )
        else:
            await mattermost_service.send_response(channel_id, formatted_response)
            
    except Exception as e:
        logger.error(f"Error in Kubernetes command processing: {str(e)}")
        error_message = f"Sorry, I encountered an error with your kubectl command: {str(e)}"
        try:
            if response_url:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        response_url,
                        json={"text": error_message, "response_type": "ephemeral"},
                        timeout=10.0
                    )
            else:
                await mattermost_service.send_response(channel_id, f"@{user_name} {error_message}")
        except Exception as inner_e:
            logger.error(f"Failed to send error message: {str(inner_e)}")

async def process_natural_language_query(query: str, channel_id: str, user_name: str, response_url: str, format_type: str = "table"):
    """Process natural language query."""
    try:
        system_prompt = """You are an expert in both Prometheus (PromQL) and Kubernetes (kubectl). 
        When given a natural language query about monitoring or infrastructure:
        
        1. If it's about metrics, monitoring, alerts, or data visualization, generate a PromQL query
        2. If it's about pods, services, deployments, logs, or Kubernetes resources, generate a kubectl command
        
        Important guidelines:
        - Always wrap your code in appropriate code blocks (```promql or ```bash)
        - For PromQL: Make queries practical and efficient
        - For kubectl: Use realistic commands that work with the Kubernetes API
        - Keep responses focused on the technical implementation
        
        Examples:
        - "Show me CPU usage" → ```promql\nrate(cpu_usage_total[5m])\n```
        - "List all pods" → ```bash\nkubectl get pods --all-namespaces\n```
        """
        
        chatgpt_response = await chatgpt_service.get_response(query, system_prompt)
        script_type, extracted_script = script_discriminator.detect_script_type(chatgpt_response)
        
        logger.info(f"Detected script type: {script_type}, Script: {extracted_script}")
        
        if script_type == "promql":
            results = await prometheus_service.execute_query(extracted_script, format_type)
            formatted_response = (
                f"@{user_name} asked: \"{query}\"\n\n"
                f"**Generated PromQL:** `{extracted_script}`\n\n"
                f"{results}"
            )
        elif script_type == "kubernetes":
            results = await kubernetes_service.execute_kubectl_command(extracted_script, format_type)
            formatted_response = (
                f"@{user_name} asked: \"{query}\"\n\n"
                f"**Generated kubectl command:** `{extracted_script}`\n\n"
                f"{results}"
            )
        else:
            formatted_response = (
                f"@{user_name} asked: \"{query}\"\n\n"
                f"{chatgpt_response}"
            )
        
        if response_url:
            async with httpx.AsyncClient() as client:
                await client.post(
                    response_url,
                    json={"text": formatted_response, "response_type": "in_channel"},
                    timeout=10.0
                )
        else:
            await mattermost_service.send_response(channel_id, formatted_response)
            
    except Exception as e:
        logger.error(f"Error in natural language processing: {str(e)}")
        error_message = f"Sorry, I encountered an error processing your query: {str(e)}"
        try:
            if response_url:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        response_url,
                        json={"text": error_message, "response_type": "ephemeral"},
                        timeout=10.0
                    )
            else:
                await mattermost_service.send_response(channel_id, f"@{user_name} {error_message}")
        except Exception as inner_e:
            logger.error(f"Failed to send error message: {str(inner_e)}")

async def process_with_chatgpt_and_route(text: str, channel_id: str, user_name: str, response_url: str):
    """Process request with ChatGPT and automatically route any generated scripts."""
    try:
        chatgpt_response = await chatgpt_service.get_response(text)
        script_type, extracted_script = script_discriminator.detect_script_type(chatgpt_response)
        
        logger.info(f"ChatGPT response received. Detected script type: {script_type}")
        
        if script_type == "promql":
            cleaned_script = extracted_script.split('\n')[0].strip()
            if cleaned_script:
                prometheus_results = await prometheus_service.execute_query(cleaned_script, "table")
                formatted_response = (
                    f"@{user_name} asked: \"{text}\"\n\n"
                    f"**ChatGPT's response:** {chatgpt_response}\n\n"
                    f"**Detected PromQL query:** `{cleaned_script}`\n\n"
                    f"**Execution results:**\n{prometheus_results}"
                )
            else:
                formatted_response = f"@{user_name} asked: \"{text}\"\n\n{chatgpt_response}"
        elif script_type == "kubernetes":
            k8s_results = await kubernetes_service.execute_kubectl_command(extracted_script, "table")
            formatted_response = (
                f"@{user_name} asked: \"{text}\"\n\n"
                f"**ChatGPT's response:** {chatgpt_response}\n\n"
                f"**Detected kubectl command:** `{extracted_script}`\n\n"
                f"**Execution results:**\n{k8s_results}"
            )
        else:
            formatted_response = f"@{user_name} asked: \"{text}\"\n\n{chatgpt_response}"
        
        if response_url:
            async with httpx.AsyncClient() as client:
                await client.post(
                    response_url,
                    json={"text": formatted_response, "response_type": "in_channel"},
                    timeout=10.0
                )
        else:
            await mattermost_service.send_response(channel_id, formatted_response)
            
    except Exception as e:
        logger.error(f"Error in ChatGPT routing: {str(e)}")
        error_message = f"Sorry, I encountered an error: {str(e)}"
        try:
            if response_url:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        response_url,
                        json={"text": error_message, "response_type": "ephemeral"},
                        timeout=10.0
                    )
            else:
                await mattermost_service.send_response(channel_id, f"@{user_name} {error_message}")
        except Exception as inner_e:
            logger.error(f"Failed to send error message: {str(inner_e)}")