- 참고 사이트 : https://github.com/PrefectHQ/prefect-helm/tree/main


kubectl config set-context --current --namespace=prefect

1. 설치
- helm repo add prefect https://prefecthq.github.io/prefect-helm
- helm search repo prefect <br>
  위에 있는 차트별로 하나씩 설치 (agent는 제외, deprecated)
- helm install server prefect/prefect-server <br>
  helm install prefect-worker prefect/prefect-worker -f worker-values.yaml<br>
  helm install exporter prefect/prometheus-prefect-exporter<br>

2. 접속
- kubectl --namespace prefect port-forward svc/prefect-server 4200:4200
- http://localhost:4200


3. Docker Build/Push
- docker build -t midi79/prefect-k8s-helm-flow:v0.1.0 .
- docker push midi79/prefect-k8s-helm-flow:v0.1.0


