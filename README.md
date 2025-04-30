# ktds_gpt_demo
KT DS : Mattermost + ChatGPT 연계 데모

1. Mattermost 설치
  - 참고 사이트 : https://github.com/mattermost/mattermost-helm/tree/master/charts/mattermost-team-edition

  - Ingress Controller 설치
    helm upgrade --install ingress-nginx ingress-nginx --repo https://kubernetes.github.io/ingress-nginx --namespace ingress-nginx --create-namespace

  - C:\Windows\System32\drivers\etc\hosts에 추가 <br>
    127.0.0.1 mattermost.local

  - Mattermost 설치
    helm repo add mattermost https://helm.mattermost.com
    helm repo update
    helm install mattermost mattermost/mattermost-team-edition --set mysql.mysqlUser=sampleUser --set mysql.mysqlPassword=samplePassword -f mattermost-values.yaml
    

