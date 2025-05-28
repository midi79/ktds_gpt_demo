"""
Prefect 3.x Sample Flows with Various Task Examples
Run these flows to see them in the Prefect UI
"""

import asyncio
import random
import time
from datetime import datetime, timedelta
from typing import List

from prefect import flow, task, get_run_logger
from prefect.tasks import task_input_hash
from prefect.cache_policies import INPUTS


# Simple computational tasks
@task(cache_policy=INPUTS, cache_expiration=timedelta(hours=1))
def fetch_data(source: str) -> List[dict]:
    """Simulate fetching data from a source with caching"""
    logger = get_run_logger()
    logger.info(f"Fetching data from {source}")
    
    # Simulate API call delay
    time.sleep(2)
    
    # Generate sample data
    data = [
        {"id": i, "value": random.randint(1, 100), "timestamp": datetime.now().isoformat()}
        for i in range(10)
    ]
    
    logger.info(f"Fetched {len(data)} records from {source}")
    return data


@task
def process_data(data: List[dict]) -> dict:
    """Process the fetched data"""
    logger = get_run_logger()
    logger.info("Processing data...")
    
    total_value = sum(item["value"] for item in data)
    avg_value = total_value / len(data) if data else 0
    max_value = max((item["value"] for item in data), default=0)
    min_value = min((item["value"] for item in data), default=0)
    
    result = {
        "total": total_value,
        "average": avg_value,
        "max": max_value,
        "min": min_value,
        "count": len(data)
    }
    
    logger.info(f"Processed data: {result}")
    return result


@task
def save_results(results: dict, destination: str) -> str:
    """Save processed results"""
    logger = get_run_logger()
    
    # Simulate saving to database/file
    time.sleep(1)
    
    filename = f"{destination}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    logger.info(f"Saved results to {filename}")
    logger.info(f"Results summary: {results}")
    
    return filename


@task(retries=3, retry_delay_seconds=2)
def unreliable_task() -> str:
    """Task that might fail to demonstrate retry logic"""
    logger = get_run_logger()
    
    if random.random() < 0.6:  # 60% chance of failure
        logger.warning("Task failed, will retry...")
        raise Exception("Random failure occurred")
    
    logger.info("Task succeeded!")
    return "Success after retries"


# Async task example
@task
async def async_api_call(endpoint: str) -> dict:
    """Simulate an async API call"""
    logger = get_run_logger()
    logger.info(f"Making async call to {endpoint}")
    
    # Simulate async operation
    await asyncio.sleep(1)
    
    response = {
        "endpoint": endpoint,
        "status": "success",
        "data": {"message": f"Data from {endpoint}"},
        "timestamp": datetime.now().isoformat()
    }
    
    logger.info(f"Async call completed: {response['status']}")
    return response


# Main data processing flow
@flow(name="Data Processing Pipeline", log_prints=True)
def data_processing_flow(sources: List[str] = None):
    """Main flow that orchestrates data processing tasks"""
    if sources is None:
        sources = ["api-service-1", "api-service-2", "database"]
    
    logger = get_run_logger()
    logger.info(f"Starting data processing pipeline for sources: {sources}")
    
    # Fetch data from multiple sources in parallel
    data_futures = [fetch_data(source) for source in sources]
    
    # Process each dataset
    processed_results = []
    for i, data_future in enumerate(data_futures):
        data = data_future
        processed = process_data(data)
        processed_results.append(processed)
        
        # Save individual results
        save_results(processed, f"processed_data_{sources[i]}")
    
    # Combine all results
    combined_result = {
        "total_records": sum(r["count"] for r in processed_results),
        "overall_average": sum(r["average"] * r["count"] for r in processed_results) / sum(r["count"] for r in processed_results),
        "sources_processed": len(sources),
        "processing_timestamp": datetime.now().isoformat()
    }
    
    # Save combined results
    final_file = save_results(combined_result, "combined_results")
    
    logger.info(f"Pipeline completed successfully. Final results saved to: {final_file}")
    return combined_result


# Async flow example
@flow(name="Async API Integration", log_prints=True)
async def async_integration_flow():
    """Flow demonstrating async task execution"""
    logger = get_run_logger()
    logger.info("Starting async integration flow")
    
    endpoints = ["users", "todos", "posts", "comments"]
    
    # Run async tasks concurrently
    api_tasks = [async_api_call(f"https://jsonplaceholder.typicode.com/{endpoint}") for endpoint in endpoints]
    results = await asyncio.gather(*api_tasks)
    
    # Process results
    summary = {
        "total_calls": len(results),
        "successful_calls": len([r for r in results if r["status"] == "success"]),
        "completion_time": datetime.now().isoformat()
    }
    
    logger.info(f"Async integration completed: {summary}")
    return summary


# Error handling and retry flow
@flow(name="Resilient Processing", log_prints=True)
def resilient_flow():
    """Flow demonstrating error handling and retries"""
    logger = get_run_logger()
    logger.info("Starting resilient processing flow")
    
    try:
        # This task might fail and retry
        result = unreliable_task()
        logger.info(f"Unreliable task completed: {result}")
        
        # Process some data
        data = fetch_data("resilient-source")
        processed = process_data(data)
        
        return {
            "status": "success",
            "unreliable_result": result,
            "processed_data": processed
        }
    
    except Exception as e:
        logger.error(f"Flow failed after retries: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


# Scheduled flow example
@flow(name="Daily Report Generation", log_prints=True)
def daily_report_flow():
    """Flow for generating daily reports"""
    logger = get_run_logger()
    logger.info("Generating daily report")
    
    # Fetch today's data
    today_data = fetch_data("daily-metrics")
    processed_data = process_data(today_data)
    
    # Create report
    report = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "metrics": processed_data,
        "report_generated_at": datetime.now().isoformat(),
        "summary": f"Processed {processed_data['count']} records with average value {processed_data['average']:.2f}"
    }
    
    # Save report
    report_file = save_results(report, "daily_report")
    
    logger.info(f"Daily report generated: {report_file}")
    return report


if __name__ == "__main__":
    # Run different flows for testing
    print("Running Data Processing Pipeline...")
    result1 = data_processing_flow(["source-a", "source-b"])
    print(f"Result: {result1}")
    
    print("\nRunning Resilient Flow...")
    result2 = resilient_flow()
    print(f"Result: {result2}")
    
    print("\nRunning Async Integration Flow...")
    result3 = asyncio.run(async_integration_flow())
    print(f"Result: {result3}")
    
    print("\nRunning Daily Report Flow...")
    result4 = daily_report_flow()
    print(f"Result: {result4}")