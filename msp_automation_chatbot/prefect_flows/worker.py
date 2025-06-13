"""Prefect worker for running flows."""
from prefect import flow
from prefect.client.orchestration import get_client
from prefect.workers import serve
import asyncio

async def start_worker():
    """Start a Prefect worker for the Kubernetes pool."""
    # This is for running flows with work pools
    # Adjust the pool name and type based on your setup
    await serve(
        flow_run_id=None,
        work_pool_name="kubernetes-pool",  # Change this to your work pool name
        work_queue_name="default",
        limit=5
    )

if __name__ == "__main__":
    print("Starting Prefect worker...")
    asyncio.run(start_worker())