# Stackat demo cluster on Proxmox. `make up` builds everything, `make destroy` removes the VM.
SHELL := /bin/bash
ifneq (,$(wildcard .env))
include .env
export PROXMOX_VE_ENDPOINT PROXMOX_VE_API_TOKEN PROXMOX_VE_INSECURE
endif

TF := terraform -chdir=terraform
IP = $(shell $(TF) output -raw ip 2>/dev/null || echo 192.168.178.20)
export KUBECONFIG := $(CURDIR)/kubeconfig

.PHONY: help check init plan vm bootstrap up status urls argocd-password grafana-password headlamp-token ssh destroy

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
	scripts/bootstrap.sh $(IP)

up: vm bootstrap ## Everything: VM, k3s, Argo CD, the apps

status: ## Argo CD's view of every app
	kubectl -n argocd get applications

urls: ## The web UIs (needs nip.io to resolve: see README if it does not)
	@echo "  Argo CD   https://argocd.$(IP).nip.io    (admin / make argocd-password)"
	@echo "  Grafana   https://grafana.$(IP).nip.io   (admin / make grafana-password)"
	@echo "  Headlamp  https://headlamp.$(IP).nip.io  (token: make headlamp-token)"

argocd-password: ## Argo CD's initial admin password
	@kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo

grafana-password: ## Grafana's admin password
	@kubectl -n monitoring get secret grafana -o jsonpath='{.data.admin-password}' | base64 -d; echo

headlamp-token: ## A one-day, read-only token for Headlamp
	@kubectl -n headlamp create token headlamp --duration 24h

ssh: ## SSH to the VM
	ssh -o UserKnownHostsFile=.known_hosts ubuntu@$(IP)

destroy: ## Delete the VM and the downloaded Ubuntu image
	$(TF) destroy
	rm -f kubeconfig .known_hosts
