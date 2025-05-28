
### StackStrom 검토 결과
1. K8S 환경에 최적화되지 않고 Python script, YAML 등 다소 복잡한 셋팅이 필요함.
2. K8S 환경에서 script 업로드 과정이 번거롭고 공수가 많이 소요됨
3. K8S 환경에 대한 지원이 부족함


## 설치
helm repo add stackstorm https://helm.stackstorm.com/

helm install stackstorm stackstorm/stackstorm-ha --namespace stackstorm --create-namespace

kubectl config set-context --current --namespace=stackstorm

- PW 확인 <br> 
kubectl get --namespace stackstorm -o jsonpath="{.data.ST2_AUTH_PASSWORD}" secret stackstorm-st2-auth <br>
-> 해당 값을 base64 디코딩하면 됨


- ID : st2admin <br>
 PW : MqhsJctyNkAb

- st2 Client 접속 <br>
kubectl exec -it stackstorm-st2client-6b798bb4f7-c8svb -- /bin/bash