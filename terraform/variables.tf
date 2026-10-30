variable "node_name" {
  description = "Proxmox node that runs the VM (the host name shown in the Proxmox UI)."
  type        = string
  default     = "pve"
}

variable "vm_id" {
  description = "Proxmox VM ID (100 is semapi, 120 is stackat-ci)."
  type        = number
  default     = 130
}

variable "vm_name" {
  type    = string
  default = "demo-k3s"
}

variable "cores" {
  description = "vCPUs. Shared with the other VMs, so 4 on a 4-core host is fine for a demo."
  type        = number
  default     = 4
}

variable "memory_mb" {
  description = "RAM in MiB. The host had about 6 GiB free next to semapi and CI; 5 GiB leaves room for Proxmox itself."
  type        = number
  default     = 5120
}

variable "disk_gb" {
  type    = number
  default = 30
}

variable "disk_datastore" {
  description = "Where the VM disk and cloud-init drive live (pvesm status)."
  type        = string
  default     = "local-lvm"
}

variable "image_datastore" {
  description = "Directory storage that receives the Ubuntu cloud image. Needs the Import content type (see README)."
  type        = string
  default     = "local"
}

variable "bridge" {
  type    = string
  default = "vmbr0"
}

variable "ip_cidr" {
  description = "Static address of the VM, in CIDR notation."
  type        = string
  default     = "192.168.178.20/24"
}

variable "gateway" {
  type    = string
  default = "192.168.178.1"
}

variable "dns_servers" {
  type    = list(string)
  default = ["192.168.178.1", "1.1.1.1"]
}

variable "ssh_public_key_file" {
  description = "Your public key; the VM user `ubuntu` accepts only this key (no password)."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "ubuntu_image_url" {
  description = "Ubuntu 24.04 LTS cloud image."
  type        = string
  default     = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
}
