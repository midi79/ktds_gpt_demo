# prometheus stack 설치 (Prometheus + Grafana + Alarm Manager)


1. 설치 방법 <br>
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts<br>
helm repo update<br>
<br>
helm install prometheus-stack prometheus-community/kube-prometheus-stack --namespace prometheus -f custom-values.yaml --set prometheus-node-exporter.hostRootFsMount.enabled=false
- --set prometheus-node-exporter.hostRootFsMount.enabled=false 옵션은 Docker Desktop에서 K8S를 띄울 경우에 적용 필요

<br>

- Docker Desktop Kubernetes Metric 서버 활성화 하기 <br>
https://data04190.tistory.com/133


- Grafana init chown data 에러 발생시
helm upgrade prometheus-stack prometheus-community/kube-prometheus-stack --reuse-values --set grafana.initChownData=false