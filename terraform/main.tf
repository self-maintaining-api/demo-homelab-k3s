# One Ubuntu VM for a single-node k3s cluster. k3s, Argo CD and everything after it are installed by
# scripts/bootstrap.sh over SSH, so Terraform only needs the Proxmox API (no SSH access to the Proxmox host).

resource "proxmox_download_file" "ubuntu" {
  node_name    = var.node_name
  datastore_id = var.image_datastore
  content_type = "import"
  file_name    = "noble-server-cloudimg-amd64.qcow2" # the .img is a qcow2 image; Proxmox imports by extension
  url          = var.ubuntu_image_url
  overwrite    = false # keep the downloaded image; a newer one is picked up by `terraform apply -replace`
}

resource "proxmox_virtual_environment_vm" "k3s" {
  node_name   = var.node_name
  vm_id       = var.vm_id
  name        = var.vm_name
  description = "Stackat demo: single-node k3s, apps deployed by Argo CD from self-maintaining-api/demo-homelab-k3s. Managed by Terraform."
  tags        = ["stackat", "demo", "k3s"]

  # Cloud images have no qemu-guest-agent; with the agent off, Proxmox stops the VM instead of asking it to shut down.
  agent {
    enabled = false
  }
  stop_on_destroy = true

  cpu {
    cores = var.cores
    type  = "x86-64-v2-AES"
  }

  memory {
    dedicated = var.memory_mb
  }

  disk {
    datastore_id = var.disk_datastore
    import_from  = proxmox_download_file.ubuntu.id
    interface    = "scsi0"
    size         = var.disk_gb
    discard      = "on"
    ssd          = true
  }

  initialization {
    datastore_id = var.disk_datastore

    ip_config {
      ipv4 {
        address = var.ip_cidr
        gateway = var.gateway
      }
    }

    dns {
      servers = var.dns_servers
    }

    user_account {
      username = "ubuntu"
      keys     = [trimspace(file(pathexpand(var.ssh_public_key_file)))]
    }
  }

  network_device {
    bridge = var.bridge
  }

  operating_system {
    type = "l26"
  }

  serial_device {} # the Ubuntu cloud image logs to the serial console

  startup {
    order    = 3 # after the host's other VMs
    up_delay = 30
  }
}
