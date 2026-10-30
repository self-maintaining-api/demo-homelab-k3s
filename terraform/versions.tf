terraform {
  required_version = ">= 1.5.0"

  required_providers {
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.117.0" # pinned behind the latest on purpose: Stackat opens the upgrade issue
    }
  }
}

# Credentials come from the environment (.env, loaded by the Makefile), never from this repo:
#   PROXMOX_VE_ENDPOINT  https://192.168.178.10:8006/
#   PROXMOX_VE_API_TOKEN terraform@pve!demo=<secret>
#   PROXMOX_VE_INSECURE  true   (Proxmox's self-signed certificate)
provider "proxmox" {}
