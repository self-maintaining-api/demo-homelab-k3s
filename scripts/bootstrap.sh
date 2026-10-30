#!/usr/bin/env bash
# Runs on your Mac after `terraform apply`: waits for the VM, installs k3s and Argo CD on it (vm-bootstrap.sh), and
# writes ./kubeconfig so kubectl works from here.
set -euo pipefail
cd "$(dirname "$0")/.."

IP="${1:?usage: scripts/bootstrap.sh <vm-ip>}"
K3S_VERSION="v1.34.12+k3s1"  # pinned; k3s upgrades are done by hand (see README)
ARGOCD_CHART_VERSION="$(awk '/targetRevision:/ {print $2; exit}' apps/argo-cd.yaml)"

KNOWN_HOSTS="$PWD/.known_hosts"  # this repo's own file: a rebuilt VM gets a new host key without touching ~/.ssh
SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS" -o ConnectTimeout=5 -o BatchMode=yes)
ssh_vm() { ssh "${SSH_OPTS[@]}" "ubuntu@${IP}" "$@"; }

echo "==> Waiting for SSH on ${IP}"
for i in $(seq 1 60); do
  ssh_vm true 2>/dev/null && break
  [ "$i" = 60 ] && { echo "No SSH after 5 minutes: check the VM's console in Proxmox." >&2; exit 1; }
  sleep 5
done

echo "==> Waiting for cloud-init to finish"
ssh_vm 'cloud-init status --wait >/dev/null; cloud-init status'

echo "==> Installing k3s and Argo CD"
ssh_vm 'mkdir -p /tmp/stackat-demo'
scp "${SSH_OPTS[@]}" -q scripts/vm-bootstrap.sh argocd/root.yaml "ubuntu@${IP}:/tmp/stackat-demo/"
ssh_vm "sudo K3S_VERSION='${K3S_VERSION}' ARGOCD_CHART_VERSION='${ARGOCD_CHART_VERSION}' NODE_IP='${IP}' bash /tmp/stackat-demo/vm-bootstrap.sh"

echo "==> Writing ./kubeconfig"
ssh_vm 'sudo cat /etc/rancher/k3s/k3s.yaml' | sed "s#https://127.0.0.1:6443#https://${IP}:6443#" > kubeconfig
chmod 600 kubeconfig

cat <<EOF

Cluster is up. Argo CD is installing the apps now (5-10 minutes on the NUC):

  export KUBECONFIG=\$PWD/kubeconfig
  kubectl -n argocd get applications

  make urls            # the web UIs
  make argocd-password # Argo CD's admin password
EOF
