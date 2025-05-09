# prometheus stack 설치 (Prometheus + Grafana + Alarm Manager)


helm repo add prometheus-community https://prometheus-community.github.io/helm-charts<br>
helm repo update<br>
<br>
helm install prometheus-stack prometheus-community/kube-prometheus-stack --namespace prometheus -f custom-values.yaml --set prometheus-node-exporter.hostRootFsMount.enabled=false
- --set prometheus-node-exporter.hostRootFsMount.enabled=false 옵션은 Docker Desktop에서 K8S를 띄울 경우에 적용 필요
