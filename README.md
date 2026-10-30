# Stackat demo: a real k3s cluster on Proxmox, deployed by Argo CD

A single-node Kubernetes cluster (k3s on Ubuntu 24.04) that runs on a Proxmox VM and installs everything from this
repository through Argo CD. The tools are pinned a few releases behind on purpose: Stackat reads every release note
in between, opens one issue per tool with what to change, and its pull requests are merged here and rolled out by
Argo CD, for real.

| App | Chart | Pinned at | Why it is here |
| --- | --- | --- | --- |
| Argo CD | argo-cd | 10.8.4 | Deploys everything, including itself |
| cert-manager | cert-manager | v1.18.6 | A private CA for the UIs (`manifests/cert-manager-issuers`) |
| ingress-nginx | ingress-nginx | 4.12.8 | The web entry point. Retired upstream in 2026, so Stackat should say so |
| External Secrets | external-secrets | 2.11.0 | `installCRDs` left at the default: issues show how to check a setting the repo does not set |
| Kyverno | kyverno | 3.6.4 | Two policies in Audit mode (`manifests/kyverno-policies`) |
| metrics-server | metrics-server | 3.12.2 | `kubectl top` (k3s' own copy is turned off) |
| Reloader | reloader | 2.1.5 | Restarts pods when their ConfigMaps or Secrets change |
| CloudNativePG | cloudnative-pg | 0.26.1 | Runs a one-instance PostgreSQL (`manifests/postgres`) |
| Prometheus | prometheus | 29.36.2 | Metrics, 3 days kept |
| Grafana | grafana | 10.2.0 | Dashboards on Prometheus |
| Headlamp | headlamp | 0.42.0 | A read-only Kubernetes UI |

The VM itself comes from Terraform (`terraform/`, provider `bpg/proxmox`, also pinned behind).

Sized for a small host: 4 vCPU (shared) and 5 GiB RAM. Change `memory_mb` and `cores` in `terraform/terraform.tfvars`.

## What happens

1. `terraform apply` downloads the Ubuntu 24.04 cloud image to Proxmox and creates VM 130 with a static IP and your
   SSH key (cloud-init). Terraform only uses the Proxmox API.
2. `scripts/bootstrap.sh` connects over SSH, installs k3s (without Traefik), Helm and Argo CD, and applies
   `argocd/root.yaml`.
3. Argo CD reads `apps/` and installs every app. From then on, a change merged to `main` is a change to the cluster.

## Setup, once

### On the Proxmox host (as root)

Let the `local` storage hold disk images for import. Check what it allows now:

```sh
pvesh get /storage/local
```

Add `import` to the `content` list it shows. For example, if it shows `iso,vztmpl,backup`:

```sh
pvesm set local --content iso,vztmpl,backup,import
```

Create a Proxmox user and API token for Terraform, with only the rights it needs:

```sh
pveum role add StackatDemo -privs "Datastore.Allocate Datastore.AllocateSpace Datastore.AllocateTemplate Datastore.Audit Pool.Audit Sys.Audit Sys.Console Sys.Modify SDN.Use VM.Allocate VM.Audit VM.Clone VM.Config.CDROM VM.Config.Cloudinit VM.Config.CPU VM.Config.Disk VM.Config.HWType VM.Config.Memory VM.Config.Network VM.Config.Options VM.Migrate VM.PowerMgmt"
pveum user add terraform@pve --comment "Terraform: Stackat demo cluster"
pveum aclmod / -user terraform@pve -role StackatDemo
pveum user token add terraform@pve demo --privsep 0
```

The last command prints the token's secret once. Keep that window open for the next step.

### On your Mac

```sh
brew install terraform kubectl
git clone https://github.com/self-maintaining-api/demo-homelab-k3s.git && cd demo-homelab-k3s
cp .env.example .env
```

Open `.env` in an editor and paste the secret after `terraform@pve!demo=`. It never leaves your Mac (`.env` is ignored
by git).

If your SSH key is not `~/.ssh/id_ed25519.pub`, or `192.168.178.20` is taken:

```sh
cp terraform/terraform.tfvars.example terraform/terraform.tfvars   # then uncomment and change the lines you need
```

## Build it

```sh
make plan      # what Terraform will create; nothing changes yet
make up        # the VM, k3s, Argo CD and every app (about 10 minutes)
make status    # every app should reach Synced / Healthy
make urls
```

`make help` lists the rest (`argocd-password`, `grafana-password`, `headlamp-token`, `ssh`).

The UIs use `*.192.168.178.20.nip.io`, a public name that points at the VM. A FRITZ!Box blocks such answers (DNS
rebind protection): add `nip.io` under Home Network → Network → Network Settings → DNS Rebind Protection, or put the
names in `/etc/hosts`:

```sh
echo "192.168.178.20 argocd.192.168.178.20.nip.io grafana.192.168.178.20.nip.io headlamp.192.168.178.20.nip.io" | sudo tee -a /etc/hosts
```

The certificates come from the cluster's own CA, so the browser warns once.

## Tear it down

```sh
make destroy
```

The VM and the downloaded image go; nothing else on the Proxmox host changes.

## With Stackat

Stackat is installed on this repository. It finds the 11 charts, the CRDs the manifests use and the Proxmox provider,
and opens an issue per tool that is behind. Reply `/stackpaw pr` (or let `auto_pr` do it), review, merge: Argo CD
syncs the new version within three minutes. Settings are in `.stackat.yml`.

k3s itself is pinned in `scripts/bootstrap.sh` (`K3S_VERSION`) and upgraded by hand: change it and run
`make bootstrap` again.
