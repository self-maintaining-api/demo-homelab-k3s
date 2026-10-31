# Stackat demo cluster on Proxmox. `make up` builds everything, `make destroy` removes the VM.
SHELL := /bin/bash
ifneq (,$(wildcard .env))
include .env
export PROXMOX_VE_ENDPOINT PROXMOX_VE_API_TOKEN PROXMOX_VE_INSECURE
endif

TF := terraform -chdir=terraform
IP = $(shell $(TF) output -raw ip 2>/dev/null)
DOMAIN := demo-k3s.internal
UIS := argocd grafana headlamp podinfo
export KUBECONFIG := $(CURDIR)/kubeconfig

.PHONY: help check init plan vm bootstrap up status hosts urls argocd-password grafana-password headlamp-token vulns diff ssh destroy

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-18s %s\n", $$1, $$2}'

check: ## Check the tools and .env are in place
	@for t in terraform ssh scp kubectl; do command -v $$t >/dev/null || { echo "missing: $$t (brew install $$t)"; exit 1; }; done
	@test -f .env || { echo "missing .env: cp .env.example .env and fill in the token"; exit 1; }
	@echo "ok"

init: check ## terraform init
	$(TF) init

plan: init ## Show what Terraform would create
	$(TF) plan

vm: init ## Create the VM (Ubuntu 24.04 on Proxmox)
	$(TF) apply

bootstrap: ## Install k3s and Argo CD on the VM, write ./kubeconfig
	@test -n "$(IP)" || { echo "no VM address: run make vm first"; exit 1; }
	scripts/bootstrap.sh $(IP)

up: vm bootstrap ## Everything: VM, k3s, Argo CD, the apps

status: ## Argo CD's view of every app
	kubectl -n argocd get applications

hosts: ## The line to add to /etc/hosts, so the UIs' names point at the VM
	@test -n "$(IP)" || { echo "no VM address: run make vm first (or terraform output ip)"; exit 1; }
	@echo "$(IP) $(foreach ui,$(UIS),$(ui).$(DOMAIN))"
	@echo "Add it with: make hosts | head -1 | sudo tee -a /etc/hosts"

urls: ## The web UIs (their names need the line from make hosts)
	@echo "  Argo CD   https://argocd.$(DOMAIN)    (admin / make argocd-password)"
	@echo "  Grafana   https://grafana.$(DOMAIN)   (admin / make grafana-password)"
	@echo "  Headlamp  https://headlamp.$(DOMAIN)  (token: make headlamp-token)"
	@echo "  podinfo   https://podinfo.$(DOMAIN)"

argocd-password: ## Argo CD's initial admin password
	@kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo

grafana-password: ## Grafana's admin password
	@kubectl -n monitoring get secret grafana -o jsonpath='{.data.admin-password}' | base64 -d; echo

headlamp-token: ## A one-day, read-only token for Headlamp
	@kubectl -n headlamp create token headlamp --duration 24h

vulns: ## Vulnerabilities in the running images, per workload (trivy-operator)
	@kubectl get vulnerabilityreports -A -o custom-columns='NAMESPACE:.metadata.namespace,WORKLOAD:.metadata.labels.trivy-operator\.resource\.name,IMAGE:.report.artifact.repository,TAG:.report.artifact.tag,CRITICAL:.report.summary.criticalCount,HIGH:.report.summary.highCount,MEDIUM:.report.summary.mediumCount'

diff: ## What the local branch changes in the cluster, compared with origin/main (needs helm)
	python3 tools/upgrade_diff.py --base origin/main

ssh: ## SSH to the VM
	ssh -o UserKnownHostsFile=.known_hosts ubuntu@$(IP)

destroy: ## Delete the VM and the downloaded Ubuntu image
	$(TF) destroy
	rm -f kubeconfig .known_hosts
