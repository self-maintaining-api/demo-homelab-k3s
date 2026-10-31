# Stackat demo: a real cluster that tells you what breaks before you upgrade

This is a public demo of [Stackat](https://stackat.dev). It is not a sample: everything in this repository runs on a
real Kubernetes cluster (k3s), deployed by Argo CD straight from `main`. The tools are pinned a few releases behind on
purpose, so you can watch Stackat do its job here in the open.

**See it in action:**

- **[Issues](../../issues?q=label%3Astackat)**: one per tool that is behind. Each says what changes between the pinned
  version and the latest, what in *this* repository it touches (file and line), and gives a verdict: safe to upgrade,
  review, edits needed or migration.
- **[Pull requests](../../pulls)**: the version bump, ready when nothing needs changing, a draft with the checklist when
  something does.
- **The upgrade diff** on every pull request: a GitHub Action renders the chart at both versions and comments what
  really changes in the cluster. It is our own check on Stackat: anything there that the issue did not mention is a
  miss we want to know about.
- **[`.stackat.yml`](.stackat.yml)**: the settings this repository uses (pull requests on, who may ask for them, what
  counts as up to date).

## What runs here

| App | What to look for |
| --- | --- |
| Argo CD | Argo CD deploys everything, itself included: merging its pull request upgrades Argo CD |
| cert-manager | An edit needed: the issue points at the exact line in `manifests/cert-manager-issuers` that a default change affects |
| trust-manager | Its `Bundle` resource (`manifests/trust-bundle`) |
| ingress-nginx | Snippet annotations are on (the setting behind 2025's IngressNightmare CVEs) |
| External Secrets | A safe upgrade: nothing in the release notes touches this repository, so the pull request is ready to merge |
| Kyverno | Policies and a PolicyException (`manifests/kyverno-policies`) |
| Reloader | Restarts podinfo when its secret changes |
| Prometheus | Metrics, with probes of every UI |
| Blackbox exporter | The probes: an upgrade that breaks a UI shows up, release notes or not |
| Grafana | Dashboards, including the running images' vulnerabilities |
| trivy-operator | Scans the images that actually run, to compare with the CVEs an upgrade fixes |
| metrics-server | `kubectl top` |
| descheduler | Runs every half hour |
| Headlamp | A read-only Kubernetes UI |

The versions running now are the `targetRevision` in each file under `apps/`; they move as pull requests are merged.

**Every option of every chart is set explicitly** (about 4,000 settings across the charts), at the default of the version
it was written for, with this repository's own choices on top; images (registry, repository, tag, digest) are left to
the chart, so an upgrade still upgrades the images, and one that swaps an image gets the new one. That way any release note about any option touches this repository, and an option a
new chart renames or removes shows up in the upgrade diff instead of being ignored by Helm in silence. The defaults
come from `tools/chart-defaults/`; `tools/gen_apps.py` writes the apps.

Plus podinfo, a small web app pinned by image tag, and the Terraform provider that builds the virtual machine
(`terraform/`, also pinned behind). Many chart features are switched on, so release notes and security advisories about
them have something real to match.

## Upgrade alerts

Every upgrade that reaches the cluster ends in one Slack message from Argo CD: rolled out healthy, Degraded after
the upgrade, failed to sync, or still not healthy 10 minutes later. A red one means that release needs care before
anyone else upgrades, and it is how we check Stackat's verdicts against a real cluster. The rules are Argo CD
notifications in `apps/argo-cd.yaml`; the Slack webhook is a Kubernetes secret that never enters this repository.

## How the loop works

1. Stackat reads every release note between the version pinned here and the latest, for each tool.
2. It compares them with this repository's own files: the values set, the custom resources used, the features turned on
   or off.
3. It opens one issue per tool with what to change, and a pull request with the bump.
4. The upgrade-diff workflow comments what the bump really changes.
5. A maintainer merges; Argo CD rolls it out within three minutes; Stackat closes the issue on its next scan.

## Repository layout

| Path | What it is |
| --- | --- |
| `apps/` | One Argo CD Application per tool (Helm chart, pinned version, values), written by `tools/gen_apps.py` |
| `manifests/` | Plain resources the apps use: the CA, policies, the demo app |
| `argocd/root.yaml` | The app of apps that points Argo CD at `apps/` |
| `terraform/` | The virtual machine (Proxmox) |
| `scripts/` | Installs k3s and Argo CD on a fresh machine |
| `tools/upgrade_diff.py` | The upgrade diff behind the pull request comments |

## Run it yourself

It runs on a Proxmox host with about 5 GiB of RAM and 4 vCPU to spare. You need Terraform and kubectl, a Proxmox API
token allowed to create VMs and download images (with the `import` content type enabled on the image storage), and an
SSH key. Copy `.env.example` to `.env` and `terraform/terraform.tfvars.example` to `terraform/terraform.tfvars`, fill
them in (both are ignored by git), then:

```sh
make plan     # what Terraform will create
make up       # the VM, k3s, Argo CD and every app (about 10 minutes)
make status   # every app Synced / Healthy
make hosts    # the /etc/hosts line for the UIs (*.demo-k3s.internal)
```

`make help` lists the rest. To run it from your own copy, change the repository address in `argocd/root.yaml` and `apps/`.

## Try Stackat on your own repositories

[stackat.dev](https://stackat.dev) · [Documentation](https://docs.stackat.dev) · 14 days free, then a free plan for one
repository.
