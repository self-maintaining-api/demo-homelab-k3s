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

echo "==> Waiting for SSH on ${IP} (up to 10 minutes on a first boot)"
for i in $(seq 1 120); do
  if error="$(ssh_vm true 2>&1)"; then break; fi
  if [ "$i" = 120 ]; then
    echo "No SSH after 10 minutes. The last error was:" >&2
    echo "  ${error}" >&2
    case "$error" in
      *"Permission denied"*) echo "The VM answers but refuses your key: load it with ssh-add, or check ssh_public_key_file." >&2 ;;
      *"timed out"*|*"No route"*|*"Host is down"*) echo "The VM does not answer: check its console on Proxmox with qm terminal 130 (exit with Ctrl+O)." >&2 ;;
      *"refused"*) echo "The VM is up but sshd is not listening yet: run make bootstrap again in a minute." >&2 ;;
    esac
    exit 1
  fi
  [ $((i % 6)) = 0 ] && echo "    still waiting ($((i * 5))s): ${error}"
  sleep 5
done

echo "==> Waiting for cloud-init to finish"
# Exit code 2 means "done, with recoverable warnings" (common on cloud images): fine for us. 1 is a real failure.
set +e
ssh_vm 'cloud-init status --wait >/dev/null 2>&1; cloud-init status'
code=$?
set -e
if [ "$code" = 1 ] || [ "$code" = 255 ]; then
  echo "cloud-init failed on the VM (exit ${code}). Details: make ssh, then: cloud-init status --long" >&2
  exit 1
fi

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
