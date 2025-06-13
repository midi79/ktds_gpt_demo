"""Prometheus service for executing PromQL queries."""
import logging
import json
import httpx

from app.config import config

logger = logging.getLogger(__name__)

class PrometheusService:
    """Service for interacting with Prometheus."""
    
    @staticmethod
    async def execute_query(query: str, format_type: str = "default") -> str:
        """Execute a PromQL query against Prometheus and return the results."""
        if not config.PROMETHEUS_URL:
            return "Error: Prometheus URL is not configured. Please contact the administrator."
            
        logger.info(f"Executing PromQL query: {query} with format: {format_type}")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{config.PROMETHEUS_URL}/api/v1/query",
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
                    
                    if result_type == "vector":
                        if format_type == "table":
                            return PrometheusService._format_vector_as_table(query, results)
                        elif format_type == "json":
                            return f"### Prometheus Query Results\n\nQuery: `{query}`\n\n```json\n{json.dumps(results, indent=2)}\n```"
                        else:
                            return PrometheusService._format_vector_as_text(query, results)
                    
                    elif result_type == "matrix":
                        if format_type == "table":
                            return PrometheusService._format_matrix_as_table(query, results)
                        else:
                            return f"### Prometheus Range Query Results\n\nQuery: `{query}`\n\nResults are in matrix format. Please use a specific instant query for more readable results."
                    
                    else:
                        return f"### Prometheus Results ({result_type})\n\nQuery: `{query}`\n\n```\n{results}\n```"
                else:
                    return f"Error executing query: {data.get('error', 'Unknown error')}"
        except Exception as e:
            logger.error(f"Error executing Prometheus query: {str(e)}")
            return f"Error executing query: {str(e)}"
    
    @staticmethod
    def _format_vector_as_text(query: str, results: list) -> str:
        """Format vector results as text."""
        formatted_results = "### Prometheus Query Results\n\n"
        formatted_results += f"Query: `{query}`\n\n"
        
        for i, result in enumerate(results, 1):
            labels = result.get("metric", {})
            label_str = ", ".join([f"{k}={v}" for k, v in labels.items()])
            
            value = result.get("value", [])
            if len(value) >= 2:
                timestamp, metric_value = value
                try:
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
    
    @staticmethod
    def _format_vector_as_table(query: str, results: list) -> str:
        """Format vector results as a Markdown table."""
        if not results:
            return "The query returned no results."
            
        all_label_keys = set()
        for result in results:
            labels = result.get("metric", {})
            all_label_keys.update(labels.keys())
            
        sorted_label_keys = sorted(all_label_keys)
        
        formatted_results = f"### Prometheus Query Results\n\n"
        formatted_results += f"Query: `{query}`\n\n"
        
        header = "| "
        for key in sorted_label_keys:
            header += f"{key} | "
        header += "Value |\n"
        
        separator = "| "
        for _ in range(len(sorted_label_keys)):
            separator += "--- | "
        separator += "--- |\n"
        
        rows = ""
        for result in results:
            labels = result.get("metric", {})
            value = result.get("value", [])
            
            row = "| "
            for key in sorted_label_keys:
                row += f"{labels.get(key, '')} | "
                
            if len(value) >= 2:
                _, metric_value = value
                try:
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
            
        formatted_results += header + separator + rows
        
        if len(sorted_label_keys) > 5:
            formatted_results += "\n**Note:** This table contains many columns and may not display well on small screens.\n"
            
        return formatted_results
    
    @staticmethod
    def _format_matrix_as_table(query: str, results: list) -> str:
        """Format matrix results as a table (simplified view)."""
        if not results:
            return "The query returned no results."
            
        return "Matrix results are complex time series. Consider using an instant query instead."