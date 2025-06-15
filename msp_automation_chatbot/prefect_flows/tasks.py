"""Prefect tasks for Kubernetes troubleshooting."""
import logging
import re
from typing import List, Dict, Optional, Tuple
from prefect import task
import asyncio

# Import existing services
from app.services import KubernetesService, ChatGPTService, MattermostService

logger = logging.getLogger(__name__)

@task(
    name="Initialize Services",
    description="Initialize Kubernetes, ChatGPT, and Mattermost services",
    retries=2
)
async def initialize_services() -> Tuple[KubernetesService, ChatGPTService, MattermostService]:
    """Initialize all required services."""
    k8s_service = KubernetesService()
    chatgpt_service = ChatGPTService()
    mattermost_service = MattermostService()
    
    logger.info("Services initialized successfully")
    return k8s_service, chatgpt_service, mattermost_service

@task(
    name="Get All Namespaces",
    description="Fetch all Kubernetes namespaces"
)
async def get_all_namespaces(k8s_service: KubernetesService) -> str:
    """Get all namespaces in the cluster."""
    logger.info("Fetching all namespaces")
    result = await k8s_service.execute_kubectl_command("kubectl get namespaces", "table")
    return result

@task(
    name="Get All Pods",
    description="Fetch all pods across all namespaces"
)
async def get_all_pods(k8s_service: KubernetesService) -> str:
    """Get all pods in the cluster."""
    logger.info("Fetching all pods")
    result = await k8s_service.execute_kubectl_command("kubectl get pods --all-namespaces", "table")
    return result

@task(
    name="Find Abnormal Pods",
    description="Identify pods not in Running or Succeeded state"
)
async def find_abnormal_pods(k8s_service: KubernetesService) -> Tuple[str, Optional[Dict[str, str]]]:
    """Find pods that are not in Running or Succeeded state."""
    logger.info("Finding abnormal pods")
    
    # Get pods that are not Running or Succeeded
    result = await k8s_service.execute_kubectl_command(
        'kubectl get pods --all-namespaces --field-selector="status.phase!=Running"',
        "table"
    )
    
    # Parse the result to find the first abnormal pod
    lines = result.split('\n')
    abnormal_pod = None
    
    for line in lines:
        if '|' in line and 'NAMESPACE' not in line and '---' not in line:
            parts = [p.strip() for p in line.split('|')]
            if len(parts) >= 4:
                # Extract namespace, pod name, and status
                pod_name = parts[0]
                namespace = parts[1]
                status = parts[2]
                
                # Skip empty lines or header remnants
                if pod_name and namespace and status and status not in ['Running', 'Succeeded', 'STATUS', 'Name']:
                    abnormal_pod = {
                        'namespace': namespace,
                        'name': pod_name,
                        'status': status
                    }
                    logger.info(f"Found abnormal pod: {pod_name} in namespace {namespace} with status {status}")
                    break
    
    if not abnormal_pod:
        logger.info("No abnormal pods found")
    
    return result, abnormal_pod

@task(
    name="Describe Abnormal Pod",
    description="Get detailed description of the abnormal pod"
)
async def describe_abnormal_pod(k8s_service: KubernetesService, pod_info: Optional[Dict[str, str]]) -> Optional[str]:
    """Describe the abnormal pod to get detailed information."""
    if not pod_info:
        logger.info("No abnormal pod found to describe")
        return None
    
    logger.info(f"Describing pod {pod_info['name']} in namespace {pod_info['namespace']}")
    
    command = f"kubectl describe pod {pod_info['name']} -n {pod_info['namespace']}"
    result = await k8s_service.execute_kubectl_command(command, "yaml")
    
    return result

@task(
    name="Extract Error Information",
    description="Extract error details from pod description"
)
def extract_error_info(pod_description: Optional[str]) -> Optional[str]:
    """Extract error information from pod description."""
    if not pod_description:
        return None
    
    error_patterns = [
        r"Error:.*",
        r"Failed.*",
        r"BackOff.*",
        r"CrashLoopBackOff.*",
        r"ImagePullBackOff.*",
        r"ErrImagePull.*",
        r"CreateContainerError.*",
        r"InvalidImageName.*",
        r"Reason:.*",
        r"Warning.*",
        r"Message:.*Error.*",
        r"Exit Code:.*[1-9].*"
    ]
    
    errors = []
    seen_errors = set()  # To avoid duplicates
    lines = pod_description.split('\n')
    
    for line in lines:
        for pattern in error_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                error_line = line.strip()
                # Avoid duplicate errors
                if error_line not in seen_errors and len(error_line) > 5:
                    errors.append(error_line)
                    seen_errors.add(error_line)
                break
    
    if errors:
        return "\n".join(errors[:10])  # Limit to first 10 errors
    else:
        return "No specific errors found in pod description"

@task(
    name="Get Solution from ChatGPT",
    description="Ask ChatGPT for solutions based on the error information"
)
async def get_solution_from_chatgpt(
    chatgpt_service: ChatGPTService,
    pod_info: Optional[Dict[str, str]],
    error_info: Optional[str]
) -> str:
    """Ask ChatGPT for solution based on the error information."""
    if not error_info or not pod_info:
        return "No error information available to analyze."
    
    prompt = f"""
    I have a Kubernetes pod with the following issues:
    
    Pod Name: {pod_info['name']}
    Namespace: {pod_info['namespace']}
    Status: {pod_info['status']}
    
    Error Information:
    {error_info}
    
    Please provide:
    1. A brief explanation of what's wrong (2-3 sentences)
    2. The most likely root cause
    3. Step-by-step solution (maximum 5 steps)
    4. A kubectl command to help fix or diagnose further if applicable
    
    Keep the response concise and actionable. Format it nicely for Mattermost.
    """
    
    logger.info("Getting solution from ChatGPT")
    solution = await chatgpt_service.get_response(prompt)
    
    return solution

@task(
    name="Send to Mattermost",
    description="Send workflow step results to Mattermost",
    retries=2
)
async def send_to_mattermost(
    mattermost_service: MattermostService,
    channel_id: str,
    message: str,
    step_name: str
):
    """Send a message to Mattermost with step information."""
    # Format message with emoji and styling
    step_emojis = {
        "Workflow Initiated": "🚀",
        "1. All Namespaces": "📋",
        "2. All Pods": "🔍",
        "3. Abnormal Pods": "⚠️",
        "4. Pod Description": "📝",
        "5. Error Analysis": "🔎",
        "6. Recommended Solution": "💡",
        "Workflow Complete": "✅",
        "Workflow Error": "❌"
    }
    
    emoji = step_emojis.get(step_name, "▶️")
    formatted_message = f"{emoji} **[Workflow Step: {step_name}]**\n\n{message}"
    
    await mattermost_service.send_response(channel_id, formatted_message)
    logger.info(f"Sent {step_name} results to Mattermost")