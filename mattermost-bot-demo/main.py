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
import subprocess
import shlex
import re
from typing import Optional

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

# Kubernetes Service - Complete Implementation
class KubernetesService:
    def __init__(self):
        """Initialize Kubernetes client with proper error handling."""
        # Initialize all attributes first
        self.v1 = None
        self.apps_v1 = None
        self.client_initialized = False
        
        # Security: Define allowed kubectl commands to prevent command injection
        self.allowed_kubectl_commands = {
            'get', 'describe', 'logs', 'cluster-info', 'version', 
            'config', 'api-resources', 'api-versions', 'top'
        }
        
        # Enable/disable subprocess execution (set to False by default for security)
        self.enable_subprocess = os.getenv("ENABLE_KUBECTL_SUBPROCESS", "false").lower() == "true"
        
        # Path to kubectl binary (should be in PATH or specify full path)
        self.kubectl_path = os.getenv("KUBECTL_PATH", "kubectl")
        
        # Try to initialize Kubernetes client
        self._initialize_kubernetes_client()
    
    def _initialize_kubernetes_client(self):
        """Initialize Kubernetes client with multiple fallback strategies."""
        try:
            # Strategy 1: Try to load in-cluster config first
            try:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes configuration")
                self._setup_api_clients()
                return
            except config.ConfigException:
                logger.info("In-cluster config not available")
                pass
            
            # Strategy 2: Try custom kubeconfig path if specified
            if KUBERNETES_CONFIG_PATH and os.path.exists(KUBERNETES_CONFIG_PATH):
                try:
                    config.load_kube_config(config_file=KUBERNETES_CONFIG_PATH)
                    logger.info(f"Loaded Kubernetes configuration from: {KUBERNETES_CONFIG_PATH}")
                    self._setup_api_clients()
                    return
                except Exception as e:
                    logger.warning(f"Custom kubeconfig failed: {e}")
                    pass
            
            # Strategy 3: Try default kubeconfig
            try:
                config.load_kube_config()
                logger.info("Loaded default Kubernetes configuration")
                self._setup_api_clients()
                return
            except Exception as e:
                logger.warning(f"Default kubeconfig failed: {e}")
                pass
            
            # If all strategies fail
            logger.error("Failed to initialize Kubernetes client with any method")
            logger.info("Kubernetes operations will fall back to subprocess if enabled")
            
        except Exception as e:
            logger.error(f"Unexpected error during Kubernetes client initialization: {str(e)}")
    
    def _setup_api_clients(self):
        """Setup API clients after successful configuration loading."""
        try:
            self.v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.client_initialized = True
            logger.info("Kubernetes API clients initialized successfully")
        except Exception as e:
            logger.error(f"Failed to setup API clients: {str(e)}")
            self.v1 = None
            self.client_initialized = False
    
    def is_client_available(self) -> bool:
        """Check if Kubernetes client is properly initialized."""
        return self.client_initialized and self.v1 is not None
    
    async def execute_kubectl_command(self, command: str, format_type: str = "yaml") -> str:
        """Execute kubectl-like commands using the Kubernetes Python client or subprocess fallback."""
        # Check if client is available
        if not self.is_client_available():
            if self.enable_subprocess:
                logger.info("Kubernetes client not available, using subprocess fallback")
                return await self._execute_kubectl_via_subprocess(command, format_type)
            else:
                return self._get_client_unavailable_message()
        
        try:
            # Store original command for reference
            original_command = command.strip()
            
            # Use lowercase version ONLY for command detection
            command_lower = command.strip().lower()
            parts = command_lower.split()
            
            if not parts:
                return "Error: Empty command"
            
            # Remove 'kubectl' from the beginning if present
            if parts[0] == "kubectl":
                parts = parts[1:]
                command_lower = " ".join(parts)
            
            if not parts:
                return "Error: No command specified after 'kubectl'"
            
            # Parse the main command structure
            verb = parts[0] if parts else ""
            resource = parts[1] if len(parts) > 1 else ""
            
            # Try Python client first for supported commands
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
            
            elif verb == "describe":
                if resource in ["pod", "pods"]:
                    return await self._describe_pod(original_command, format_type)
            
            elif verb == "logs":
                return await self._get_logs(original_command, format_type)
            
            # For commands not supported by Python client, try subprocess
            if self.enable_subprocess:
                return await self._execute_kubectl_via_subprocess(original_command, format_type)
            else:
                # Return helpful message for unsupported commands
                return await self._handle_unsupported_command(original_command)
                
        except Exception as e:
            return f"Error executing kubectl command: {str(e)}"
    
    def _get_client_unavailable_message(self) -> str:
        """Return message when Kubernetes client is not available."""
        return """### Kubernetes Client Not Available

**Status:** The Kubernetes Python client failed to initialize.

**Possible causes:**
- No kubeconfig file found
- Invalid cluster credentials
- Network connectivity issues
- Missing cluster access permissions

**Solutions:**
1. Check if kubeconfig exists at ~/.kube/config
2. Set KUBERNETES_CONFIG_PATH environment variable
3. Enable subprocess execution with ENABLE_KUBECTL_SUBPROCESS=true
4. Verify cluster connectivity and permissions

**Note:** Some commands may still work if subprocess execution is enabled."""
    
    async def _execute_kubectl_via_subprocess(self, command: str, format_type: str = "yaml") -> str:
        """Execute kubectl command via subprocess with security measures."""
        # Security check: validate command
        if not self._is_safe_kubectl_command(command):
            return f"Error: Command '{command}' is not allowed for security reasons."
        
        try:
            # Parse command to ensure it starts with kubectl
            parts = shlex.split(command)
            if not parts or parts[0].lower() != "kubectl":
                parts.insert(0, self.kubectl_path)
            else:
                parts[0] = self.kubectl_path
            
            # Add output format if not specified
            if format_type == "json" and "--output" not in command and "-o" not in command:
                parts.extend(["--output", "json"])
            elif format_type == "yaml" and "--output" not in command and "-o" not in command:
                parts.extend(["--output", "yaml"])
            
            # Execute command with timeout
            logger.info(f"Executing kubectl via subprocess: {' '.join(parts)}")
            result = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                cwd=os.getcwd()
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if not output:
                    return "Command executed successfully but returned no output."
                
                # Format output based on type
                if format_type == "table" and not any(flag in command for flag in ["-o", "--output"]):
                    return f"### kubectl Command: {command}\n\n```\n{output}\n```"
                elif format_type == "json":
                    try:
                        parsed = json.loads(output)
                        return f"### kubectl Command: {command}\n\n```json\n{json.dumps(parsed, indent=2)}\n```"
                    except json.JSONDecodeError:
                        return f"### kubectl Command: {command}\n\n```\n{output}\n```"
                else:
                    return f"### kubectl Command: {command}\n\n```yaml\n{output}\n```"
            else:
                error_output = result.stderr.strip()
                return f"Error executing command '{command}':\n```\n{error_output}\n```"
                
        except subprocess.TimeoutExpired:
            return f"Error: Command '{command}' timed out after 30 seconds."
        except Exception as e:
            logger.error(f"Subprocess execution error: {str(e)}")
            return f"Error executing command via subprocess: {str(e)}"
    
    def _is_safe_kubectl_command(self, command: str) -> bool:
        """Validate that the kubectl command is safe to execute."""
        normalized = command.strip().lower()
        parts = shlex.split(normalized)
        
        if not parts:
            return False
        
        # Skip 'kubectl' if it's the first word
        if parts[0] == "kubectl":
            parts = parts[1:]
        
        if not parts:
            return False
        
        # Check if the main verb is allowed
        main_verb = parts[0]
        if main_verb not in self.allowed_kubectl_commands:
            logger.warning(f"Blocked unsafe kubectl command: {main_verb}")
            return False
        
        # Block dangerous commands explicitly
        dangerous_patterns = [
            r'delete\s+', r'apply\s+', r'create\s+', r'patch\s+',
            r'edit\s+', r'exec\s+', r'cp\s+', r'auth\s+'
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, normalized):
                logger.warning(f"Blocked dangerous kubectl command: {command}")
                return False
        
        # Check for shell metacharacters
        shell_chars = ['&', '|', ';', '`', '$', '<', '>', '(', ')', '{', '}']
        if any(char in command for char in shell_chars):
            logger.warning(f"Blocked kubectl command with shell metacharacters: {command}")
            return False
        
        return True
    
    async def _handle_unsupported_command(self, command: str) -> str:
        """Provide helpful information about unsupported commands."""
        return f"""### Command Not Supported: {command}

**Status:** This command is not available through the Kubernetes Python client.

**Supported Operations:**
- Resource listing: `get pods`, `get services`, `get deployments`, `get namespaces`, `get nodes`
- Resource description: `describe pod <n>`
- Log retrieval: `logs <pod-name>`

**Note:** For advanced kubectl commands, enable subprocess execution with ENABLE_KUBECTL_SUBPROCESS=true or use kubectl directly."""
    
    # Core kubectl functionality methods
    async def _get_pods(self, command: str, format_type: str) -> str:
        """Get pods information with support for field selectors."""
        namespace = "default"
        all_namespaces = False
        label_selector = None
        field_selector = None
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
        
        # Parse field selector and handle != operators that don't work server-side
        if "--field-selector=" in command:
            parts = command.split("--field-selector=")
            if len(parts) > 1:
                # Extract the field selector value (until next space or end)
                field_selector_value = parts[1].split()[0]
                
                # Check if it's a negation that might not work server-side
                if "!=" in field_selector_value and "status.phase" in field_selector_value:
                    # Don't send the != filter to server, handle client-side instead
                    client_side_filter = field_selector_value
                    field_selector = None
                    logger.info(f"Using client-side filtering for: {field_selector_value}")
                else:
                    field_selector = field_selector_value
        
        try:
            # Get pods with server-side filtering (if applicable)
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
            
            # Apply client-side filtering if needed
            if client_side_filter:
                original_count = len(pods.items)
                
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
                
                filtered_count = len(pods.items)
                logger.info(f"Client-side filtering: {original_count} -> {filtered_count} pods")
            
            # Format response with optional filtering note
            result = ""
            if client_side_filter:
                result += f"**Note:** Filtered {len(pods.items)} pods client-side (field-selector '{client_side_filter}' not supported server-side)\n\n"
            
            if format_type == "table":
                result += self._format_pods_as_table(pods)
            elif format_type == "json":
                result += json.dumps([self._pod_to_dict(pod) for pod in pods.items], indent=2)
            else:
                result += self._format_pods_as_yaml(pods)
            
            return result
                
        except ApiException as e:
            logger.error(f"Kubernetes API error: {e}")
            return f"Error getting pods: {e.reason}. Field selector '{field_selector}' may not be supported by this Kubernetes version."
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return f"Error getting pods: {str(e)}"
    
    async def _get_services(self, command: str, format_type: str) -> str:
        """Get services information."""
        namespace = "default"
        all_namespaces = False
        
        if "--all-namespaces" in command:
            all_namespaces = True
        
        if not all_namespaces and ("-n " in command or "--namespace " in command):
            parts = command.split()
            for i, part in enumerate(parts):
                if part in ["-n", "--namespace"] and i + 1 < len(parts):
                    namespace = parts[i + 1]
                    break
        
        try:
            if all_namespaces:
                services = self.v1.list_service_for_all_namespaces()
            else:
                services = self.v1.list_namespaced_service(namespace=namespace)
            
            if format_type == "table":
                return self._format_services_as_table(services)
            elif format_type == "json":
                return json.dumps([self._service_to_dict(svc) for svc in services.items], indent=2)
            else:
                return self._format_services_as_yaml(services)
                
        except ApiException as e:
            return f"Error getting services: {e.reason}"
    
    async def _get_deployments(self, command: str, format_type: str) -> str:
        """Get deployments information."""
        namespace = "default"
        all_namespaces = False
        
        if "--all-namespaces" in command:
            all_namespaces = True
        
        if not all_namespaces and ("-n " in command or "--namespace " in command):
            parts = command.split()
            for i, part in enumerate(parts):
                if part in ["-n", "--namespace"] and i + 1 < len(parts):
                    namespace = parts[i + 1]
                    break
        
        try:
            if all_namespaces:
                deployments = self.apps_v1.list_deployment_for_all_namespaces()
            else:
                deployments = self.apps_v1.list_namespaced_deployment(namespace=namespace)
            
            if format_type == "table":
                return self._format_deployments_as_table(deployments)
            elif format_type == "json":
                return json.dumps([self._deployment_to_dict(deploy) for deploy in deployments.items], indent=2)
            else:
                return self._format_deployments_as_yaml(deployments)
                
        except ApiException as e:
            return f"Error getting deployments: {e.reason}"
    
    async def _get_namespaces(self, command: str, format_type: str) -> str:
        """Get namespaces information."""
        try:
            namespaces = self.v1.list_namespace()
            
            if format_type == "table":
                return self._format_namespaces_as_table(namespaces)
            elif format_type == "json":
                return json.dumps([self._namespace_to_dict(ns) for ns in namespaces.items], indent=2)
            else:
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
            else:
                return self._format_nodes_as_yaml(nodes)
                
        except ApiException as e:
            return f"Error getting nodes: {e.reason}"
    
    async def _describe_pod(self, command: str, format_type: str) -> str:
        """Describe a specific pod."""
        parts = command.split()
        pod_name = None
        namespace = "default"
        
        # Parse pod name and namespace
        skip_next = False
        for i, part in enumerate(parts):
            if skip_next:
                skip_next = False
                continue
                
            if part in ["-n", "--namespace"] and i + 1 < len(parts):
                namespace = parts[i + 1]
                skip_next = True
            elif not part.startswith("-") and part not in ["kubectl", "describe", "pod"]:
                pod_name = part
                break
        
        if not pod_name:
            return "Error: Pod name is required for describe command"
        
        try:
            pod = self.v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            
            description = f"### Pod Description: {pod_name}\n\n"
            description += f"**Namespace:** {pod.metadata.namespace}\n"
            description += f"**Status:** {pod.status.phase}\n"
            description += f"**Node:** {pod.spec.node_name or 'Not assigned'}\n"
            description += f"**Created:** {pod.metadata.creation_timestamp}\n"
            
            # Container information
            if pod.spec.containers:
                description += f"\n**Containers:**\n"
                for container in pod.spec.containers:
                    description += f"- **{container.name}**: {container.image}\n"
            
            return description
            
        except ApiException as e:
            if e.status == 404:
                return f"Pod '{pod_name}' not found in namespace '{namespace}'"
            else:
                return f"Error describing pod: {e.reason}"
    
    async def _get_logs(self, command: str, format_type: str) -> str:
        """Get pod logs."""
        parts = command.split()
        pod_name = None
        namespace = "default"
        lines = 100
        
        for i, part in enumerate(parts):
            if part in ["-n", "--namespace"] and i + 1 < len(parts):
                namespace = parts[i + 1]
            elif part.startswith("--tail="):
                lines = int(part.split("=")[1])
            elif part not in ["kubectl", "logs", "-n", "--namespace"] and not part.startswith("--"):
                pod_name = part
                break
        
        if not pod_name:
            return "Error: Pod name is required for logs command"
        
        try:
            logs = self.v1.read_namespaced_pod_log(
                name=pod_name, 
                namespace=namespace, 
                tail_lines=lines
            )
            return f"### Logs for pod {pod_name} (last {lines} lines)\n\n```\n{logs}\n```"
            
        except ApiException as e:
            return f"Error getting logs: {e.reason}"
    
    # Formatting methods
    def _format_pods_as_table(self, pods) -> str:
        """Format pods as a markdown table."""
        if not pods.items:
            return "No pods found matching the criteria."
        
        table = "### Pods\n\n"
        table += "| Name | Namespace | Status | Age |\n"
        table += "| --- | --- | --- | --- |\n"
        
        for pod in pods.items:
            name = pod.metadata.name
            namespace = pod.metadata.namespace
            status = pod.status.phase
            age = self._calculate_age(pod.metadata.creation_timestamp)
            table += f"| {name} | {namespace} | **{status}** | {age} |\n"
        
        # Add summary
        status_counts = {}
        for pod in pods.items:
            status = pod.status.phase
            status_counts[status] = status_counts.get(status, 0) + 1
        
        if status_counts:
            table += f"\n**Summary:** "
            summary_parts = []
            for status, count in sorted(status_counts.items()):
                summary_parts.append(f"{count} {status}")
            table += ", ".join(summary_parts)
        
        return table
    
    def _format_services_as_table(self, services) -> str:
        """Format services as a markdown table."""
        if not services.items:
            return "No services found."
        
        table = "### Services\n\n"
        table += "| Name | Namespace | Type | Cluster-IP | Port(s) |\n"
        table += "| --- | --- | --- | --- | --- |\n"
        
        for svc in services.items:
            name = svc.metadata.name
            namespace = svc.metadata.namespace
            svc_type = svc.spec.type
            cluster_ip = svc.spec.cluster_ip
            
            ports = []
            if svc.spec.ports:
                for port in svc.spec.ports:
                    ports.append(f"{port.port}/{port.protocol}")
            ports_str = ",".join(ports) if ports else "None"
            
            table += f"| {name} | {namespace} | {svc_type} | {cluster_ip} | {ports_str} |\n"
        
        return table
    
    def _format_deployments_as_table(self, deployments) -> str:
        """Format deployments as a markdown table."""
        if not deployments.items:
            return "No deployments found."
        
        table = "### Deployments\n\n"
        table += "| Name | Namespace | Ready | Age |\n"
        table += "| --- | --- | --- | --- |\n"
        
        for deploy in deployments.items:
            name = deploy.metadata.name
            namespace = deploy.metadata.namespace
            replicas = deploy.spec.replicas or 0
            ready_replicas = deploy.status.ready_replicas or 0
            ready_str = f"{ready_replicas}/{replicas}"
            age = self._calculate_age(deploy.metadata.creation_timestamp)
            table += f"| {name} | {namespace} | {ready_str} | {age} |\n"
        
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
            age = self._calculate_age(ns.metadata.creation_timestamp)
            table += f"| {name} | {status} | {age} |\n"
        
        return table
    
    def _format_nodes_as_table(self, nodes) -> str:
        """Format nodes as a markdown table."""
        if not nodes.items:
            return "No nodes found."
        
        table = "### Nodes\n\n"
        table += "| Name | Status | Age | Version |\n"
        table += "| --- | --- | --- | --- |\n"
        
        for node in nodes.items:
            name = node.metadata.name
            status = "Unknown"
            if node.status.conditions:
                for condition in node.status.conditions:
                    if condition.type == "Ready":
                        status = "Ready" if condition.status == "True" else "NotReady"
                        break
            
            age = self._calculate_age(node.metadata.creation_timestamp)
            version = node.status.node_info.kubelet_version if node.status.node_info else "Unknown"
            table += f"| {name} | {status} | {age} | {version} |\n"
        
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
    
    # Dictionary conversion methods for JSON/YAML output
    def _pod_to_dict(self, pod) -> dict:
        """Convert pod object to dictionary."""
        return {
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "status": pod.status.phase,
            "creation_timestamp": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None
        }
    
    def _service_to_dict(self, service) -> dict:
        """Convert service object to dictionary."""
        return {
            "name": service.metadata.name,
            "namespace": service.metadata.namespace,
            "type": service.spec.type,
            "cluster_ip": service.spec.cluster_ip,
            "creation_timestamp": service.metadata.creation_timestamp.isoformat() if service.metadata.creation_timestamp else None
        }
    
    def _deployment_to_dict(self, deployment) -> dict:
        """Convert deployment object to dictionary."""
        return {
            "name": deployment.metadata.name,
            "namespace": deployment.metadata.namespace,
            "replicas": deployment.spec.replicas or 0,
            "ready_replicas": deployment.status.ready_replicas or 0,
            "creation_timestamp": deployment.metadata.creation_timestamp.isoformat() if deployment.metadata.creation_timestamp else None
        }
    
    def _namespace_to_dict(self, namespace) -> dict:
        """Convert namespace object to dictionary."""
        return {
            "name": namespace.metadata.name,
            "status": namespace.status.phase,
            "creation_timestamp": namespace.metadata.creation_timestamp.isoformat() if namespace.metadata.creation_timestamp else None
        }
    
    def _node_to_dict(self, node) -> dict:
        """Convert node object to dictionary."""
        status = "Unknown"
        if node.status.conditions:
            for condition in node.status.conditions:
                if condition.type == "Ready":
                    status = "Ready" if condition.status == "True" else "NotReady"
                    break
        
        return {
            "name": node.metadata.name,
            "status": status,
            "version": node.status.node_info.kubelet_version if node.status.node_info else "Unknown",
            "creation_timestamp": node.metadata.creation_timestamp.isoformat() if node.metadata.creation_timestamp else None
        }
    
    # YAML formatting methods
    def _format_pods_as_yaml(self, pods) -> str:
        """Format pods as YAML."""
        if not pods.items:
            return "No pods found."
        
        yaml_content = "### Pods (YAML)\n\n```yaml\n"
        for pod in pods.items:
            pod_dict = self._pod_to_dict(pod)
            yaml_content += yaml.dump(pod_dict, default_flow_style=False)
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
            yaml_content += yaml.dump(svc_dict, default_flow_style=False)
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
            yaml_content += yaml.dump(deploy_dict, default_flow_style=False)
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
            yaml_content += yaml.dump(ns_dict, default_flow_style=False)
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
            yaml_content += yaml.dump(node_dict, default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content
    
# Enhanced script discriminator service
class ScriptDiscriminator:
    @staticmethod
    def detect_script_type(text: str) -> tuple[str, str]:
        """
        Detect whether the text contains PromQL or Kubernetes commands.
        Returns (script_type, extracted_script) where script_type is 'promql' or 'kubernetes' or 'unknown'
        """
        text_lower = text.lower().strip()
        
        # PromQL patterns - improved to catch filesystem queries
        promql_patterns = [
            r'\b(rate|sum|avg|max|min|count|histogram_quantile|increase)\s*\(',
            r'\[[\d]+[smhd]\]',  # Time ranges like [5m], [1h]
            r'\{[^}]*\}',  # Label selectors
            r'by\s*\([^)]+\)',  # Group by
            r'without\s*\([^)]+\)',  # Group without
            r'node_filesystem_',  # Node filesystem metrics
            r'node_memory_',  # Node memory metrics
            r'node_cpu_',  # Node CPU metrics
            r'container_memory_',  # Container metrics
            r'up\s*\{',  # Up metrics with labels
            r'_total\s*$',  # Metrics ending with _total
            r'_bytes\s*/',  # Metrics with _bytes (common in filesystem queries)
        ]
        
        # Kubernetes command patterns
        k8s_patterns = [
            r'\b(kubectl|get|describe|logs|apply|delete|create)\b',
            r'\b(pods|pod|services|svc|deployments|deploy|nodes|ns|namespaces)\b',
            r'\b-n\s+\w+|\b--namespace\s+\w+',  # Namespace flags
            r'\b-l\s+\w+|\b--selector\s+\w+',  # Label selectors
            r'\b--field-selector\b',  # Field selectors
        ]
        
        # First check for code blocks with language hints
        code_blocks = re.findall(r'```(?:(promql|yaml|bash|sh|kubectl))?\n?(.*?)\n?```', text, re.DOTALL | re.IGNORECASE)
        
        if code_blocks:
            for lang_hint, block in code_blocks:
                block_clean = block.strip()
                
                # If explicitly tagged as promql
                if lang_hint and lang_hint.lower() == 'promql':
                    return "promql", block_clean
                    
                # If explicitly tagged as bash/kubectl
                if lang_hint and lang_hint.lower() in ['bash', 'sh', 'kubectl']:
                    return "kubernetes", block_clean
                
                # Analyze content if no explicit language tag
                if not lang_hint and block_clean:
                    # Check if it looks like a single-line metric query
                    if any(re.search(pattern, block_clean, re.IGNORECASE) for pattern in promql_patterns):
                        return "promql", block_clean
                    elif any(re.search(pattern, block_clean, re.IGNORECASE) for pattern in k8s_patterns):
                        return "kubernetes", block_clean
        
        # If no code blocks, analyze the entire text
        # Count pattern matches
        promql_matches = sum(1 for pattern in promql_patterns if re.search(pattern, text_lower))
        k8s_matches = sum(1 for pattern in k8s_patterns if re.search(pattern, text_lower))
        
        # Special checks for common cases
        # Check for filesystem queries specifically
        if 'filesystem' in text_lower and any(word in text_lower for word in ['avail', 'size', 'used', 'free']):
            # Extract the potential PromQL query from the text
            lines = text.strip().split('\n')
            for line in lines:
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in promql_patterns):
                    return "promql", line.strip()
        
        # Make decision based on matches
        if promql_matches > k8s_matches and promql_matches > 0:
            # Try to extract the metric query from text
            lines = text.strip().split('\n')
            for line in lines:
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in promql_patterns):
                    return "promql", line.strip()
            return "promql", text.strip()
        elif k8s_matches > promql_matches and k8s_matches > 0:
            # Try to extract kubectl command
            lines = text.strip().split('\n')
            for line in lines:
                if 'kubectl' in line.lower():
                    return "kubernetes", line.strip()
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
        
        # Enhanced system prompt for better Korean and filesystem query handling
        if system_prompt is None:
            system_prompt = """You are a helpful assistant integrated with Mattermost. Keep responses concise and under 2000 characters.

When users ask about monitoring, metrics, or Prometheus (in any language including Korean):
- Always provide PromQL queries in code blocks with ```promql
- For filesystem questions (파일시스템, 디스크, 저장공간), use node_filesystem metrics
- Example filesystem query: ```promql
node_filesystem_avail_bytes{fstype!="tmpfs"} / node_filesystem_size_bytes{fstype!="tmpfs"} * 100
```

When users ask about Kubernetes, pods, services, deployments, or kubectl commands:
- Provide kubectl commands in code blocks with ```bash
- For Korean requests about pods (파드), nodes (노드), services (서비스), use appropriate kubectl commands

Always format your scripts in properly tagged code blocks.
Respond in Korean when the user writes in Korean."""
        
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


# Enhanced processing function for better script detection
async def process_with_chatgpt_and_route(text: str, channel_id: str, user_name: str, response_url: str):
    """Process request with ChatGPT and automatically route any generated scripts."""
    try:
        # Get response from ChatGPT
        chatgpt_response = await chatgpt_service.get_response(text)
        
        # Check if ChatGPT generated any executable scripts
        script_type, extracted_script = script_discriminator.detect_script_type(chatgpt_response)
        
        logger.info(f"ChatGPT response received. Detected script type: {script_type}, Script: {extracted_script}")
        
        if script_type == "promql":
            # Clean up the PromQL query - remove any trailing text
            cleaned_script = extracted_script.split('\n')[0].strip()
            if cleaned_script:
                # Execute the PromQL query
                prometheus_results = await prometheus_service.execute_query(cleaned_script, "table")
                formatted_response = (
                    f"@{user_name} asked: \"{text}\"\n\n"
                    f"**ChatGPT's response:** {chatgpt_response}\n\n"
                    f"**Detected PromQL query:** `{cleaned_script}`\n\n"
                    f"**Execution results:**\n{prometheus_results}"
                )
            else:
                # Fallback if script extraction failed
                formatted_response = f"@{user_name} asked: \"{text}\"\n\n{chatgpt_response}"
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


# Configuration class for managing subprocess settings
class SubprocessConfig:
    @staticmethod
    def enable_subprocess_execution():
        """Enable subprocess execution - use with caution!"""
        os.environ["ENABLE_KUBECTL_SUBPROCESS"] = "true"
        logger.warning("Subprocess execution for kubectl has been ENABLED. This may pose security risks.")
    
    @staticmethod
    def disable_subprocess_execution():
        """Disable subprocess execution (default and recommended)"""
        os.environ["ENABLE_KUBECTL_SUBPROCESS"] = "false"
        logger.info("Subprocess execution for kubectl has been disabled.")
    
    @staticmethod
    def set_kubectl_path(path: str):
        """Set custom path to kubectl binary"""
        os.environ["KUBECTL_PATH"] = path
        logger.info(f"kubectl path set to: {path}")

@app.get("/health")
async def health_check():
    """Health check endpoint with subprocess status."""
    subprocess_enabled = os.getenv("ENABLE_KUBECTL_SUBPROCESS", "false").lower() == "true"
    
    return {
        "status": "healthy",
        "services": {
            "prometheus": "configured" if PROMETHEUS_URL else "not configured",
            "kubernetes": "initialized" if kubernetes_service.v1 else "not initialized",
            "openai": "configured" if OPENAI_API_KEY else "not configured",
            "mattermost": "configured" if MATTERMOST_URL and MATTERMOST_BOT_TOKEN else "not configured",
            "kubectl_subprocess": "enabled" if subprocess_enabled else "disabled (recommended)"
        },
        "kubectl_path": os.getenv("KUBECTL_PATH", "kubectl")
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8999))
    uvicorn.run("main:app", host="localhost", port=port, reload=True)