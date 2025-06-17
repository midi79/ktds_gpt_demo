"""Kubernetes service for executing kubectl-like commands."""
import logging
import os
import yaml
import subprocess
import shlex
import re
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from app.config import config as app_config

logger = logging.getLogger(__name__)

class KubernetesService:
    """Service for interacting with Kubernetes cluster."""
    
    def __init__(self):
        """Initialize Kubernetes client with proper error handling."""
        self.v1 = None
        self.apps_v1 = None
        self.client_initialized = False
        
        # Security: Define allowed kubectl commands
        self.allowed_kubectl_commands = {
            'get', 'describe', 'logs', 'cluster-info', 'version', 
            'config', 'api-resources', 'api-versions', 'top'
        }
        
        self.enable_subprocess = app_config.ENABLE_KUBECTL_SUBPROCESS
        self.kubectl_path = app_config.KUBECTL_PATH
        
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
            
            # Strategy 2: Try custom kubeconfig path if specified
            if app_config.KUBERNETES_CONFIG_PATH and os.path.exists(app_config.KUBERNETES_CONFIG_PATH):
                try:
                    config.load_kube_config(config_file=app_config.KUBERNETES_CONFIG_PATH)
                    logger.info(f"Loaded Kubernetes configuration from: {app_config.KUBERNETES_CONFIG_PATH}")
                    self._setup_api_clients()
                    return
                except Exception as e:
                    logger.warning(f"Custom kubeconfig failed: {e}")
            
            # Strategy 3: Try default kubeconfig
            try:
                config.load_kube_config()
                logger.info("Loaded default Kubernetes configuration")
                self._setup_api_clients()
                return
            except Exception as e:
                logger.warning(f"Default kubeconfig failed: {e}")
            
            logger.error("Failed to initialize Kubernetes client with any method")
            
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
            self.client_initialized = False
    
    def is_client_available(self) -> bool:
        """Check if Kubernetes client is properly initialized."""
        return self.client_initialized and self.v1 is not None
    
    async def execute_kubectl_command(self, command: str, format_type: str = "yaml") -> str:
        """Execute kubectl-like commands using the Kubernetes Python client."""
        if not self.is_client_available():
            if self.enable_subprocess:
                logger.info("Kubernetes client not available, using subprocess fallback")
                return await self._execute_kubectl_via_subprocess(command, format_type)
            else:
                return self._get_client_unavailable_message()
        
        try:
            original_command = command.strip()
            command_lower = command.strip().lower()
            parts = command_lower.split()
            
            if not parts:
                return "Error: Empty command"
            
            if parts[0] == "kubectl":
                parts = parts[1:]
                command_lower = " ".join(parts)
            
            if not parts:
                return "Error: No command specified after 'kubectl'"
            
            verb = parts[0] if parts else ""
            resource = parts[1] if len(parts) > 1 else ""
            
            # Route to appropriate handler
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
            
            if self.enable_subprocess:
                return await self._execute_kubectl_via_subprocess(original_command, format_type)
            else:
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
4. Verify cluster connectivity and permissions"""
    
    async def _execute_kubectl_via_subprocess(self, command: str, format_type: str = "yaml") -> str:
        """Execute kubectl command via subprocess with security measures."""
        if not self._is_safe_kubectl_command(command):
            return f"Error: Command '{command}' is not allowed for security reasons."
        
        try:
            parts = shlex.split(command)
            if not parts or parts[0].lower() != "kubectl":
                parts.insert(0, self.kubectl_path)
            else:
                parts[0] = self.kubectl_path
            
            if format_type == "json" and "--output" not in command and "-o" not in command:
                parts.extend(["--output", "json"])
            elif format_type == "yaml" and "--output" not in command and "-o" not in command:
                parts.extend(["--output", "yaml"])
            
            logger.info(f"Executing kubectl via subprocess: {' '.join(parts)}")
            result = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.getcwd()
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if not output:
                    return "Command executed successfully but returned no output."
                
                if format_type == "table" and not any(flag in command for flag in ["-o", "--output"]):
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
        
        if parts[0] == "kubectl":
            parts = parts[1:]
        
        if not parts:
            return False
        
        main_verb = parts[0]
        if main_verb not in self.allowed_kubectl_commands:
            logger.warning(f"Blocked unsafe kubectl command: {main_verb}")
            return False
        
        dangerous_patterns = [
            r'delete\s+', r'apply\s+', r'create\s+', r'patch\s+',
            r'edit\s+', r'exec\s+', r'cp\s+', r'auth\s+'
        ]
        
        for pattern in dangerous_patterns:
            if re.search(pattern, normalized):
                logger.warning(f"Blocked dangerous kubectl command: {command}")
                return False
        
        shell_chars = ['&', '|', ';', '`', '$', '<', '>', '(', ')', '{', '}']
        if any(char in command for char in shell_chars):
            logger.warning(f"Blocked kubectl command with shell metacharacters: {command}")
            return False
        
        return True
    
    async def _handle_unsupported_command(self, command: str) -> str:
        """Provide helpful information about unsupported commands."""
        return f"""### Command Not Supported: {command}

**Supported Operations:**
- Resource listing: `get pods`, `get services`, `get deployments`, `get namespaces`, `get nodes`
- Resource description: `describe pod <name>`
- Log retrieval: `logs <pod-name>`

**Note:** For advanced kubectl commands, enable subprocess execution with ENABLE_KUBECTL_SUBPROCESS=true"""
    
    # Core kubectl functionality methods
    async def _get_pods(self, command: str, format_type: str) -> str:
        """Get pods information with support for field selectors."""
        from app.utils.formatters import K8sFormatter
        
        namespace = "default"
        all_namespaces = False
        label_selector = None
        field_selector = None
        client_side_filter = None
        
        if "--all-namespaces" in command:
            all_namespaces = True
        
        if not all_namespaces and ("-n " in command or "--namespace " in command):
            parts = command.split()
            for i, part in enumerate(parts):
                if part in ["-n", "--namespace"] and i + 1 < len(parts):
                    namespace = parts[i + 1]
                    break
        
        if "-l " in command or "--selector " in command:
            parts = command.split()
            for i, part in enumerate(parts):
                if part in ["-l", "--selector"] and i + 1 < len(parts):
                    label_selector = parts[i + 1]
                    break
        
        if "--field-selector=" in command:
            parts = command.split("--field-selector=")
            if len(parts) > 1:
                field_selector_value = parts[1].split()[0].strip('\'"') # FIX: Strip quotes
                
                if "!=" in field_selector_value and "status.phase" in field_selector_value:
                    client_side_filter = field_selector_value
                    field_selector = None
                    logger.info(f"Using client-side filtering for: {field_selector_value}")
                else:
                    field_selector = field_selector_value
        
        try:
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
            
            if client_side_filter:
                original_count = len(pods.items)
                
                if client_side_filter == "status.phase!=Running":
                    pods.items = [pod for pod in pods.items if pod.status.phase != "Running"]
                elif client_side_filter == "status.phase!=Succeeded":
                    pods.items = [pod for pod in pods.items if pod.status.phase != "Succeeded"]
                elif client_side_filter == "status.phase!=Failed":
                    pods.items = [pod for pod in pods.items if pod.status.phase != "Failed"]
                else:
                    if "status.phase!=" in client_side_filter:
                        exclude_status = client_side_filter.split("status.phase!=")[1]
                        pods.items = [pod for pod in pods.items if pod.status.phase != exclude_status]
                
                filtered_count = len(pods.items)
                logger.info(f"Client-side filtering: {original_count} -> {filtered_count} pods")
            
            result = ""
            if client_side_filter:
                result += f"**Note:** Filtered {len(pods.items)} pods client-side (field-selector '{client_side_filter}' not supported server-side)\n\n"
            
            formatter = K8sFormatter()
            if format_type == "table":
                result += formatter.format_pods_as_table(pods)
            else:
                result += formatter.format_pods_as_yaml(pods)
            
            return result
                
        except ApiException as e:
            logger.error(f"Kubernetes API error: {e}")
            return f"Error getting pods: {e.reason}"
    
    async def _get_services(self, command: str, format_type: str) -> str:
        """Get services information."""
        from app.utils.formatters import K8sFormatter
        
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
            
            formatter = K8sFormatter()
            if format_type == "table":
                return formatter.format_services_as_table(services)
            else:
                return formatter.format_services_as_yaml(services)
                
        except ApiException as e:
            return f"Error getting services: {e.reason}"
    
    async def _get_deployments(self, command: str, format_type: str) -> str:
        """Get deployments information."""
        from app.utils.formatters import K8sFormatter
        
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
            
            formatter = K8sFormatter()
            if format_type == "table":
                return formatter.format_deployments_as_table(deployments)
            else:
                return formatter.format_deployments_as_yaml(deployments)
                
        except ApiException as e:
            return f"Error getting deployments: {e.reason}"
    
    async def _get_namespaces(self, command: str, format_type: str) -> str:
        """Get namespaces information."""
        from app.utils.formatters import K8sFormatter
        
        try:
            namespaces = self.v1.list_namespace()
            
            formatter = K8sFormatter()
            if format_type == "table":
                return formatter.format_namespaces_as_table(namespaces)
            else:
                return formatter.format_namespaces_as_yaml(namespaces)
                
        except ApiException as e:
            return f"Error getting namespaces: {e.reason}"
    
    async def _get_nodes(self, command: str, format_type: str) -> str:
        """Get nodes information."""
        from app.utils.formatters import K8sFormatter
        
        try:
            nodes = self.v1.list_node()
            
            formatter = K8sFormatter()
            if format_type == "table":
                return formatter.format_nodes_as_table(nodes)
            else:
                return formatter.format_nodes_as_yaml(nodes)
                
        except ApiException as e:
            return f"Error getting nodes: {e.reason}"
    
    async def _describe_pod(self, command: str, format_type: str) -> str:
        """Describe a specific pod with corrected parsing."""
        parts = command.split()
        pod_name = None
        namespace = "default"

        # Correctly parse pod_name and namespace regardless of order
        # Find pod name (first argument after 'pod' that is not a flag)
        pod_keyword_index = -1
        if 'pod' in parts:
            pod_keyword_index = parts.index('pod')
        elif 'pods' in parts:
            pod_keyword_index = parts.index('pods')

        if pod_keyword_index != -1 and pod_keyword_index + 1 < len(parts):
            if not parts[pod_keyword_index + 1].startswith('-'):
                pod_name = parts[pod_keyword_index + 1]

        # Find namespace
        for i, part in enumerate(parts):
            if part in ["-n", "--namespace"] and i + 1 < len(parts):
                namespace = parts[i + 1]
                break
        
        if not pod_name:
            return "Error: Pod name not found in describe command."

        try:
            pod_obj = self.v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            
            # Fetch recent events for the pod, which is crucial for debugging
            events_str = "No events found."
            try:
                events = self.v1.list_namespaced_event(
                    namespace=namespace,
                    field_selector=f"involvedObject.name={pod_name}"
                )
                if events.items:
                    event_list = [
                        f"- **Type**: {e.type}, **Reason**: {e.reason}, **Message**: {e.message}"
                        for e in sorted(events.items, key=lambda e: e.last_timestamp, reverse=True)[:10] # Get last 10 events
                    ]
                    events_str = "\n".join(event_list)
            except ApiException as e:
                logger.warning(f"Could not fetch events for pod {pod_name}: {e.reason}")
                events_str = "Could not fetch events."


            # Return a summary similar to `kubectl describe`
            return (
                f"### Pod Description: {pod_name}\n\n"
                f"**Namespace:** `{pod_obj.metadata.namespace}`\n"
                f"**Status:** `{pod_obj.status.phase}`\n"
                f"**Node:** `{pod_obj.spec.node_name or 'Not assigned'}`\n"
                f"**Created:** `{pod_obj.metadata.creation_timestamp}`\n\n"
                f"#### Recent Events\n{events_str}"
            )

        except ApiException as e:
            if e.status == 404:
                return f"Error: Pod '{pod_name}' not found in namespace '{namespace}'"
            else:
                logger.error(f"API Error describing pod: {e.reason}")
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
                if (i > 0 and parts[i-1] not in ["-n", "--namespace"]):
                     pod_name = part

        if not pod_name:
             # Fallback if parsing fails
            if parts and not parts[-1].startswith('-'):
                 pod_name = parts[-1]

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