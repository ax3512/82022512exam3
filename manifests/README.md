### nginx ingress 설치 (SA 학습자)
~~~
kubectl create namespace ingress-nginx
kubectl apply -f ingress-nginx-deploy.yaml -n ingress-nginx
~~~

### ArgoCd 설치 (SA 학습자)
~~~
kubectl create namespace argocd
kubectl apply -f argocd-install.yaml -n argocd
~~~

### kustomize 확인 (SA, AA 학습자 공통)
~~~
kubectl kustomize manifests/overlays/prod
~~~
