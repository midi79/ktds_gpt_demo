# my_flow.py
from prefect import flow, task
import platform
import time

@task
def log_platform_info():
    """Logs information about the execution environment."""
    node = platform.node()
    system = platform.system()
    release = platform.release()
    python_version = platform.python_version()
    message = (
        f"Hello from a Kubernetes Pod! 🚀\n"
        f"  Node: {node}\n"
        f"  System: {system}\n"
        f"  Release: {release}\n"
        f"  Python Version: {python_version}"
    )
    print(message)
    return message

@task
def simple_task(name: str):
    """A simple task that prints a greeting."""
    greeting = f"Hello, {name}! This task is running successfully."
    print(greeting)
    # Simulate some work
    for i in range(3):
        print(f"Processing item {i+1} for {name}...")
        time.sleep(1)
    return greeting

@flow(log_prints=True) # log_prints=True ensures print statements appear in Prefect logs
def my_kubernetes_flow(user_name: str = "K8s User"):
    """
    A simple flow designed to run on Kubernetes.
    It logs platform info and runs a simple greeting task.
    """
    platform_message = log_platform_info()
    greeting_message = simple_task(user_name)
    print(f"Flow completed. Platform info: '{platform_message}'. Greeting: '{greeting_message}'")

if __name__ == "__main__":
    # This allows you to run the flow locally for testing,
    # but it's not how it will be triggered by Prefect on K8s.
    my_kubernetes_flow(user_name="Local Developer")

# how to run
# python my_flow.py    