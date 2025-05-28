## 실행방법

kubectl apply -f k8s-deployment.yaml

kubectl port-forward -n prefect service/prefect-server 4200:4200

prefect config set PREFECT_API_URL="http://localhost:4200/api"

prefect work-pool create kubernetes-pool --type kubernetes

python deployment.py


### - Manual run
prefect deployment run "data-processing-flow/data-processing-pipeline"

prefect deployment run "resilient-flow/resilient-processing