"""
Prefect 3.x Deployment Configuration Script for Helm-installed Prefect
This script creates deployments for flows using the new Prefect 3.x API
"""

import os
import asyncio
from datetime import timedelta
from prefect import serve
from prefect.server.schemas.schedules import CronSchedule, IntervalSchedule
from prefect.client.schemas.schedules import CronSchedule as ClientCronSchedule, IntervalSchedule as ClientIntervalSchedule

# Import your flows
from flows import (
    data_processing_flow,
    async_integration_flow,
    resilient_flow,
    daily_report_flow
)


def get_prefect_api_url():
    """Get the Prefect API URL from your Helm installation"""
    
    # Try to get from environment first
    api_url = os.getenv('PREFECT_API_URL')
    if api_url:
        return api_url
    
    # Common Helm installation patterns
    possible_urls = [
        "http://prefect-server.prefect.svc.cluster.local:4200/api",
        "http://prefect-server:4200/api",
        "http://localhost:4200/api",  # If port-forwarded
    ]
    
    print("🔍 Detecting Prefect API URL...")
    print("Available options:")
    for i, url in enumerate(possible_urls, 1):
        print(f"  {i}. {url}")
    
    choice = input("\nSelect API URL (1-3) or enter custom URL: ").strip()
    
    if choice.isdigit() and 1 <= int(choice) <= len(possible_urls):
        return possible_urls[int(choice) - 1]
    elif choice.startswith('http'):
        return choice
    else:
        return possible_urls[0]  # Default


def setup_work_pool():
    """Set up or verify the Kubernetes work pool exists"""
    import subprocess
    
    try:
        # Check if work pool exists
        result = subprocess.run(
            ["prefect", "work-pool", "ls", "--format", "json"],
            capture_output=True,
            text=True,
            check=True
        )
        
        work_pools = result.stdout
        if "kubernetes-pool" in work_pools:
            print("✅ Work pool 'kubernetes-pool' already exists")
            return True
        
        # Create work pool if it doesn't exist
        subprocess.run(
            ["prefect", "work-pool", "create", "kubernetes-pool", "--type", "kubernetes"],
            check=True
        )
        print("✅ Created work pool: kubernetes-pool")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Could not manage work pool: {e}")
        print("Please create the work pool manually:")
        print("  prefect work-pool create kubernetes-pool --type kubernetes")
        return False


async def deploy_flows():
    """Deploy all flows using Prefect 3.x serve() method"""
    
    print("🚀 Deploying flows to Helm-installed Prefect using Prefect 3.x...")
    print("=" * 60)
    
    try:
        # Set up work pool
        setup_work_pool()
        
        # Define deployment configurations
        deployments = []
        
        # 1. Data Processing Pipeline - Every 6 hours
        data_processing_deployment = data_processing_flow.to_deployment(
            name="data-processing-pipeline",
            version="1.0.0",
            description="Main data processing pipeline - fetches and processes data from multiple sources",
            tags=["data", "etl", "production", "helm"],
            parameters={"sources": ["production-api", "analytics-db", "external-feed"]},
            work_pool_name="kubernetes-pool",
            schedule=ClientCronSchedule(cron="0 */6 * * *", timezone="UTC"),
            job_variables={
                "image": "prefecthq/prefect:3-latest",
                "namespace": "prefect",
                "service_account_name": "prefect-flow-runner",
                "image_pull_policy": "Always",
                "finished_job_ttl": 300,
                "pod_template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "prefect-job",
                                "resources": {
                                    "requests": {
                                        "memory": "512Mi",
                                        "cpu": "250m"
                                    },
                                    "limits": {
                                        "memory": "1Gi",
                                        "cpu": "500m"
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        )
        deployments.append(("data-processing-pipeline", data_processing_deployment))
        
        # 2. Async Integration Flow - Every 30 minutes
        async_integration_deployment = async_integration_flow.to_deployment(
            name="async-api-integration",
            version="1.0.0",
            description="Async flow for integrating with multiple API endpoints concurrently",
            tags=["api", "async", "integration", "helm"],
            work_pool_name="kubernetes-pool",
            schedule=ClientIntervalSchedule(interval=timedelta(minutes=30)),
            job_variables={
                "image": "prefecthq/prefect:3-latest",
                "namespace": "prefect",
                "service_account_name": "prefect-flow-runner",
                "image_pull_policy": "Always",
                "finished_job_ttl": 300,
                "pod_template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "prefect-job",
                                "resources": {
                                    "requests": {
                                        "memory": "256Mi",
                                        "cpu": "100m"
                                    },
                                    "limits": {
                                        "memory": "512Mi",
                                        "cpu": "250m"
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        )
        deployments.append(("async-api-integration", async_integration_deployment))
        
        # 3. Resilient Flow - Manual trigger only
        resilient_deployment = resilient_flow.to_deployment(
            name="resilient-processing",
            version="1.0.0",
            description="Demonstrates error handling, retry logic, and failure recovery",
            tags=["resilience", "retry", "testing", "helm"],
            work_pool_name="kubernetes-pool",
            job_variables={
                "image": "prefecthq/prefect:3-latest",
                "namespace": "prefect",
                "service_account_name": "prefect-flow-runner",
                "image_pull_policy": "Always",
                "finished_job_ttl": 600,  # Keep failed jobs longer for debugging
                "pod_template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "prefect-job",
                                "resources": {
                                    "requests": {
                                        "memory": "256Mi",
                                        "cpu": "100m"
                                    },
                                    "limits": {
                                        "memory": "512Mi",
                                        "cpu": "250m"
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        )
        deployments.append(("resilient-processing", resilient_deployment))
        
        # 4. Daily Report Flow - Daily at 6 AM UTC
        daily_report_deployment = daily_report_flow.to_deployment(
            name="daily-report-generation",
            version="1.0.0",
            description="Generates comprehensive daily reports with processed metrics and insights",
            tags=["reporting", "daily", "business", "helm"],
            work_pool_name="kubernetes-pool",
            schedule=ClientCronSchedule(cron="0 6 * * *", timezone="UTC"),
            job_variables={
                "image": "prefecthq/prefect:3-latest",
                "namespace": "prefect",
                "service_account_name": "prefect-flow-runner",
                "image_pull_policy": "Always",
                "finished_job_ttl": 300,
                "pod_template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "prefect-job",
                                "resources": {
                                    "requests": {
                                        "memory": "512Mi",
                                        "cpu": "250m"
                                    },
                                    "limits": {
                                        "memory": "1Gi",
                                        "cpu": "500m"
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        )
        deployments.append(("daily-report-generation", daily_report_deployment))
        
        # Deploy all flows
        deployment_ids = []
        for name, deployment in deployments:
            try:
                deployment_id = await deployment.apply()
                deployment_ids.append((name, deployment_id))
                print(f"✅ Deployed: {name}")
            except Exception as e:
                print(f"❌ Failed to deploy {name}: {e}")
        
        if deployment_ids:
            print(f"\n🎉 Successfully deployed {len(deployment_ids)} flows!")
            print("\n📋 Deployment Summary:")
            print("=" * 60)
            
            for name, deployment in deployments:
                schedule_info = "Manual trigger" if not hasattr(deployment, 'schedule') or deployment.schedule is None else f"Scheduled: {deployment.schedule}"
                print(f"• {name}")
                print(f"  Description: {deployment.description}")
                print(f"  Schedule: {schedule_info}")
                print(f"  Tags: {', '.join(deployment.tags)}")
                print()
            
            print("🌐 Next Steps:")
            print("1. Access your Prefect UI (check your Helm deployment for the URL)")
            print("2. Go to 'Deployments' to see your new flows")
            print("3. Trigger manual runs to test")
            print("4. Monitor scheduled runs")
            print("5. Check 'Flow Runs' for execution details")
            
            print("\n💡 Useful Commands:")
            print("# List deployments")
            print("prefect deployment ls")
            print("\n# Trigger a manual run")
            print("prefect deployment run 'data-processing-flow/data-processing-pipeline'")
            print("\n# Check work pool status")
            print("prefect work-pool inspect kubernetes-pool")
            
        else:
            print("❌ No deployments were successful")
            
    except Exception as e:
        print(f"❌ Deployment process failed: {e}")
        print("\n🔧 Troubleshooting:")
        print("1. Ensure your Prefect API is accessible")
        print("2. Check that the work pool exists")
        print("3. Verify Kubernetes permissions")
        print("4. Check the Prefect server logs")
        raise


def serve_flows():
    """Alternative method using serve() for development"""
    
    print("🚀 Starting flows with serve() method...")
    
    # This method is useful for development and testing
    # It keeps the flows running locally but executes them on Kubernetes
    
    serve(
        data_processing_flow.to_deployment(
            name="data-processing-pipeline-dev",
            work_pool_name="kubernetes-pool",
            tags=["development", "serve"]
        ),
        async_integration_flow.to_deployment(
            name="async-api-integration-dev",
            work_pool_name="kubernetes-pool",
            tags=["development", "serve"]
        ),
        resilient_flow.to_deployment(
            name="resilient-processing-dev",
            work_pool_name="kubernetes-pool",
            tags=["development", "serve"]
        ),
        daily_report_flow.to_deployment(
            name="daily-report-generation-dev",
            work_pool_name="kubernetes-pool",
            tags=["development", "serve"]
        ),
        limit=10  # Maximum concurrent flow runs
    )


def check_connection():
    """Check connection to Prefect server"""
    import subprocess
    
    try:
        result = subprocess.run(
            ["prefect", "config", "view"],
            capture_output=True,
            text=True,
            check=True
        )
        print("✅ Prefect configuration:")
        print(result.stdout)
        
        # Test API connection by listing deployments
        result = subprocess.run(
            ["prefect", "deployment", "ls"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Connected to Prefect server")
            return True
        else:
            print("⚠️  Could not verify server connection")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"❌ Connection check failed: {e}")
        return False


def main():
    """Main function to handle deployment"""
    
    print("🔧 Setting up Prefect 3.x deployments for Helm installation")
    print("=" * 60)
    
    # Check connection first
    if not check_connection():
        print("\n🔧 Connection Issues? Try these steps:")
        print("1. Check if Prefect server is running:")
        print("   kubectl get pods -n prefect")
        print("\n2. Port forward if needed:")
        print("   kubectl port-forward -n prefect svc/prefect-server 4200:4200")
        print("\n3. Set API URL:")
        print("   prefect config set PREFECT_API_URL='http://localhost:4200/api'")
        return
    
    # Choose deployment method
    print("\nChoose deployment method:")
    print("1. Deploy flows (recommended for production)")
    print("2. Serve flows (good for development)")
    
    choice = input("\nSelect option (1-2): ").strip()
    
    if choice == "1":
        # Use asyncio to run the async deployment function
        asyncio.run(deploy_flows())
    elif choice == "2":
        serve_flows()
    else:
        print("Invalid choice. Running deployment method...")
        asyncio.run(deploy_flows())


if __name__ == "__main__":
    main()