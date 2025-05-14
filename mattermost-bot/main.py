import os
import asyncio
import re
from fastapi import FastAPI, Request, HTTPException, Form, Depends
from fastapi.responses import JSONResponse
import httpx
import uvicorn
import time
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import logging
from dotenv import load_dotenv
import json
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import yaml

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Mattermost ChatGPT Integration with K8s and Prometheus")

# Environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MATTERMOST_URL = os.getenv("MATTERMOST_URL")
MATTERMOST_BOT_TOKEN = os.getenv("MATTERMOST_BOT_TOKEN")
MATTERMOST_WEBHOOK_TOKEN = os.getenv("MATTERMOST_WEBHOOK_TOKEN")
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
KUBERNETES_CONFIG_PATH = os.getenv("KUBERNETES_CONFIG_PATH")  # Optional path to kubeconfig

# Response model for Mattermost
class MattermostResponse(BaseModel):
    text: str
    response_type: str = "in_channel"

# Initialize Kubernetes client
class KubernetesService:
    def __init__(self):
        """Initialize Kubernetes client."""
        try:
            # Try to load in-cluster config first
            try:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes configuration")
            except config.ConfigException:
                # Fall back to kubeconfig file
                if KUBERNETES_CONFIG_PATH:
                    config.load_kube_config(config_file=KUBERNETES_CONFIG_PATH)
                else:
                    config.load_kube_config()
                logger.info("Loaded Kubernetes configuration from file")
            
            self.v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.networking_v1 = client.NetworkingV1Api()
            self.batch_v1 = client.BatchV1Api()
            self.storage_v1 = client.StorageV1Api()
            
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {str(e)}")
            self.v1 = None
            
    async def execute_kubectl_command(self, command: str, format_type: str = "yaml") -> str:
        """
        Execute kubectl-like commands using the Kubernetes Python client.
        """
        if not self.v1:
            return "Error: Kubernetes client is not initialized. Please check your configuration."
            
        try:
            # Store original command for reference
            original_command = command.strip()
            
            # Use lowercase version ONLY for command detection, not for actual processing
            command_lower = command.strip().lower()
            parts = command_lower.split()
            
            if not parts:
                return "Error: Empty command"
            
            # Parse the main command structure
            verb = parts[0] if parts else ""
            resource = parts[1] if len(parts) > 1 else ""
            
            # Handle various get commands - PASS ORIGINAL COMMAND
            if verb == "get":
                if resource in ["pods", "pod"]:
                    return await self._get_pods(original_command, format_type)
                elif resource in ["services", "svc", "service"]:
                    return await self._get_services(original_command, format_type)
                elif resource in ["deployments", "deploy", "deployment"]:
                    return await self._get_deployments(original_command, format_type)
                elif resource in ["namespaces", "ns", "namespace"]:
                    return await self._get_namespaces(original_command, format_type)
                elif resource in ["nodes", "node"]:
                    return await self._get_nodes(original_command, format_type)
            
            # Handle describe commands - PASS ORIGINAL COMMAND
            elif verb == "describe":
                if resource in ["pod", "pods"]:
                    return await self._describe_pod(original_command, format_type)
                else:
                    return await self._execute_unsupported_command(original_command)
            
            # Handle logs commands - PASS ORIGINAL COMMAND
            elif verb == "logs" or (verb == "get" and resource == "logs"):
                return await self._get_logs(original_command, format_type)
            
            # Try to interpret the command more flexibly - PASS ORIGINAL COMMAND
            elif "describe pod" in command_lower:
                return await self._describe_pod(original_command, format_type)
            
            # Try to interpret the command more flexibly first
            elif "get pods" in command:
                return await self._get_pods(command, format_type)
            elif "get services" in command or "get svc" in command:
                return await self._get_services(command, format_type)
            elif "get deployments" in command or "get deploy" in command:
                return await self._get_deployments(command, format_type)
            elif "get namespaces" in command or "get ns" in command:
                return await self._get_namespaces(command, format_type)
            elif "get nodes" in command:
                return await self._get_nodes(command, format_type)
            elif "describe pod" in command:
                return await self._describe_pod(command, format_type)
            elif "logs" in command:
                return await self._get_logs(command, format_type)
            
            # NEW: Handle unsupported commands instead of returning error immediately
            # Special handling for common unsupported commands
            if verb == "cluster-info":
                return await self._get_cluster_info()
            elif verb == "version":
                return await self._get_version()
            elif verb == "config":
                return await self._handle_config_command(original_command)
            elif "api-resources" in command:
                return await self._get_api_resources()
            elif "api-versions" in command:
                return await self._get_api_versions()
            else:
                # For any other unsupported command, provide a helpful message
                return f"""### Command '{original_command}' Attempted

    **Status:** This command cannot be directly executed through the Kubernetes Python client.

    **Explanation:** Some kubectl commands like cluster-info, version, api-resources, etc. require direct access to the kubectl binary or additional cluster permissions that aren't available through the programmatic API.

    **Supported Operations:**
    - Resource listing (pods, services, deployments, namespaces, nodes)
    - Resource description (pods)
    - Log retrieval (pod logs)
    - Field and label selector filtering

    **Alternative:** Run this command directly on a machine with kubectl configured and cluster access."""
                
        except Exception as e:
            return f"Error executing kubectl command: {str(e)}"
    
    async def _execute_unsupported_command(self, command: str) -> str:
        """
        Attempt to execute unsupported kubectl commands by making a best-effort attempt
        to map them to appropriate API calls.
        """
        try:
            # Log that we're attempting an unsupported command
            logger.info(f"Attempting to execute unsupported command: {command}")
            
            # Parse the command to extract meaningful information
            parts = command.strip().split()
            verb = parts[0] if parts else ""
            
            # Handle common unsupported commands
            if verb == "cluster-info":
                return await self._get_cluster_info()
            elif verb == "version":
                return await self._get_version()
            elif verb == "config":
                return await self._handle_config_command(command)
            elif "api-resources" in command:
                return await self._get_api_resources()
            elif "api-versions" in command:
                return await self._get_api_versions()
            else:
                # For other commands, try to provide a helpful message
                return f"""Command '{command}' is not directly supported in this application.

**Supported commands:**
- get pods [--all-namespaces] [--field-selector=...] [--selector=...]
- get services [--all-namespaces] [--field-selector=...]
- get deployments [--all-namespaces] [--field-selector=...]
- get namespaces
- get nodes
- describe pod <pod-name> [-n namespace]
- logs <pod-name> [-n namespace] [--tail=lines]

**Note:** The command was attempted but could not be executed directly through the Kubernetes Python client. You may need to run this command directly on a machine with kubectl access."""
                
        except Exception as e:
            logger.error(f"Error executing unsupported command: {str(e)}")
            return f"""Cannot execute command '{command}'.

**Error:** {str(e)}

**Note:** This command is not supported by the Kubernetes Python client interface. Common unsupported commands include:
- cluster-info
- version
- config commands
- port-forward
- exec
- apply/delete (for security reasons)

Please run these commands directly on a machine with kubectl access."""
    
    async def _get_cluster_info(self) -> str:
        """Get cluster information using available APIs."""
        try:
            # Get some basic cluster information
            info = "### Cluster Information\n\n"
            
            # Get server version
            try:
                version = self.v1.api_client.get_api_version()
                info += f"**API Version:** {version}\n"
            except:
                pass
            
            # Get nodes summary
            try:
                nodes = self.v1.list_node()
                info += f"**Nodes:** {len(nodes.items)} nodes\n"
            except:
                pass
            
            # Get namespaces summary
            try:
                namespaces = self.v1.list_namespace()
                info += f"**Namespaces:** {len(namespaces.items)} namespaces\n"
            except:
                pass
            
            info += "\n**Note:** This is a limited cluster info view. For complete cluster-info, use kubectl directly."
            return info
            
        except Exception as e:
            return f"Error getting cluster info: {str(e)}"
    
    async def _get_version(self) -> str:
        """Get Kubernetes version information."""
        try:
            version_info = self.v1.api_client.configuration.version
            return f"### Kubernetes Version\n\n**Client Version:** {version_info}\n\n**Note:** Server version information requires kubectl access."
        except Exception as e:
            return f"Error getting version: {str(e)}"
    
    async def _handle_config_command(self, command: str) -> str:
        """Handle kubectl config commands."""
        return """### Config Commands Not Supported

Config commands like `kubectl config` are not supported in this application for security reasons.

**Available config-related information:**
- Current context is automatically determined by the Kubernetes service configuration
- Authentication is handled through the configured service account or kubeconfig

**Note:** To manage kubectl configuration, use kubectl directly on a machine with appropriate access."""
    
    async def _get_api_resources(self) -> str:
        """Get available API resources."""
        try:
            # This is a simplified version - full API resources would require more complex calls
            resources = "### Available API Resources\n\n"
            resources += "**Supported in this application:**\n"
            resources += "- pods\n"
            resources += "- services\n"
            resources += "- deployments\n"
            resources += "- namespaces\n"
            resources += "- nodes\n\n"
            resources += "**Note:** This is a limited view. For complete API resources, use `kubectl api-resources` directly."
            return resources
        except Exception as e:
            return f"Error getting API resources: {str(e)}"
    
    async def _get_api_versions(self) -> str:
        """Get available API versions."""
        try:
            versions = "### Available API Versions\n\n"
            
            # Get core API version
            try:
                core_api = self.v1.api_client.configuration.host + "/api"
                versions += f"**Core API:** /api/v1\n"
            except:
                pass
            
            versions += "\n**Note:** This is a limited view. For complete API versions, use `kubectl api-versions` directly."
            return versions
        except Exception as e:
            return f"Error getting API versions: {str(e)}"
    
    # ... [Rest of the methods remain the same as before]
    # ... [_get_namespaces, _get_nodes, _describe_pod, _get_pods, _get_services, _get_deployments, _get_logs]
    # ... [All formatting methods remain the same]
    
    async def _get_namespaces(self, command: str, format_type: str) -> str:
        """Get namespaces information."""
        try:
            namespaces = self.v1.list_namespace()
            
            if format_type == "table":
                return self._format_namespaces_as_table(namespaces)
            elif format_type == "json":
                return json.dumps([self._namespace_to_dict(ns) for ns in namespaces.items], indent=2)
            else:  # yaml format
                return self._format_namespaces_as_yaml(namespaces)
                
        except ApiException as e:
            return f"Error getting namespaces: {e.reason}"
    
    async def _get_nodes(self, command: str, format_type: str) -> str:
        """Get nodes information."""
        try:
            nodes = self.v1.list_node()
            
            if format_type == "table":
                return self._format_nodes_as_table(nodes)
            elif format_type == "json":
                return json.dumps([self._node_to_dict(node) for node in nodes.items], indent=2)
            else:  # yaml format
                return self._format_nodes_as_yaml(nodes)
                
        except ApiException as e:
            return f"Error getting nodes: {e.reason}"
    
    async def _describe_pod(self, command: str, format_type: str) -> str:
        """Describe a specific pod."""
        # Parse pod name and namespace
        parts = command.split()
        pod_name = None
        namespace = "noticeboard"
        
        # Find pod name and namespace in the command
        # Skip the initial "kubectl describe pod" part
        command_part_index = 0
        
        # Skip past the command keywords
        for i, part in enumerate(parts):
            if part in ["kubectl", "describe", "pod"]:
                command_part_index = i + 1
            else:
                break
        
        # Now parse from after the command keywords
        skip_next = False
        for i in range(command_part_index, len(parts)):
            part = parts[i]
            
            if skip_next:
                skip_next = False
                continue
                
            if part in ["-n", "--namespace"] and i + 1 < len(parts):
                namespace = parts[i + 1]
                skip_next = True
            elif not part.startswith("--") and not part.startswith("-"):
                # This should be the pod name (first non-flag argument after command)
                pod_name = part
                break
        
        if not pod_name:
            return "Error: Pod name is required for describe command"
        
        # Debug logging
        logger.info(f"Attempting to describe pod: '{pod_name}' in namespace: '{namespace}'")
        
        try:
            pod = self.v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            
            # Format pod description
            description = f"### Pod Description: {pod_name}\n\n"
            description += f"**Namespace:** {pod.metadata.namespace}\n"
            description += f"**Status:** {pod.status.phase}\n"
            description += f"**Node:** {pod.spec.node_name or 'Not assigned'}\n"
            description += f"**Created:** {pod.metadata.creation_timestamp}\n"
            
            # Container information
            if pod.spec.containers:
                description += f"\n**Containers:**\n"
                for container in pod.spec.containers:
                    description += f"- **{container.name}**\n"
                    description += f"  - Image: {container.image}\n"
                    if container.resources:
                        if container.resources.requests:
                            description += f"  - Requests: {dict(container.resources.requests)}\n"
                        if container.resources.limits:
                            description += f"  - Limits: {dict(container.resources.limits)}\n"
            
            # Labels
            if pod.metadata.labels:
                description += f"\n**Labels:**\n"
                for key, value in pod.metadata.labels.items():
                    description += f"- {key}: {value}\n"
            
            # Annotations (first few)
            if pod.metadata.annotations:
                description += f"\n**Annotations (sample):**\n"
                # Show only first 5 annotations to avoid clutter
                for i, (key, value) in enumerate(pod.metadata.annotations.items()):
                    if i >= 5:
                        description += f"- ... and {len(pod.metadata.annotations) - 5} more\n"
                        break
                    # Truncate long values
                    display_value = value[:100] + "..." if len(value) > 100 else value
                    description += f"- {key}: {display_value}\n"
            
            # Conditions
            if pod.status.conditions:
                description += f"\n**Conditions:**\n"
                for condition in pod.status.conditions:
                    description += f"- {condition.type}: {condition.status}"
                    if condition.reason:
                        description += f" (Reason: {condition.reason})"
                    description += "\n"
            
            # Container statuses
            if pod.status.container_statuses:
                description += f"\n**Container Statuses:**\n"
                for status in pod.status.container_statuses:
                    description += f"- **{status.name}:**\n"
                    description += f"  - Ready: {status.ready}\n"
                    description += f"  - Restart Count: {status.restart_count}\n"
                    if status.state:
                        if status.state.running:
                            description += f"  - State: Running (since {status.state.running.started_at})\n"
                        elif status.state.waiting:
                            description += f"  - State: Waiting (reason: {status.state.waiting.reason})\n"
                        elif status.state.terminated:
                            description += f"  - State: Terminated (reason: {status.state.terminated.reason})\n"
            
            return description
            
        except ApiException as e:
            if e.status == 404:
                return f"Error describing pod {pod_name}: Pod not found in namespace '{namespace}'. Please check the pod name and namespace."
            else:
                return f"Error describing pod {pod_name}: {e.reason}"
        except Exception as e:
            return f"Error describing pod {pod_name}: {str(e)}"
    
    async def _get_pods(self, command: str, format_type: str) -> str:
        """Get pods information with server-side and client-side filtering fallback."""
        namespace = "default"
        label_selector = None
        field_selector = None
        all_namespaces = False
        client_side_filter = None
        
        # Check for --all-namespaces flag
        if "--all-namespaces" in command:
            all_namespaces = True
        
        # Parse specific namespace from command (only if not all-namespaces)
        if not all_namespaces and ("-n " in command or "--namespace " in command):
            parts = command.split()
            for i, part in enumerate(parts):
                if part in ["-n", "--namespace"] and i + 1 < len(parts):
                    namespace = parts[i + 1]
                    break
        
        # Parse label selector
        if "-l " in command or "--selector " in command:
            parts = command.split()
            for i, part in enumerate(parts):
                if part in ["-l", "--selector"] and i + 1 < len(parts):
                    label_selector = parts[i + 1]
                    break
        
        # Parse field selector
        if "--field-selector=" in command:
            parts = command.split("--field-selector=")
            if len(parts) > 1:
                # Extract the field selector value (until next space or end)
                original_field_selector = parts[1].split()[0]
                
                # Check if it's a negation that might not work server-side
                if "!=" in original_field_selector and "status.phase" in original_field_selector:
                    # Try server-side first, but prepare for client-side fallback
                    field_selector = original_field_selector
                    client_side_filter = original_field_selector
                else:
                    field_selector = original_field_selector
        
        try:
            # Get pods with server-side filtering
            if all_namespaces:
                pods = self.v1.list_pod_for_all_namespaces(
                    label_selector=label_selector,
                    field_selector=field_selector
                )
            else:
                pods = self.v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=label_selector,
                    field_selector=field_selector
                )
            
            # Check if server-side filtering worked
            if client_side_filter and field_selector:
                # Count pods by status to see if filtering worked
                status_counts = {}
                for pod in pods.items:
                    status = pod.status.phase
                    status_counts[status] = status_counts.get(status, 0) + 1
                
                # If we asked for non-Running pods but still got Running pods, server-side failed
                if "status.phase!=Running" in client_side_filter and status_counts.get("Running", 0) > 0:
                    logger.warning("Server-side field selector failed, falling back to client-side filtering")
                    
                    # Re-fetch without field selector and filter client-side
                    if all_namespaces:
                        pods = self.v1.list_pod_for_all_namespaces(label_selector=label_selector)
                    else:
                        pods = self.v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
                    
                    # Apply client-side filtering
                    if client_side_filter == "status.phase!=Running":
                        pods.items = [pod for pod in pods.items if pod.status.phase != "Running"]
                    elif client_side_filter == "status.phase!=Succeeded":
                        pods.items = [pod for pod in pods.items if pod.status.phase != "Succeeded"]
                    elif client_side_filter == "status.phase!=Failed":
                        pods.items = [pod for pod in pods.items if pod.status.phase != "Failed"]
                    else:
                        # Generic parsing for other != filters
                        if "status.phase!=" in client_side_filter:
                            exclude_status = client_side_filter.split("status.phase!=")[1]
                            pods.items = [pod for pod in pods.items if pod.status.phase != exclude_status]
            
            # Add a note about filtering method used
            result = ""
            if client_side_filter and len(pods.items) == 0:
                result += "**Note:** No pods found matching the filter criteria.\n\n"
            elif client_side_filter:
                # Check if client-side filtering was used
                has_excluded_status = any(pod.status.phase == client_side_filter.split("!=")[1] 
                                        for pod in pods.items if "!=" in client_side_filter)
                if not has_excluded_status:
                    result += "**Note:** Results filtered client-side due to API limitations.\n\n"
            
            if format_type == "table":
                result += self._format_pods_as_table(pods)
            elif format_type == "json":
                result += json.dumps([self._pod_to_dict(pod) for pod in pods.items], indent=2)
            else:  # yaml format
                result += self._format_pods_as_yaml(pods)
            
            return result
                
        except ApiException as e:
            logger.error(f"Kubernetes API error: {e}")
            return f"Error getting pods: {e.reason}. The field selector '{field_selector}' may not be supported by this Kubernetes version."
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return f"Error getting pods: {str(e)}"
    
    async def _get_services(self, command: str, format_type: str) -> str:
        """Get services information."""
        namespace = "default"
        all_namespaces = False
        field_selector = None
        
        # Check for --all-namespaces flag
        if "--all-namespaces" in command:
            all_namespaces = True
        
        # Parse specific namespace from command (only if not all-namespaces)
        if not all_namespaces and ("-n " in command or "--namespace " in command):
            parts = command.split()
            for i, part in enumerate(parts):
                if part in ["-n", "--namespace"] and i + 1 < len(parts):
                    namespace = parts[i + 1]
                    break
        
        # Parse field selector
        if "--field-selector=" in command:
            parts = command.split("--field-selector=")
            if len(parts) > 1:
                # Extract the field selector value (until next space or end)
                field_selector = parts[1].split()[0]
        
        try:
            if all_namespaces:
                # Get services from all namespaces
                services = self.v1.list_service_for_all_namespaces(field_selector=field_selector)
            else:
                # Get services from specific namespace
                services = self.v1.list_namespaced_service(namespace=namespace, field_selector=field_selector)
            
            if format_type == "table":
                return self._format_services_as_table(services)
            elif format_type == "json":
                return json.dumps([self._service_to_dict(svc) for svc in services.items], indent=2)
            else:  # yaml format
                return self._format_services_as_yaml(services)
                
        except ApiException as e:
            return f"Error getting services: {e.reason}"
    
    async def _get_deployments(self, command: str, format_type: str) -> str:
        """Get deployments information."""
        namespace = "default"
        all_namespaces = False
        field_selector = None
        
        # Check for --all-namespaces flag
        if "--all-namespaces" in command:
            all_namespaces = True
        
        # Parse specific namespace from command (only if not all-namespaces)
        if not all_namespaces and ("-n " in command or "--namespace " in command):
            parts = command.split()
            for i, part in enumerate(parts):
                if part in ["-n", "--namespace"] and i + 1 < len(parts):
                    namespace = parts[i + 1]
                    break
        
        # Parse field selector
        if "--field-selector=" in command:
            parts = command.split("--field-selector=")
            if len(parts) > 1:
                # Extract the field selector value (until next space or end)
                field_selector = parts[1].split()[0]
        
        try:
            if all_namespaces:
                # Get deployments from all namespaces
                deployments = self.apps_v1.list_deployment_for_all_namespaces(field_selector=field_selector)
            else:
                # Get deployments from specific namespace
                deployments = self.apps_v1.list_namespaced_deployment(namespace=namespace, field_selector=field_selector)
            
            if format_type == "table":
                return self._format_deployments_as_table(deployments)
            elif format_type == "json":
                return json.dumps([self._deployment_to_dict(deploy) for deploy in deployments.items], indent=2)
            else:  # yaml format
                return self._format_deployments_as_yaml(deployments)
                
        except ApiException as e:
            return f"Error getting deployments: {e.reason}"
    
    async def _get_logs(self, command: str, format_type: str) -> str:
        """Get pod logs."""
        # Parse pod name and namespace
        parts = command.split()
        pod_name = None
        namespace = "default"
        container = None
        lines = 100  # Default line limit
        
        for i, part in enumerate(parts):
            if part in ["-n", "--namespace"] and i + 1 < len(parts):
                namespace = parts[i + 1]
            elif part.startswith("--tail="):
                lines = int(part.split("=")[1])
            elif part not in ["get", "logs", "-n", "--namespace"] and not part.startswith("--"):
                pod_name = part
                break
        
        if not pod_name:
            return "Error: Pod name is required for logs command"
        
        try:
            logs = self.v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container,
                tail_lines=lines
            )
            
            return f"### Logs for pod {pod_name} (last {lines} lines)\n\n```\n{logs}\n```"
            
        except ApiException as e:
            return f"Error getting logs: {e.reason}"
    
    # ... (all the formatting methods stay the same)
    
    def _format_pods_as_table(self, pods) -> str:
        """Format pods as a markdown table."""
        if not pods.items:
            return "No pods found."
        
        table = "### Pods\n\n"
        table += "| Name | Namespace | Status | Restarts | Age |\n"
        table += "| --- | --- | --- | --- | --- |\n"
        
        for pod in pods.items:
            name = pod.metadata.name
            namespace = pod.metadata.namespace
            status = pod.status.phase
            
            # Calculate restarts
            restarts = 0
            if pod.status.container_statuses:
                restarts = sum(cs.restart_count for cs in pod.status.container_statuses)
            
            # Calculate age
            creation_time = pod.metadata.creation_timestamp
            age = self._calculate_age(creation_time)
            
            table += f"| {name} | {namespace} | {status} | {restarts} | {age} |\n"
        
        return table
    
    def _format_services_as_table(self, services) -> str:
        """Format services as a markdown table."""
        if not services.items:
            return "No services found."
        
        table = "### Services\n\n"
        table += "| Name | Namespace | Type | Cluster-IP | External-IP | Port(s) |\n"
        table += "| --- | --- | --- | --- | --- | --- |\n"
        
        for svc in services.items:
            name = svc.metadata.name
            namespace = svc.metadata.namespace
            svc_type = svc.spec.type
            cluster_ip = svc.spec.cluster_ip
            
            # External IP
            external_ip = "None"
            if svc.status.load_balancer and svc.status.load_balancer.ingress:
                external_ip = svc.status.load_balancer.ingress[0].ip or "Pending"
            
            # Ports
            ports = []
            if svc.spec.ports:
                for port in svc.spec.ports:
                    port_str = f"{port.port}"
                    if port.protocol != "TCP":
                        port_str += f"/{port.protocol}"
                    ports.append(port_str)
            ports_str = ",".join(ports) if ports else "None"
            
            table += f"| {name} | {namespace} | {svc_type} | {cluster_ip} | {external_ip} | {ports_str} |\n"
        
        return table
    
    def _format_namespaces_as_table(self, namespaces) -> str:
        """Format namespaces as a markdown table."""
        if not namespaces.items:
            return "No namespaces found."
        
        table = "### Namespaces\n\n"
        table += "| Name | Status | Age |\n"
        table += "| --- | --- | --- |\n"
        
        for ns in namespaces.items:
            name = ns.metadata.name
            status = ns.status.phase
            
            # Calculate age
            creation_time = ns.metadata.creation_timestamp
            age = self._calculate_age(creation_time)
            
            table += f"| {name} | {status} | {age} |\n"
        
        return table
    
    def _format_nodes_as_table(self, nodes) -> str:
        """Format nodes as a markdown table."""
        if not nodes.items:
            return "No nodes found."
        
        table = "### Nodes\n\n"
        table += "| Name | Status | Roles | Age | Version |\n"
        table += "| --- | --- | --- | --- | --- |\n"
        
        for node in nodes.items:
            name = node.metadata.name
            
            # Get status
            status = "Unknown"
            if node.status.conditions:
                for condition in node.status.conditions:
                    if condition.type == "Ready":
                        status = "Ready" if condition.status == "True" else "NotReady"
                        break
            
            # Get roles
            roles = []
            if node.metadata.labels:
                for key, value in node.metadata.labels.items():
                    if key.startswith("node-role.kubernetes.io/"):
                        role = key.split("/")[-1]
                        if role:
                            roles.append(role)
            roles_str = ",".join(roles) if roles else "worker"
            
            # Calculate age
            creation_time = node.metadata.creation_timestamp
            age = self._calculate_age(creation_time)
            
            # Get version
            version = node.status.node_info.kubelet_version if node.status.node_info else "Unknown"
            
            table += f"| {name} | {status} | {roles_str} | {age} | {version} |\n"
        
        return table
    
    def _format_deployments_as_table(self, deployments) -> str:
        """Format deployments as a markdown table."""
        if not deployments.items:
            return "No deployments found."
        
        table = "### Deployments\n\n"
        table += "| Name | Namespace | Ready | Up-to-date | Available | Age |\n"
        table += "| --- | --- | --- | --- | --- | --- |\n"
        
        for deploy in deployments.items:
            name = deploy.metadata.name
            namespace = deploy.metadata.namespace
            
            # Get replica counts
            replicas = deploy.spec.replicas or 0
            ready_replicas = deploy.status.ready_replicas or 0
            updated_replicas = deploy.status.updated_replicas or 0
            available_replicas = deploy.status.available_replicas or 0
            
            ready_str = f"{ready_replicas}/{replicas}"
            
            # Calculate age
            creation_time = deploy.metadata.creation_timestamp
            age = self._calculate_age(creation_time)
            
            table += f"| {name} | {namespace} | {ready_str} | {updated_replicas} | {available_replicas} | {age} |\n"
        
        return table
    
    def _calculate_age(self, creation_time) -> str:
        """Calculate age from creation timestamp."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        age = now - creation_time
        
        if age.days > 0:
            return f"{age.days}d"
        elif age.seconds > 3600:
            return f"{age.seconds // 3600}h"
        elif age.seconds > 60:
            return f"{age.seconds // 60}m"
        else:
            return f"{age.seconds}s"
        
    # Add these missing methods to the KubernetesService class

    async def _execute_generic_command(self, command: str, format_type: str) -> str:
        """Execute generic kubectl commands that don't match specific patterns."""
        return f"Command '{command}' is not yet supported. Please use one of the supported commands: get pods, get services, get deployments, get namespaces, get nodes, describe pod, or get logs."
    
    def _namespace_to_dict(self, namespace) -> dict:
        """Convert namespace object to dictionary."""
        return {
            "name": namespace.metadata.name,
            "status": namespace.status.phase,
            "creation_timestamp": namespace.metadata.creation_timestamp.isoformat() if namespace.metadata.creation_timestamp else None,
            "labels": namespace.metadata.labels or {}
        }
    
    def _node_to_dict(self, node) -> dict:
        """Convert node object to dictionary."""
        # Get status
        status = "Unknown"
        if node.status.conditions:
            for condition in node.status.conditions:
                if condition.type == "Ready":
                    status = "Ready" if condition.status == "True" else "NotReady"
                    break
        
        # Get roles
        roles = []
        if node.metadata.labels:
            for key, value in node.metadata.labels.items():
                if key.startswith("node-role.kubernetes.io/"):
                    role = key.split("/")[-1]
                    if role:
                        roles.append(role)
        
        return {
            "name": node.metadata.name,
            "status": status,
            "roles": roles if roles else ["worker"],
            "version": node.status.node_info.kubelet_version if node.status.node_info else "Unknown",
            "creation_timestamp": node.metadata.creation_timestamp.isoformat() if node.metadata.creation_timestamp else None
        }
    
    def _pod_to_dict(self, pod) -> dict:
        """Convert pod object to dictionary."""
        # Calculate restarts
        restarts = 0
        if pod.status.container_statuses:
            restarts = sum(cs.restart_count for cs in pod.status.container_statuses)
        
        return {
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "status": pod.status.phase,
            "restarts": restarts,
            "creation_timestamp": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None,
            "labels": pod.metadata.labels or {}
        }
    
    def _service_to_dict(self, service) -> dict:
        """Convert service object to dictionary."""
        # External IP
        external_ip = None
        if service.status.load_balancer and service.status.load_balancer.ingress:
            external_ip = service.status.load_balancer.ingress[0].ip
        
        # Ports
        ports = []
        if service.spec.ports:
            for port in service.spec.ports:
                port_dict = {
                    "port": port.port,
                    "protocol": port.protocol,
                    "target_port": port.target_port
                }
                if port.node_port:
                    port_dict["node_port"] = port.node_port
                ports.append(port_dict)
        
        return {
            "name": service.metadata.name,
            "namespace": service.metadata.namespace,
            "type": service.spec.type,
            "cluster_ip": service.spec.cluster_ip,
            "external_ip": external_ip,
            "ports": ports,
            "creation_timestamp": service.metadata.creation_timestamp.isoformat() if service.metadata.creation_timestamp else None
        }
    
    def _deployment_to_dict(self, deployment) -> dict:
        """Convert deployment object to dictionary."""
        return {
            "name": deployment.metadata.name,
            "namespace": deployment.metadata.namespace,
            "replicas": deployment.spec.replicas or 0,
            "ready_replicas": deployment.status.ready_replicas or 0,
            "updated_replicas": deployment.status.updated_replicas or 0,
            "available_replicas": deployment.status.available_replicas or 0,
            "creation_timestamp": deployment.metadata.creation_timestamp.isoformat() if deployment.metadata.creation_timestamp else None
        }
    
    def _format_pods_as_yaml(self, pods) -> str:
        """Format pods as YAML."""
        if not pods.items:
            return "No pods found."
        
        yaml_content = "### Pods (YAML)\n\n```yaml\n"
        for pod in pods.items:
            pod_dict = self._pod_to_dict(pod)
            yaml_content += yaml.dump([pod_dict], default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content
    
    def _format_services_as_yaml(self, services) -> str:
        """Format services as YAML."""
        if not services.items:
            return "No services found."
        
        yaml_content = "### Services (YAML)\n\n```yaml\n"
        for svc in services.items:
            svc_dict = self._service_to_dict(svc)
            yaml_content += yaml.dump([svc_dict], default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content
    
    def _format_deployments_as_yaml(self, deployments) -> str:
        """Format deployments as YAML."""
        if not deployments.items:
            return "No deployments found."
        
        yaml_content = "### Deployments (YAML)\n\n```yaml\n"
        for deploy in deployments.items:
            deploy_dict = self._deployment_to_dict(deploy)
            yaml_content += yaml.dump([deploy_dict], default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content
    
    def _format_namespaces_as_yaml(self, namespaces) -> str:
        """Format namespaces as YAML."""
        if not namespaces.items:
            return "No namespaces found."
        
        yaml_content = "### Namespaces (YAML)\n\n```yaml\n"
        for ns in namespaces.items:
            ns_dict = self._namespace_to_dict(ns)
            yaml_content += yaml.dump([ns_dict], default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content
    
    def _format_nodes_as_yaml(self, nodes) -> str:
        """Format nodes as YAML."""
        if not nodes.items:
            return "No nodes found."
        
        yaml_content = "### Nodes (YAML)\n\n```yaml\n"
        for node in nodes.items:
            node_dict = self._node_to_dict(node)
            yaml_content += yaml.dump([node_dict], default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content
    
    async def _get_cluster_info(self) -> str:
        """Get cluster information using available APIs."""
        try:
            # Get some basic cluster information
            info = "### Cluster Information\n\n"
            
            # Get nodes summary
            try:
                nodes = self.v1.list_node()
                info += f"**Nodes:** {len(nodes.items)} total\n"
                
                # Count nodes by status
                ready_nodes = 0
                for node in nodes.items:
                    if node.status.conditions:
                        for condition in node.status.conditions:
                            if condition.type == "Ready" and condition.status == "True":
                                ready_nodes += 1
                                break
                
                info += f"**Ready Nodes:** {ready_nodes}/{len(nodes.items)}\n"
            except Exception as e:
                info += f"**Nodes:** Error retrieving node information: {str(e)}\n"
            
            # Get namespaces summary
            try:
                namespaces = self.v1.list_namespace()
                info += f"**Namespaces:** {len(namespaces.items)} total\n"
            except Exception as e:
                info += f"**Namespaces:** Error retrieving namespace information: {str(e)}\n"
            
            # Get API server info
            try:
                # Get the API server endpoint from client configuration
                host = self.v1.api_client.configuration.host
                info += f"**API Server:** {host}\n"
            except Exception as e:
                info += f"**API Server:** Unable to retrieve endpoint information\n"
            
            info += "\n**Note:** This is a limited cluster info view using available Kubernetes APIs. For complete cluster-info including endpoints and certificates, use `kubectl cluster-info` directly on a machine with cluster access."
            return info
            
        except Exception as e:
            return f"Error getting cluster info: {str(e)}"
    
    async def _get_version(self) -> str:
        """Get Kubernetes version information."""
        try:
            info = "### Kubernetes Version Information\n\n"
            
            # Get client version from configuration
            try:
                info += f"**Client API Version:** Using Kubernetes Python client\n"
            except:
                info += f"**Client API Version:** Unable to determine\n"
            
            # Attempt to get server version through API calls
            try:
                # Get version info by making a generic API call
                response = self.v1.api_client.call_api(
                    '/version', 'GET',
                    response_type='object',
                    auth_settings=['BearerToken']
                )
                if response and len(response) > 0:
                    version_data = response[0]
                    info += f"**Server Version:** {version_data.get('gitVersion', 'Unknown')}\n"
                    info += f"**Go Version:** {version_data.get('goVersion', 'Unknown')}\n"
                    info += f"**Platform:** {version_data.get('platform', 'Unknown')}\n"
            except:
                info += f"**Server Version:** Unable to retrieve server version through API\n"
            
            info += "\n**Note:** For complete version information including build details, use `kubectl version` directly."
            return info
            
        except Exception as e:
            return f"Error getting version: {str(e)}"
    
    async def _handle_config_command(self, command: str) -> str:
        """Handle kubectl config commands."""
        return """### Config Commands

**Status:** Config commands like `kubectl config` are not available through the Kubernetes Python client.

**Reason:** Configuration management requires direct access to kubectl binary and local kubeconfig files.

**Available Information:**
- The application uses the configured Kubernetes context automatically
- Authentication is handled through service accounts or kubeconfig files
- Context switching and cluster management must be done externally

**Note:** To manage kubectl configuration, use kubectl directly on a machine with appropriate access."""
    
    async def _get_api_resources(self) -> str:
        """Get available API resources."""
        try:
            resources = "### API Resources\n\n"
            resources += "**Directly Supported Resources:**\n"
            resources += "- pods (v1)\n"
            resources += "- services (v1)\n"
            resources += "- deployments (apps/v1)\n"
            resources += "- namespaces (v1)\n"
            resources += "- nodes (v1)\n\n"
            
            # Try to get additional API groups
            try:
                # This is a simplified approach - the full API discovery is complex
                resources += "**Available API Groups:**\n"
                resources += "- core (v1)\n"
                resources += "- apps (v1)\n"
                resources += "- networking.k8s.io (v1)\n"
                resources += "- storage.k8s.io (v1)\n"
                resources += "- batch (v1)\n\n"
            except:
                pass
            
            resources += "**Note:** This is a limited view of API resources. For complete API resource discovery including CRDs and all API groups, use `kubectl api-resources` directly."
            return resources
        except Exception as e:
            return f"Error getting API resources: {str(e)}"
    
    async def _get_api_versions(self) -> str:
        """Get available API versions."""
        try:
            versions = "### API Versions\n\n"
            
            try:
                # Get available versions through client configuration
                versions += "**Supported API Versions:**\n"
                versions += "- v1 (Core API)\n"
                versions += "- apps/v1\n"
                versions += "- networking.k8s.io/v1\n"
                versions += "- storage.k8s.io/v1\n"
                versions += "- batch/v1\n\n"
            except:
                versions += "**API Versions:** Unable to enumerate all versions\n\n"
            
            versions += "**Note:** This is a static list of commonly available API versions. For a complete and dynamic list of all API versions including cluster-specific APIs, use `kubectl api-versions` directly."
            return versions
        except Exception as e:
            return f"Error getting API versions: {str(e)}"


# Enhanced script discriminator service
class ScriptDiscriminator:
    @staticmethod
    def detect_script_type(text: str) -> tuple[str, str]:
        """
        Detect whether the text contains PromQL or Kubernetes commands.
        Returns (script_type, extracted_script) where script_type is 'promql' or 'kubernetes' or 'unknown'
        """
        text_lower = text.lower().strip()
        
        # PromQL patterns
        promql_patterns = [
            r'\b(rate|sum|avg|max|min|count|histogram_quantile|increase)\s*\(',
            r'\[[\d]+[smhd]\]',  # Time ranges like [5m], [1h]
            r'\{[^}]*\}',  # Label selectors
            r'by\s*\([^)]+\)',  # Group by
            r'without\s*\([^)]+\)',  # Group without
        ]
        
        # Kubernetes command patterns
        k8s_patterns = [
            r'\b(kubectl|get|describe|logs|apply|delete|create)\b',
            r'\b(pods|pod|services|svc|deployments|deploy|nodes|ns|namespaces)\b',
            r'\b-n\s+\w+|\b--namespace\s+\w+',  # Namespace flags
            r'\b-l\s+\w+|\b--selector\s+\w+',  # Label selectors
        ]
        
        # Check for PromQL
        promql_matches = sum(1 for pattern in promql_patterns if re.search(pattern, text_lower))
        
        # Check for Kubernetes
        k8s_matches = sum(1 for pattern in k8s_patterns if re.search(pattern, text_lower))
        
        # Extract potential scripts from code blocks
        code_blocks = re.findall(r'```(?:promql|yaml|bash)?\n?(.*?)\n?```', text, re.DOTALL | re.IGNORECASE)
        
        # If we have code blocks, analyze them
        if code_blocks:
            for block in code_blocks:
                block_lower = block.lower().strip()
                block_promql_matches = sum(1 for pattern in promql_patterns if re.search(pattern, block_lower))
                block_k8s_matches = sum(1 for pattern in k8s_patterns if re.search(pattern, block_lower))
                
                if block_promql_matches > block_k8s_matches:
                    return "promql", block.strip()
                elif block_k8s_matches > block_promql_matches:
                    return "kubernetes", block.strip()
        
        # If no code blocks, check the entire text
        if promql_matches > k8s_matches and promql_matches > 0:
            return "promql", text.strip()
        elif k8s_matches > promql_matches and k8s_matches > 0:
            return "kubernetes", text.strip()
        else:
            return "unknown", text.strip()

# Service for handling predefined commands
class CommandService:
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

# Service for Prometheus integration (keeping existing code)
class PrometheusService:
    @staticmethod
    async def execute_query(query: str, format_type: str = "default") -> str:
        """Execute a PromQL query against Prometheus and return the results."""
        if not PROMETHEUS_URL:
            return "Error: Prometheus URL is not configured. Please contact the administrator."
            
        logger.info(f"Executing PromQL query: {query} with format: {format_type}")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{PROMETHEUS_URL}/api/v1/query",
                    params={"query": query},
                    timeout=10.0
                )
                
                response.raise_for_status()
                data = response.json()
                
                if data["status"] == "success":
                    result_type = data["data"]["resultType"]
                    results = data["data"]["result"]
                    
                    if not results:
                        return "The query returned no results."
                    
                    # Handle vector results (most common)
                    if result_type == "vector":
                        if format_type == "table":
                            return PrometheusService._format_vector_as_table(query, results)
                        elif format_type == "json":
                            return f"### Prometheus Query Results\n\nQuery: `{query}`\n\n```json\n{results}\n```"
                        else:  # default format
                            formatted_results = "### Prometheus Query Results\n\n"
                            formatted_results += f"Query: `{query}`\n\n"
                            
                            for i, result in enumerate(results, 1):
                                # Format labels
                                labels = result.get("metric", {})
                                label_str = ", ".join([f"{k}={v}" for k, v in labels.items()])
                                
                                # Format value
                                value = result.get("value", [])
                                if len(value) >= 2:
                                    timestamp, metric_value = value
                                    # Try to make the value more readable
                                    try:
                                        # Convert scientific notation to readable format if needed
                                        metric_value = float(metric_value)
                                        if abs(metric_value) < 0.001 or abs(metric_value) > 100000:
                                            formatted_value = f"{metric_value:.6e}"
                                        else:
                                            formatted_value = f"{metric_value:.6f}".rstrip('0').rstrip('.')
                                    except ValueError:
                                        formatted_value = str(metric_value)
                                    
                                    formatted_results += f"**Result {i}:** {label_str}\n"
                                    formatted_results += f"**Value:** {formatted_value}\n\n"
                            
                            return formatted_results
                    
                    # Handle other result types
                    elif result_type == "matrix":
                        if format_type == "table":
                            return PrometheusService._format_matrix_as_table(query, results)
                        else:
                            formatted_results = "### Prometheus Range Query Results\n\n"
                            formatted_results += f"Query: `{query}`\n\n"
                            formatted_results += "Results are in matrix format. Please use a specific instant query for more readable results."
                            return formatted_results
                    
                    # Handle scalar and other result types
                    else:
                        formatted_results = f"### Prometheus Results ({result_type})\n\n"
                        formatted_results += f"Query: `{query}`\n\n"
                        formatted_results += f"```\n{results}\n```"
                        return formatted_results
                else:
                    return f"Error executing query: {data.get('error', 'Unknown error')}"
        except Exception as e:
            logger.error(f"Error executing Prometheus query: {str(e)}")
            return f"Error executing query: {str(e)}"
    
    @staticmethod
    def _format_vector_as_table(query: str, results: list) -> str:
        """Format vector results as a Markdown table."""
        if not results:
            return "The query returned no results."
            
        # Extract all unique label keys from all metrics
        all_label_keys = set()
        for result in results:
            labels = result.get("metric", {})
            all_label_keys.update(labels.keys())
            
        # Sort the label keys for consistent presentation
        sorted_label_keys = sorted(all_label_keys)
        
        # Start building the table
        formatted_results = f"### Prometheus Query Results\n\n"
        formatted_results += f"Query: `{query}`\n\n"
        
        # Table header
        header = "| "
        for key in sorted_label_keys:
            header += f"{key} | "
        header += "Value |\n"
        
        # Table separator
        separator = "| "
        for _ in range(len(sorted_label_keys)):
            separator += "--- | "
        separator += "--- |\n"
        
        # Table rows
        rows = ""
        for result in results:
            labels = result.get("metric", {})
            value = result.get("value", [])
            
            row = "| "
            for key in sorted_label_keys:
                row += f"{labels.get(key, '')} | "
                
            # Format value
            if len(value) >= 2:
                _, metric_value = value
                try:
                    # Convert scientific notation to readable format if needed
                    metric_value = float(metric_value)
                    if abs(metric_value) < 0.001 or abs(metric_value) > 100000:
                        formatted_value = f"{metric_value:.6e}"
                    else:
                        formatted_value = f"{metric_value:.6f}".rstrip('0').rstrip('.')
                except ValueError:
                    formatted_value = str(metric_value)
                    
                row += f"{formatted_value} |\n"
            else:
                row += "N/A |\n"
                
            rows += row
            
        # Combine all parts of the table
        formatted_results += header + separator + rows
        
        # Add a warning if the table might be wide
        if len(sorted_label_keys) > 5:
            formatted_results += "\n**Note:** This table contains many columns and may not display well on small screens.\n"
            
        return formatted_results
    
    @staticmethod
    def _format_matrix_as_table(query: str, results: list) -> str:
        """Format matrix results as a table (simplified view)."""
        if not results:
            return "The query returned no results."
            
        return "Matrix results are complex time series. Consider using an instant query instead."

# Enhanced ChatGPT service with script detection and routing
class ChatGPTService:
    request_count = 0
    max_retries = 3
    
    @staticmethod
    async def get_response(message: str, system_prompt: str = None) -> str:
        """Get response from ChatGPT with retry logic and rate limiting."""
        if not OPENAI_API_KEY:
            return "Error: OpenAI API key is not configured. Please contact the administrator."
            
        logger.info(f"Sending message to ChatGPT: {message}")
        
        # Increment request counter (simple rate limiting)
        ChatGPTService.request_count += 1
        
        # Basic rate limiting - skip if too many recent requests
        if ChatGPTService.request_count > 45:  # Adjust based on your rate limits
            logger.warning("Rate limit preemptively applied")
            ChatGPTService.request_count = max(0, ChatGPTService.request_count - 5)  # Decay mechanism
            return "I'm getting too many requests right now. Please try again in a few moments."
        
        # Default system prompt if none provided
        if system_prompt is None:
            system_prompt = """You are a helpful assistant integrated with Mattermost. Keep responses concise and under 2000 characters.
            
When users ask about monitoring, metrics, or Prometheus, provide PromQL queries in code blocks.
When users ask about Kubernetes, pods, services, deployments, or kubectl commands, provide the appropriate kubectl commands in code blocks.
Always format your scripts in code blocks with the appropriate language tag (```promql or ```bash).
"""
        
        # Implement retry with exponential backoff
        retry_delay = 1  # Starting delay in seconds
        
        for attempt in range(ChatGPTService.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {OPENAI_API_KEY}",
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
                if e.response.status_code == 429:  # Too Many Requests
                    if attempt < ChatGPTService.max_retries - 1:
                        logger.warning(f"Rate limit hit, retrying in {retry_delay} seconds (attempt {attempt+1}/{ChatGPTService.max_retries})")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        logger.error("Rate limit persisted after max retries")
                        return "I'm currently experiencing high demand. Please try again in a few minutes."
                else:
                    logger.error(f"HTTP error from OpenAI API: {e.response.status_code}")
                    return f"Sorry, there was an issue with the AI service (HTTP {e.response.status_code}). Please try again later."
                    
            except httpx.RequestError as e:
                logger.error(f"Request error connecting to OpenAI: {str(e)}")
                return "Sorry, I couldn't connect to the AI service. Please check your internet connection and try again."
                
            except Exception as e:
                logger.error(f"Unexpected error with ChatGPT: {str(e)}")
                return "Sorry, an unexpected error occurred. Please try again with a simpler question."
            
    # Alternative approach: Client-side filtering when server-side doesn't work
    async def _get_pods_with_client_side_filtering(self, command: str, format_type: str) -> str:
        """Get pods with client-side filtering as fallback."""
        namespace = "default"
        label_selector = None
        field_selector = None
        all_namespaces = False
        client_side_filter = None
        
        # Parse command as before...
        if "--all-namespaces" in command:
            all_namespaces = True
        
        if "--field-selector=" in command:
            parts = command.split("--field-selector=")
            if len(parts) > 1:
                field_selector = parts[1].split()[0]
                
                # Check if it's a != operator that might not work server-side
                if "!=" in field_selector:
                    client_side_filter = field_selector
                    field_selector = None  # Don't pass to server
        
        try:
            # Get all pods first
            if all_namespaces:
                pods = self.v1.list_pod_for_all_namespaces(
                    label_selector=label_selector,
                    field_selector=field_selector
                )
            else:
                # Parse namespace...
                pods = self.v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=label_selector,
                    field_selector=field_selector
                )
            
            # Apply client-side filtering if needed
            if client_side_filter:
                filtered_pods = []
                
                if client_side_filter == "status.phase!=Running":
                    filtered_pods = [pod for pod in pods.items if pod.status.phase != "Running"]
                elif client_side_filter == "status.phase!=Succeeded":
                    filtered_pods = [pod for pod in pods.items if pod.status.phase != "Succeeded"]
                elif client_side_filter == "status.phase!=Failed":
                    filtered_pods = [pod for pod in pods.items if pod.status.phase != "Failed"]
                else:
                    # Generic parsing for other != filters
                    if "status.phase!=" in client_side_filter:
                        exclude_status = client_side_filter.split("status.phase!=")[1]
                        filtered_pods = [pod for pod in pods.items if pod.status.phase != exclude_status]
                
                # Create a new object with filtered items
                pods.items = filtered_pods
            
            if format_type == "table":
                return self._format_pods_as_table(pods)
            elif format_type == "json":
                return json.dumps([self._pod_to_dict(pod) for pod in pods.items], indent=2)
            else:  # yaml format
                return self._format_pods_as_yaml(pods)
                
        except ApiException as e:
            return f"Error getting pods: {e.reason}"
    
# Service for sending messages back to Mattermost
class MattermostService:
    @staticmethod
    async def send_response(channel_id: str, message: str) -> None:
        """Send a response back to Mattermost."""
        if not MATTERMOST_URL or not MATTERMOST_BOT_TOKEN:
            raise ValueError("Mattermost URL or token is not set")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{MATTERMOST_URL}/api/v4/posts",
                    headers={
                        "Authorization": f"Bearer {MATTERMOST_BOT_TOKEN}",
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

# Initialize services
kubernetes_service = KubernetesService()
prometheus_service = PrometheusService()
chatgpt_service = ChatGPTService()
mattermost_service = MattermostService()
script_discriminator = ScriptDiscriminator()

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
    if MATTERMOST_WEBHOOK_TOKEN and token != MATTERMOST_WEBHOOK_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    logger.info(f"Received slash command: {command} with text: {text} from user: {user_name}")
    
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
    
    # Natural language query - generates and executes appropriate commands
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
    command_service = CommandService()
    response = command_service.process_command(text)
    
    if response is not None:
        return MattermostResponse(text=response)
    
    # For any other text, process with ChatGPT and then route appropriately
    asyncio.create_task(process_with_chatgpt_and_route(text, channel_id, user_name, response_url))
    return MattermostResponse(
        text="Processing your request... I'll respond shortly.",
        response_type="ephemeral"
    )

async def process_kubernetes_command(kubectl_command: str, channel_id: str, user_name: str, response_url: str, format_type: str = "table"):
    """Process a Kubernetes command in the background and send response when ready."""
    try:
        logger.info("k8s Command : ", kubectl_command, ", format_type : ", format_type);
        # Execute kubectl command
        results = await kubernetes_service.execute_kubectl_command(kubectl_command, format_type)
        
        # Format response
        formatted_response = f"@{user_name} requested kubectl: \"{kubectl_command}\"\n\n{results}"
        
        # Send response back to Mattermost
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
    """Process natural language query - let ChatGPT generate the appropriate script and execute it."""
    try:
        # First, ask ChatGPT to generate the appropriate script
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
        
        # Get response from ChatGPT
        chatgpt_response = await chatgpt_service.get_response(query, system_prompt)
        
        # Detect and extract the script
        script_type, extracted_script = script_discriminator.detect_script_type(chatgpt_response)
        
        logger.info(f"Detected script type: {script_type}, Script: {extracted_script}")
        
        # Execute the detected script
        if script_type == "promql":
            # Execute PromQL query
            results = await prometheus_service.execute_query(extracted_script, format_type)
            formatted_response = (
                f"@{user_name} asked: \"{query}\"\n\n"
                f"**Generated PromQL:** `{extracted_script}`\n\n"
                f"{results}"
            )
        elif script_type == "kubernetes":
            # Execute kubectl command
            results = await kubernetes_service.execute_kubectl_command(extracted_script, format_type)
            formatted_response = (
                f"@{user_name} asked: \"{query}\"\n\n"
                f"**Generated kubectl command:** `{extracted_script}`\n\n"
                f"{results}"
            )
        else:
            # If we can't detect the script type, just return ChatGPT's response
            formatted_response = (
                f"@{user_name} asked: \"{query}\"\n\n"
                f"{chatgpt_response}"
            )
        
        # Send response back to Mattermost
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
        # Get response from ChatGPT
        chatgpt_response = await chatgpt_service.get_response(text)
        
        # Check if ChatGPT generated any executable scripts
        script_type, extracted_script = script_discriminator.detect_script_type(chatgpt_response)
        
        logger.info(f"ChatGPT response received. Detected script type: {script_type}")
        
        if script_type == "promql":
            # Execute the PromQL query
            prometheus_results = await prometheus_service.execute_query(extracted_script, "table")
            formatted_response = (
                f"@{user_name} asked: \"{text}\"\n\n"
                f"**ChatGPT's response:** {chatgpt_response}\n\n"
                f"**Detected PromQL query:** `{extracted_script}`\n\n"
                f"**Execution results:**\n{prometheus_results}"
            )
        elif script_type == "kubernetes":
            # Execute the kubectl command
            k8s_results = await kubernetes_service.execute_kubectl_command(extracted_script, "table")
            formatted_response = (
                f"@{user_name} asked: \"{text}\"\n\n"
                f"**ChatGPT's response:** {chatgpt_response}\n\n"
                f"**Detected kubectl command:** `{extracted_script}`\n\n"
                f"**Execution results:**\n{k8s_results}"
            )
        else:
            # No executable script detected, just return ChatGPT's response
            formatted_response = f"@{user_name} asked: \"{text}\"\n\n{chatgpt_response}"
        
        # Send response back to Mattermost
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

async def process_prometheus_query(query: str, channel_id: str, user_name: str, response_url: str, format_type: str = "table"):
    """Process a Prometheus query in the background and send response when ready."""
    try:
        # Get response from Prometheus
        response = await prometheus_service.execute_query(query, format_type)
        
        # Format response
        formatted_response = f"@{user_name} requested metrics: \"{query}\"\n\n{response}"
        
        # Send response back to Mattermost
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

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "services": {
            "prometheus": "configured" if PROMETHEUS_URL else "not configured",
            "kubernetes": "initialized" if kubernetes_service.v1 else "not initialized",
            "openai": "configured" if OPENAI_API_KEY else "not configured",
            "mattermost": "configured" if MATTERMOST_URL and MATTERMOST_BOT_TOKEN else "not configured"
        }
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8999))
    uvicorn.run("main:app", host="localhost", port=port, reload=True)