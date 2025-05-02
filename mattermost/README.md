1. Mattermost 설치 with Ingress
  - 참고 사이트 : https://github.com/mattermost/mattermost-helm/tree/master/charts/mattermost-team-edition

  - Ingress Controller 설치 <br>
    helm upgrade --install ingress-nginx ingress-nginx --repo https://kubernetes.github.io/ingress-nginx --namespace ingress-nginx --create-namespace

  - C:\Windows\System32\drivers\etc\hosts에 추가 <br>
    127.0.0.1 mattermost.local

  - Mattermost 설치 <br>
    helm repo add mattermost https://helm.mattermost.com
    helm repo update
    helm install mattermost mattermost/mattermost-team-edition --set mysql.mysqlUser=sampleUser --set mysql.mysqlPassword=samplePassword -f mattermost-values.yaml
    

2. Mattermost 설치 with NodePort

helm repo add mattermost https://helm.mattermost.com 
helm repo update
kubectl create namespace mattermost

helm show values mattermost/mattermost-team-edition > values.yaml

kubectl config set-context --current --namespace=mattermost

helm install mattermost mattermost/mattermost-team-edition \
  --namespace mattermost \
  --values values.yaml