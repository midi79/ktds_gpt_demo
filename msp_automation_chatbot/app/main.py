"""Main FastAPI application."""
import logging
from fastapi import FastAPI, Form, HTTPException
from typing import Optional
import httpx
import asyncio
from uuid import UUID

from app.config import config
from app.models.schemas import MattermostResponse
from app.handlers import process_webhook_request

# Import Prefect 3.4 client
from prefect import get_client
from prefect.client.schemas.filters import DeploymentFilter, FlowFilter
from prefect.client.schemas.sorting import DeploymentSort

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Validate configuration at startup
try:
    config.validate()
except ValueError as e:
    logger.error(f"Configuration error: {e}")
    raise

app = FastAPI(title="Mattermost ChatGPT Integration with K8s and Prometheus")

async def trigger_prefect_workflow(channel_id: str, user_name: str, namespace: Optional[str] = None, pod: Optional[str] = None):
    """Trigger the Prefect K8s troubleshooting workflow using Prefect 3.4 API."""
    try:
        logger.info(f"Triggering Prefect workflow for user {user_name}")
        
        async with get_client() as client:
            # Find deployment by name using filters
            deployments = await client.read_deployments(
                deployment_filter=DeploymentFilter(
                    name={"any_": ["k8s-troubleshooting"]}
                ),
                limit=1
            )
            
            if not deployments:
                raise ValueError("Deployment 'k8s-troubleshooting' not found. Please run deployment.py first.")
            
            deployment = deployments[0]
            
            # Create a flow run from deployment
            flow_run = await client.create_flow_run_from_deployment(
                deployment_id=deployment.id,
                parameters={
                    "channel_id": channel_id,
                    "user_name": user_name,
                    "target_namespace": namespace,
                    "target_pod": pod
                },
                state=None,  # Let Prefect handle initial state
                name=f"k8s-troubleshoot-{user_name}-{channel_id[:8]}"
            )
            
            logger.info(f"Created flow run with ID: {flow_run.id}")
            
            return flow_run.id
            
    except Exception as e:
        logger.error(f"Error triggering Prefect workflow: {str(e)}")
        raise

def parse_workflow_command(text: str) -> tuple[Optional[str], Optional[str]]:
    """Parse workflow command for optional namespace and pod parameters."""
    parts = text.strip().split()
    
    namespace = None
    pod = None
    
    # Parse parameters like: workflow -n namespace -p pod
    i = 1  # Skip 'workflow'
    while i < len(parts):
        if parts[i] in ['-n', '--namespace'] and i + 1 < len(parts):
            namespace = parts[i + 1]
            i += 2
        elif parts[i] in ['-p', '--pod'] and i + 1 < len(parts):
            pod = parts[i + 1]
            i += 2
        else:
            i += 1
    
    return namespace, pod

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
    if config.MATTERMOST_WEBHOOK_TOKEN and token != config.MATTERMOST_WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    logger.info(f"Received slash command: {command} with text: {text} from user: {user_name}")
    
    # Check for workflow trigger
    if text.strip().lower().startswith("workflow"):
        try:
            # Parse optional parameters
            namespace, pod = parse_workflow_command(text)
            
            # Trigger the Prefect workflow
            flow_run_id = await trigger_prefect_workflow(channel_id, user_name, namespace, pod)
            
            params_msg = ""
            if namespace or pod:
                params_msg = "\n**Parameters:**"
                if namespace:
                    params_msg += f"\n- Namespace: `{namespace}`"
                if pod:
                    params_msg += f"\n- Pod: `{pod}`"
            
            return MattermostResponse(
                text=f"🚀 Kubernetes Troubleshooting Workflow started!\n"
                     f"Flow Run ID: `{flow_run_id}`{params_msg}\n\n"
                     f"I'll send updates as the workflow progresses.\n\n"
                     f"💡 **Tip:** You can also use parameters:\n"
                     f"`workflow -n <namespace> -p <pod>`",
                response_type="in_channel"
            )
        except Exception as e:
            logger.error(f"Failed to trigger workflow: {str(e)}")
            return MattermostResponse(
                text=f"❌ Failed to start workflow: {str(e)}\n\n"
                     f"Please make sure the Prefect deployment is running:\n"
                     f"```bash\npython prefect_flows/deployment.py\n```",
                response_type="ephemeral"
            )
    
    # Handle all other commands as before
    return await process_webhook_request(text, channel_id, user_name, response_url)

@app.get("/health")
async def health_check():
    """Health check endpoint with service status."""
    from app.services import KubernetesService
    k8s_service = KubernetesService()
    
    # Check Prefect connection
    prefect_status = "not connected"
    deployment_count = 0
    try:
        async with get_client() as client:
            # Check Prefect API connection
            deployments = await client.read_deployments(limit=5)
            deployment_count = len(deployments)
            prefect_status = "connected"
    except Exception as e:
        logger.error(f"Prefect connection check failed: {str(e)}")
    
    return {
        "status": "healthy",
        "services": {
            "prometheus": "configured" if config.PROMETHEUS_URL else "not configured",
            "kubernetes": "initialized" if k8s_service.is_client_available() else "not initialized",
            "openai": "configured" if config.OPENAI_API_KEY else "not configured",
            "mattermost": "configured" if config.MATTERMOST_URL and config.MATTERMOST_BOT_TOKEN else "not configured",
            "kubectl_subprocess": "enabled" if config.ENABLE_KUBECTL_SUBPROCESS else "disabled (recommended)",
            "prefect": {
                "status": prefect_status,
                "deployments": deployment_count
            }
        },
        "kubectl_path": config.KUBECTL_PATH,
        "prefect_api_url": config.PREFECT_API_URL if hasattr(config, 'PREFECT_API_URL') else "not configured"
    }

@app.get("/workflow/status/{flow_run_id}")
async def get_workflow_status(flow_run_id: str):
    """Get the status of a workflow run."""
    try:
        async with get_client() as client:
            flow_run = await client.read_flow_run(UUID(flow_run_id))
            
            return {
                "flow_run_id": str(flow_run.id),
                "name": flow_run.name,
                "state": flow_run.state.name if flow_run.state else "Unknown",
                "state_type": flow_run.state.type.value if flow_run.state else "Unknown",
                "created": flow_run.created,
                "updated": flow_run.updated,
                "start_time": flow_run.start_time,
                "end_time": flow_run.end_time,
                "total_run_time": flow_run.total_run_time,
                "parameters": flow_run.parameters
            }
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Flow run not found: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=config.PORT, reload=True)