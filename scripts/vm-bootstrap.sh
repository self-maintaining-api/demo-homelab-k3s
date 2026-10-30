#!/usr/bin/env bash
# Runs on the VM as root (scripts/bootstrap.sh copies it there): installs k3s, Helm and Argo CD, then hands the
# cluster to Argo CD by applying the app of apps. Safe to run again: every step checks what is already there.
set -euo pipefail

: "${K3S_VERSION:?}" "${ARGOCD_CHART_VERSION:?}" "${NODE_IP:?}"
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
log() { printf '\n==> %s\n' "$*"; }

log "k3s ${K3S_VERSION}"
if ! command -v k3s >/dev/null || ! k3s --version | grep -q "${K3S_VERSION}"; then
  # Traefik and metrics-server are replaced by ingress-nginx and the metrics-server chart (Argo CD apps).
  curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${K3S_VERSION}" sh -s - server \
    --disable traefik --disable metrics-server \
    --write-kubeconfig-mode 600 --tls-san "${NODE_IP}" --node-ip "${NODE_IP}"
fi
for _ in $(seq 1 60); do
  kubectl get nodes 2>/dev/null | grep -q ' Ready' && break
  sleep 5
done
kubectl get nodes

log "Helm"
if ! command -v helm >/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

log "Argo CD (chart ${ARGOCD_CHART_VERSION})"
helm repo add argo https://argoproj.github.io/argo-helm >/dev/null 2>&1 || true
helm repo update argo >/dev/null
# The same release name as apps/argo-cd.yaml: Argo CD adopts this installation and manages itself from then on.
helm upgrade --install argocd argo/argo-cd --version "${ARGOCD_CHART_VERSION}" \
  --namespace argocd --create-namespace \
  --set dex.enabled=false --set notifications.enabled=false \
  --set-string 'configs.params.server\.insecure=true' \
  --wait --timeout 10m

log "App of apps"
kubectl apply -f /tmp/stackat-demo/root.yaml

log "Done. Argo CD now installs everything in apps/ (a few minutes)."
