# Kubernetes — Authentication Service

Step-by-step guide for deploying the authentication service on **Docker Desktop Kubernetes**.

> **Important**: This does NOT replace Docker Compose. Both workflows coexist side-by-side.
> Docker Compose = local development workflow
> Kubernetes = deployment/orchestration workflow

---

## Prerequisites

- Docker Desktop with Kubernetes enabled
- `kubectl` CLI (bundled with Docker Desktop)

Verify your cluster:

```bash
kubectl config current-context    # Should show: docker-desktop
kubectl get nodes                 # Should show 1 node in Ready state
```

---

## Architecture Mapping

| Docker Compose Service | Kubernetes Resource | What it does |
|---|---|---|
| `auth_app` | Deployment `auth-app` + Service `auth-app` | FastAPI on port 8000 |
| `auth_celery` | Deployment `auth-celery` | Celery worker (auth_queue) |
| `auth_celery_beat` | Deployment `auth-celery-beat` | Celery Beat scheduler |
| `shared_redis` | Deployment `redis` + Service `redis` | Redis 7 Alpine |
| `environment:` vars | ConfigMap `auth-config` | Non-sensitive config |
| `.env` secrets | Secret `auth-secrets` | API keys, DB URL, etc. |
| `trading_network` | Built-in cluster DNS | Automatic in Kubernetes |

---

## Step 1 — Build the Docker Image

Kubernetes needs a pre-built image (it doesn't build from Dockerfile like Compose does).

```bash
cd authentication-service

# Build the production (runtime) stage
docker build -t trading/auth-service:latest --target runtime .
```

> **Note**: Docker Desktop shares images between Docker and Kubernetes automatically.
> That's why `imagePullPolicy: Never` is set in the manifests — no registry needed.

---

## Step 2 — Deploy to Kubernetes

Apply all manifests in order:

```bash
# 1. Create the namespace (isolation boundary)
kubectl apply -f k8s/namespace.yaml

# 2. Apply config and secrets
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml

# 3. Deploy Redis storage, deployment, and service (auth service depends on it)
kubectl apply -f k8s/redis-pvc.yaml
kubectl apply -f k8s/redis-deployment.yaml
kubectl apply -f k8s/redis-service.yaml

# 4. Deploy the authentication service
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/celery-deployment.yaml
kubectl apply -f k8s/celery-beat-deployment.yaml
```

Or apply using Kustomize (safely excludes `secret.example.yaml`):

```bash
kubectl apply -k k8s/
```

---

## Step 3 — Verify

```bash
# Check all pods are Running
kubectl get pods -n authentication

# Expected output:
# NAME                               READY   STATUS    RESTARTS   AGE
# auth-app-xxxxx                     1/1     Running   0          1m
# auth-celery-xxxxx                  1/1     Running   0          1m
# auth-celery-beat-xxxxx             1/1     Running   0          1m
# redis-xxxxx                        1/1     Running   0          1m

# Check services
kubectl get services -n authentication

# Check health endpoint (accessible via LoadBalancer service on port 8000)
curl http://localhost:8000/health
```

---

## Useful kubectl Commands

```bash
# ── View Resources ─────────────────────────────────────────────────────────
kubectl get all -n authentication                    # See everything
kubectl get pods -n authentication -o wide           # Pods with node/IP info
kubectl describe pod <pod-name> -n authentication    # Detailed pod info

# ── Logs ───────────────────────────────────────────────────────────────────
kubectl logs -n authentication -l app=auth-app       # FastAPI logs
kubectl logs -n authentication -l app=auth-celery    # Celery worker logs
kubectl logs -n authentication -l app=auth-celery-beat  # Beat scheduler logs
kubectl logs -f -n authentication <pod-name>         # Stream logs (like docker logs -f)

# ── Shell Access ───────────────────────────────────────────────────────────
kubectl exec -it -n authentication <pod-name> -- sh  # Shell into a pod

# ── Scaling ────────────────────────────────────────────────────────────────
kubectl scale deployment auth-app -n authentication --replicas=3      # Scale API
kubectl scale deployment auth-celery -n authentication --replicas=2   # Scale workers
# ⚠️  DO NOT scale auth-celery-beat beyond 1!

# ── Restart ────────────────────────────────────────────────────────────────
kubectl rollout restart deployment auth-app -n authentication

# ── Update Image ───────────────────────────────────────────────────────────
# After rebuilding the Docker image:
docker build -t trading/auth-service:latest .
kubectl rollout restart deployment auth-app -n authentication
kubectl rollout restart deployment auth-celery -n authentication
kubectl rollout restart deployment auth-celery-beat -n authentication
```

---

## Teardown

```bash
# Remove all auth-service resources via Kustomize
kubectl delete -k k8s/

# Or remove the entire namespace (deletes everything in it)
kubectl delete namespace authentication
```

---

## File Reference

| File | Purpose |
|---|---|
| `kustomization.yaml` | Kustomize bundle configuration (excludes `secret.example.yaml`) |
| `namespace.yaml` | Creates the `authentication` namespace |
| `configmap.yaml` | Non-sensitive environment variables |
| `secret.yaml` | Sensitive environment variables (base64) |
| `secret.example.yaml` | Template for sensitive secrets with safe placeholder values |
| `redis-pvc.yaml` | PersistentVolumeClaim for Redis data directory |
| `redis-deployment.yaml` | Redis Deployment |
| `redis-service.yaml` | Internal ClusterIP Service for Redis (`redis:6379`) |
| `deployment.yaml` | FastAPI app Deployment |
| `service.yaml` | Exposes FastAPI as LoadBalancer service on port 8000 |
| `celery-deployment.yaml` | Celery worker Deployment |
| `celery-beat-deployment.yaml` | Celery Beat scheduler Deployment |
