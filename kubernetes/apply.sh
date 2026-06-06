#!/bin/bash

cd ../api
docker build -t api:latest .
cd ../web
docker build -t web:latest .
cd ../kubernetes

kubectl apply -f namespace.yaml

kubectl apply -f app/api.yaml
kubectl apply -f app/elasticsearch.yaml
kubectl apply -f app/web.yaml

kubectl wait --for=condition=ready pod -l app=elasticsearch -n app --timeout=120s
kubectl wait --for=condition=ready pod -l app=api -n app --timeout=120s
kubectl wait --for=condition=ready pod -l app=web -n app --timeout=120s

kubectl get all -n monitoring

kubectl apply -f monitoring/rbac.yaml
kubectl apply -f monitoring/prometheus-config.yaml
kubectl apply -f monitoring/prometheus.yaml
kubectl apply -f monitoring/jaeger.yaml
kubectl apply -f monitoring/grafana.yaml
kubectl apply -f monitoring/kibana.yaml

kubectl wait --for=condition=ready pod -l app=jaeger -n app --timeout=120s
kubectl wait --for=condition=ready pod -l app=prometheus -n app --timeout=120s
kubectl wait --for=condition=ready pod -l app=kibana -n app --timeout=120s

kubectl get all -n monitoring

echo "Web UI:      http://localhost:30080"
echo "Grafana:     http://localhost:30030 (admin/admin)"
echo "Jaeger UI:   http://localhost:30040"
echo "Kibana:      http://localhost:30050"