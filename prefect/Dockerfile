# Dockerfile
FROM prefecthq/prefect:3.4.2-python3.12

WORKDIR /opt/prefect/app
COPY /src/k8s_demo_flow.py .

# OPTIONAL: If you have a requirements.txt
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt