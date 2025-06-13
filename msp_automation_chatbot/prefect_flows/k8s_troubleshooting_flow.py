"""Main Prefect flow for Kubernetes troubleshooting."""
import logging
from prefect import flow, get_run_logger
from prefect.runtime import flow_run
import asyncio
from typing import Optional
import sys
from pathlib import Path

# Add parent directory to path if running directly
if __name__ == "__main__":
    sys.path.append(str(Path(__file__).parent.parent))

try:
    # Try relative import first (when used as module)
    from .tasks import (
        initialize_services,
        get_all_namespaces,
        get_all_pods,
        find_abnormal_pods,
        describe_abnormal_pod,
        extract_error_info,
        get_solution_from_chatgpt,
        send_to_mattermost
    )
except ImportError:
    # Fall back to absolute import (when running directly)
    from prefect_flows.tasks import (
        initialize_services,
        get_all_namespaces,
        get_all_pods,
        find_abnormal_pods,
        describe_abnormal_pod,
        extract_error_info,
        get_solution_from_chatgpt,
        send_to_mattermost
    )

logger = logging.getLogger(__name__)

@flow(
    name="k8s-troubleshooting-flow",
    description="Automated Kubernetes troubleshooting workflow for Mattermost",
    retries=1,
    retry_delay_seconds=30,
    log_prints=True,
    persist_result=True
)
async def k8s_troubleshooting_flow(
    channel_id: str,
    user_name: str,
    target_namespace: Optional[str] = None,
    target_pod: Optional[str] = None
):
    """
    Main flow for Kubernetes troubleshooting.
    
    Args:
        channel_id: Mattermost channel ID
        user_name: User who triggered the workflow
        target_namespace: Optional specific namespace to check
        target_pod: Optional specific pod to check
    
    Steps:
    1. Show all namespaces in the cluster
    2. Show all pods in the cluster
    3. Show abnormal pods in the cluster
    4. Describe the abnormal pod status
    5. Get error information and ask for solution
    """
    flow_logger = get_run_logger()
    flow_logger.info(f"Starting K8s troubleshooting workflow for user {user_name} in channel {channel_id}")
    
    try:
        # Initialize services
        k8s_service, chatgpt_service, mattermost_service = await initialize_services()
        
        # Get flow run ID
        flow_run_id = str(flow_run.get_id()) if hasattr(flow_run, 'get_id') else 'unknown'
        
        # Send workflow start message
        await send_to_mattermost(
            mattermost_service,
            channel_id,
            f"@{user_name} Starting Kubernetes Troubleshooting Workflow\n"
            f"Flow Run ID: `{flow_run_id}`\n"
            f"Target Namespace: `{target_namespace or 'All'}`\n"
            f"Target Pod: `{target_pod or 'Auto-detect'}`",
            "Workflow Initiated"
        )
        
        # Step 1: Get all namespaces
        flow_logger.info("Step 1: Getting all namespaces")
        namespaces_result = await get_all_namespaces(k8s_service)
        await send_to_mattermost(
            mattermost_service,
            channel_id,
            namespaces_result,
            "1. All Namespaces"
        )
        
        # Small delay for better readability in Mattermost
        await asyncio.sleep(2)
        
        # Step 2: Get all pods
        flow_logger.info("Step 2: Getting all pods")
        pods_command = "kubectl get pods --all-namespaces"
        if target_namespace:
            pods_command = f"kubectl get pods -n {target_namespace}"
            
        pods_result = await get_all_pods(k8s_service)
        await send_to_mattermost(
            mattermost_service,
            channel_id,
            pods_result,
            "2. All Pods"
        )
        
        await asyncio.sleep(2)
        
        # Step 3: Find abnormal pods
        flow_logger.info("Step 3: Finding abnormal pods")
        abnormal_pods_result, abnormal_pod_info = await find_abnormal_pods(k8s_service)
        
        # Override with target pod if specified
        if target_pod and target_namespace:
            abnormal_pod_info = {
                'name': target_pod,
                'namespace': target_namespace,
                'status': 'User-specified'
            }
            abnormal_pods_result = f"Analyzing user-specified pod: **{target_pod}** in namespace **{target_namespace}**"
        
        await send_to_mattermost(
            mattermost_service,
            channel_id,
            abnormal_pods_result,
            "3. Abnormal Pods"
        )
        
        await asyncio.sleep(2)
        
        # Step 4: Describe abnormal pod (if found)
        if abnormal_pod_info:
            flow_logger.info(f"Step 4: Describing pod {abnormal_pod_info['name']}")
            pod_description = await describe_abnormal_pod(k8s_service, abnormal_pod_info)
            
            if pod_description:
                # Truncate description if too long for Mattermost
                if len(pod_description) > 3000:
                    pod_description = pod_description[:3000] + "\n\n... (truncated)"
                
                await send_to_mattermost(
                    mattermost_service,
                    channel_id,
                    f"Describing pod: **{abnormal_pod_info['name']}** in namespace **{abnormal_pod_info['namespace']}**\n\n{pod_description}",
                    "4. Pod Description"
                )
                
                await asyncio.sleep(2)
                
                # Step 5: Extract errors and get solution
                flow_logger.info("Step 5: Extracting error information")
                error_info = extract_error_info(pod_description)
                
                if error_info and error_info != "No specific errors found in pod description":
                    await send_to_mattermost(
                        mattermost_service,
                        channel_id,
                        f"**Extracted Error Information:**\n```\n{error_info}\n```",
                        "5. Error Analysis"
                    )
                    
                    await asyncio.sleep(2)
                    
                    # Get solution from ChatGPT
                    flow_logger.info("Step 6: Getting solution from ChatGPT")
                    solution = await get_solution_from_chatgpt(
                        chatgpt_service,
                        abnormal_pod_info,
                        error_info
                    )
                    
                    await send_to_mattermost(
                        mattermost_service,
                        channel_id,
                        solution,
                        "6. Recommended Solution"
                    )
                else:
                    await send_to_mattermost(
                        mattermost_service,
                        channel_id,
                        "✅ No specific errors found in the pod description. The pod might be in a transient state or the issue might have resolved.",
                        "5. Error Analysis"
                    )
        else:
            await send_to_mattermost(
                mattermost_service,
                channel_id,
                "✅ Good news! No abnormal pods found in the cluster. All pods are either Running or Succeeded.",
                "4. Analysis Complete"
            )
        
        # Send workflow completion message
        await send_to_mattermost(
            mattermost_service,
            channel_id,
            f"Kubernetes Troubleshooting Workflow completed successfully!\n"
            f"Total steps executed: 6\n"
            f"Flow Run ID: `{flow_run_id}`",
            "Workflow Complete"
        )
        
        flow_logger.info("Workflow completed successfully")
        return {"status": "success", "flow_run_id": flow_run_id}
        
    except Exception as e:
        flow_logger.error(f"Error in K8s troubleshooting workflow: {str(e)}")
        
        # Try to send error message to Mattermost
        try:
            _, _, mattermost_service = await initialize_services()
            await send_to_mattermost(
                mattermost_service,
                channel_id,
                f"Workflow failed with error: {str(e)}\n"
                f"Please check the Prefect UI for detailed logs.",
                "Workflow Error"
            )
        except Exception as inner_e:
            flow_logger.error(f"Failed to send error message to Mattermost: {str(inner_e)}")
        
        raise