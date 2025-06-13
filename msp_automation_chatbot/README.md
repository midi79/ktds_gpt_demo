# Mattermost ChatGPT Bot with Kubernetes and Prometheus Integration

A FastAPI-based bot that integrates ChatGPT with Mattermost, providing natural language interfaces to Kubernetes and Prometheus.

## Features

- **ChatGPT Integration**: Natural language processing for all queries
- **Kubernetes Commands**: Execute kubectl-like commands directly from Mattermost
- **Prometheus Queries**: Run PromQL queries and get formatted results
- **Auto-routing**: Automatically detects and executes PromQL or kubectl commands from ChatGPT responses
- **Multiple Output Formats**: Table, YAML, JSON, and text formatting options

## Installation

### Local Development

1. Clone the repository
2. Copy `.env.example` to `.env` and fill in your credentials
3. Install dependencies:
   ```bash
   pip install -r requirements.txt

4. Run the application:
    ```bash
   python -m app.main

5. Run the deployment (In another terminal)
   ```bash
   python -m python -m prefect_flows.deployment

6. In the Mattermost
   ```bash
   /gpt workflow