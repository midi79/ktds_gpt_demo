"""Script type detection utility."""
import re
from typing import Tuple

class ScriptDiscriminator:
    """Detect and extract script types from text."""
    
    @staticmethod
    def detect_script_type(text: str) -> Tuple[str, str]:
        """
        Detect whether the text contains PromQL or Kubernetes commands.
        Returns (script_type, extracted_script) where script_type is 'promql' or 'kubernetes' or 'unknown'
        """
        text_lower = text.lower().strip()
        
        # PromQL patterns
        promql_patterns = [
            r'\b(rate|sum|avg|max|min|count|histogram_quantile|increase)\s*\(',
            r'\[[\d]+[smhd]\]',  # Time ranges
            r'\{[^}]*\}',  # Label selectors
            r'by\s*\([^)]+\)',  # Group by
            r'without\s*\([^)]+\)',  # Group without
            r'node_filesystem_',  # Node filesystem metrics
            r'node_memory_',  # Node memory metrics
            r'node_cpu_',  # Node CPU metrics
            r'container_memory_',  # Container metrics
            r'up\s*\{',  # Up metrics with labels
            r'_total\s*$',  # Metrics ending with _total
            r'_bytes\s*/',  # Metrics with _bytes
        ]
        
        # Kubernetes command patterns
        k8s_patterns = [
            r'\b(kubectl|get|describe|logs|apply|delete|create)\b',
            r'\b(pods|pod|services|svc|deployments|deploy|nodes|ns|namespaces)\b',
            r'\b-n\s+\w+|\b--namespace\s+\w+',  # Namespace flags
            r'\b-l\s+\w+|\b--selector\s+\w+',  # Label selectors
            r'\b--field-selector\b',  # Field selectors
        ]
        
        # Check for code blocks with language hints
        code_blocks = re.findall(r'```(?:(promql|yaml|bash|sh|kubectl))?\n?(.*?)\n?```', text, re.DOTALL | re.IGNORECASE)
        
        if code_blocks:
            for lang_hint, block in code_blocks:
                block_clean = block.strip()
                
                if lang_hint and lang_hint.lower() == 'promql':
                    return "promql", block_clean
                    
                if lang_hint and lang_hint.lower() in ['bash', 'sh', 'kubectl']:
                    return "kubernetes", block_clean
                
                if not lang_hint and block_clean:
                    if any(re.search(pattern, block_clean, re.IGNORECASE) for pattern in promql_patterns):
                        return "promql", block_clean
                    elif any(re.search(pattern, block_clean, re.IGNORECASE) for pattern in k8s_patterns):
                        return "kubernetes", block_clean
        
        # Analyze the entire text
        promql_matches = sum(1 for pattern in promql_patterns if re.search(pattern, text_lower))
        k8s_matches = sum(1 for pattern in k8s_patterns if re.search(pattern, text_lower))
        
        # Special check for filesystem queries
        if 'filesystem' in text_lower and any(word in text_lower for word in ['avail', 'size', 'used', 'free']):
            lines = text.strip().split('\n')
            for line in lines:
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in promql_patterns):
                    return "promql", line.strip()
        
        # Make decision based on matches
        if promql_matches > k8s_matches and promql_matches > 0:
            lines = text.strip().split('\n')
            for line in lines:
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in promql_patterns):
                    return "promql", line.strip()
            return "promql", text.strip()
        elif k8s_matches > promql_matches and k8s_matches > 0:
            lines = text.strip().split('\n')
            for line in lines:
                if 'kubectl' in line.lower():
                    return "kubernetes", line.strip()
            return "kubernetes", text.strip()
        else:
            return "unknown", text.strip()