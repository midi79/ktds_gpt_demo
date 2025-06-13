"""Formatting utilities for Kubernetes resources."""
import yaml
import json
from datetime import datetime, timezone

class K8sFormatter:
    """Formatter for Kubernetes resources."""
    
    def _calculate_age(self, creation_time) -> str:
        """Calculate age from creation timestamp."""
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
    
    def format_pods_as_table(self, pods) -> str:
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
    
    def format_pods_as_yaml(self, pods) -> str:
        """Format pods as YAML."""
        if not pods.items:
            return "No pods found."
        
        yaml_content = "### Pods (YAML)\n\n```yaml\n"
        for pod in pods.items:
            pod_dict = {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "creation_timestamp": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None
            }
            yaml_content += yaml.dump(pod_dict, default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content
    
    def format_services_as_table(self, services) -> str:
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
    
    def format_services_as_yaml(self, services) -> str:
        """Format services as YAML."""
        if not services.items:
            return "No services found."
        
        yaml_content = "### Services (YAML)\n\n```yaml\n"
        for svc in services.items:
            svc_dict = {
                "name": svc.metadata.name,
                "namespace": svc.metadata.namespace,
                "type": svc.spec.type,
                "cluster_ip": svc.spec.cluster_ip,
                "creation_timestamp": svc.metadata.creation_timestamp.isoformat() if svc.metadata.creation_timestamp else None
            }
            yaml_content += yaml.dump(svc_dict, default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content
    
    def format_deployments_as_table(self, deployments) -> str:
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
    
    def format_deployments_as_yaml(self, deployments) -> str:
        """Format deployments as YAML."""
        if not deployments.items:
            return "No deployments found."
        
        yaml_content = "### Deployments (YAML)\n\n```yaml\n"
        for deploy in deployments.items:
            deploy_dict = {
                "name": deploy.metadata.name,
                "namespace": deploy.metadata.namespace,
                "replicas": deploy.spec.replicas or 0,
                "ready_replicas": deploy.status.ready_replicas or 0,
                "creation_timestamp": deploy.metadata.creation_timestamp.isoformat() if deploy.metadata.creation_timestamp else None
            }
            yaml_content += yaml.dump(deploy_dict, default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content
    
    def format_namespaces_as_table(self, namespaces) -> str:
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
    
    def format_namespaces_as_yaml(self, namespaces) -> str:
        """Format namespaces as YAML."""
        if not namespaces.items:
            return "No namespaces found."
        
        yaml_content = "### Namespaces (YAML)\n\n```yaml\n"
        for ns in namespaces.items:
            ns_dict = {
                "name": ns.metadata.name,
                "status": ns.status.phase,
                "creation_timestamp": ns.metadata.creation_timestamp.isoformat() if ns.metadata.creation_timestamp else None
            }
            yaml_content += yaml.dump(ns_dict, default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content
    
    def format_nodes_as_table(self, nodes) -> str:
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
    
    def format_nodes_as_yaml(self, nodes) -> str:
        """Format nodes as YAML."""
        if not nodes.items:
            return "No nodes found."
        
        yaml_content = "### Nodes (YAML)\n\n```yaml\n"
        for node in nodes.items:
            status = "Unknown"
            if node.status.conditions:
                for condition in node.status.conditions:
                    if condition.type == "Ready":
                        status = "Ready" if condition.status == "True" else "NotReady"
                        break
            
            node_dict = {
                "name": node.metadata.name,
                "status": status,
                "version": node.status.node_info.kubelet_version if node.status.node_info else "Unknown",
                "creation_timestamp": node.metadata.creation_timestamp.isoformat() if node.metadata.creation_timestamp else None
            }
            yaml_content += yaml.dump(node_dict, default_flow_style=False)
            yaml_content += "---\n"
        yaml_content += "```"
        return yaml_content