# k8s_demo_flow.py
from prefect import flow, task
import platform
import time
import os

@task(retries=1, retry_delay_seconds=5)
def get_kubernetes_node_info():
    node_name = os.getenv("KUBERNETES_NODE_NAME", platform.node())
    pod_name = os.getenv("POD_NAME", platform.node()) # More common env var in K8s
    
    message = (
        f"Hello from a Prefect task running in a Kubernetes Pod (Helm Deployed)!\n"
        f"  Python version: {platform.python_version()}\n"
        f"  Reported Pod/Node name: {pod_name}\n"
        f"  Current time: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}"
    )
    print(message)
    if "error" in pod_name.lower():
        raise ValueError("Simulated error in pod name!")
    return message

@flow(name="My K8s Demo Flow v3 (Helm)", log_prints=True)
def simple_k8s_flow_helm(greeting: str = "Ahoy Helm"):
    print(f"{greeting}! Starting the K8s demo flow (Helm deployed).")
    node_info = get_kubernetes_node_info()
    print(f"Task `get_kubernetes_node_info` completed.")
    print("K8s demo flow (Helm) finished successfully!")
    return {"node_info": node_info}

if __name__ == "__main__":
    print("Running flow locally for testing...")
    try:
        simple_k8s_flow_helm(greeting="Local Test Run Helm")
    except Exception as e:
        print(f"Local flow run failed: {e}")