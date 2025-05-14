import subprocess

# Example: use a specific kubeconfig path
command = [
    "kubectl",
    "--kubeconfig", "C:/Users/Anderson Lee/.kube/config",
    "get", "pods", "--all-namespaces"
]

result = subprocess.run(command, capture_output=True, text=True)

if result.returncode == 0:
    print(result.stdout)
else:
    print("Error:", result.stderr)
