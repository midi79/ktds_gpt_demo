"""Prefect deployment configuration for version 3.x."""
import sys
from pathlib import Path

# Add the parent directory to Python path
sys.path.append(str(Path(__file__).parent.parent))

from prefect import serve
from prefect_flows.k8s_troubleshooting_flow import k8s_troubleshooting_flow

def deploy_flows():
    """Deploy flows using Prefect 3.x."""
    
    print("Creating deployment...")
    
    # Create deployment configuration
    k8s_deployment = k8s_troubleshooting_flow.to_deployment(
        name="k8s-troubleshooting",
        version="1.0.0",
        tags=["kubernetes", "troubleshooting", "mattermost"],
        description="Automated Kubernetes troubleshooting workflow triggered from Mattermost",
        parameters={},
        enforce_parameter_schema=True,
    )
    
    print(f"Deployment created: {k8s_deployment.name}")
    print("Starting deployment server...")
    print("Deployment will be available at: k8s-troubleshooting-flow/k8s-troubleshooting")
    print("\nPress Ctrl+C to stop the server")
    
    # Serve the deployment (non-async version)
    serve(
        k8s_deployment,
        limit=5,  # Limit concurrent runs
        pause_on_shutdown=False
    )

if __name__ == "__main__":
    try:
        deploy_flows()
    except KeyboardInterrupt:
        print("\nDeployment server stopped.")