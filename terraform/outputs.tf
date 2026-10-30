output "ip" {
  description = "The VM's address, without the prefix length."
  value       = split("/", var.ip_cidr)[0]
}

output "ssh" {
  value = "ssh ubuntu@${split("/", var.ip_cidr)[0]}"
}
