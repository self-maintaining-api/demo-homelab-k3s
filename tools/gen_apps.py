"""Writes apps/*.yaml (the Argo CD Applications) from one place: chart, pinned version, values.

Run after changing it: python3 tools/gen_apps.py. Stackat's pull requests edit apps/*.yaml directly; that is fine,
this file keeps whatever version apps/ already has (current_version), so it never undoes a merged upgrade. Resource requests are set to what each pod uses at
rest on this cluster (4 vCPU, 5 GiB); memory limits leave headroom for start-up and upgrades.
"""
import re
from pathlib import Path

DOMAIN = "demo-k3s.internal"  # the UIs' names; ".internal" is reserved for private networks, so no public DNS has it
REPO = "https://github.com/self-maintaining-api/demo-homelab-k3s.git"
OUT = Path(__file__).resolve().parent.parent / "apps"
FILES = {"argocd": "argo-cd"}  # Application name -> file in apps/, where they differ


def indent(text: str, n: int = 8) -> str:
    return "\n".join((" " * n + line) if line.strip() else "" for line in text.strip("\n").splitlines()) + "\n"


def current_version(name: str, version: str) -> str:
    """The version already in apps/<name>.yaml when there is one: merged upgrades (Stackat's pull requests) stay merged.
    The version written here is only used for a new app."""
    existing = OUT / f"{name}.yaml"
    if existing.exists():
        found = re.search(r"^    targetRevision: (\S+)$", existing.read_text(), re.M)
        if found:
            return found.group(1)
    return version


def chart_app(name, ns, repo, chart, version, values, wave, ssa=False, release=None, comment=""):
    version = current_version(FILES.get(name, name), version)
    opts = ["CreateNamespace=true"] + (["ServerSideApply=true"] if ssa else [])
    head = "".join(f"# {line}\n" for line in comment.splitlines()) if comment else ""
    rel = f"\n      releaseName: {release}" if release else ""
    return f"""{head}apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {name}
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "{wave}"
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: {repo}
    chart: {chart}
    targetRevision: {version}
    helm:{rel}
      valuesObject:
{indent(values).rstrip()}
  destination:
    server: https://kubernetes.default.svc
    namespace: {ns}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
""" + "".join(f"      - {o}\n" for o in opts) + RETRY


def dir_app(name, path, ns, wave, comment):
    return f"""# {comment}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {name}
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: "{wave}"
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: {REPO}
    targetRevision: main
    path: {path}
  destination:
    server: https://kubernetes.default.svc
    namespace: {ns}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - SkipDryRunOnMissingResource=true  # the CRDs come from another app; retried until they exist
""" + RETRY


RETRY = """    retry:
      limit: 10
      backoff:
        duration: 20s
        factor: 2
        maxDuration: 5m
"""

SCRAPE = 'prometheus.io/scrape: "true"'

APPS = {}

APPS["argo-cd"] = chart_app("argocd", "argocd", "https://argoproj.github.io/argo-helm", "argo-cd", "10.8.4", f"""
# Argo CD manages itself: a merged pull request that bumps this version upgrades Argo CD.
dex:
  enabled: false  # no SSO on a LAN demo; the admin user signs in
notifications:
  enabled: true
  resources:
    requests:
      cpu: 5m
      memory: 32Mi
    limits:
      memory: 96Mi
configs:
  params:
    server.insecure: true  # TLS ends at ingress-nginx
    controller.status.processors: 5
    controller.operation.processors: 2
    reposerver.parallelism.limit: 2
  cm:
    timeout.reconciliation: 180s
    statusbadge.enabled: true
    exec.enabled: true
    kustomize.buildOptions: --enable-helm
    # trivy-operator writes a report per workload and rewrites them on every scan; Argo CD manages none of them,
    # and watching them all crashed the controller (out of memory). Kyverno's reports are in the chart's defaults.
    resourceExclusionsAdditional:
      - apiGroups: [aquasecurity.github.io]
        kinds: ["*"]
        clusters: ["*"]
controller:
  resources:
    requests:
      cpu: 50m
      memory: 256Mi
    limits:
      memory: 1Gi  # measured: over 512 MiB with ~20 apps and the reports above
  metrics:
    enabled: true
    service:
      annotations:
        {SCRAPE}
        prometheus.io/port: "8082"
repoServer:
  resources:
    requests:
      cpu: 20m
      memory: 96Mi
    limits:
      memory: 384Mi
  metrics:
    enabled: true
server:
  resources:
    requests:
      cpu: 10m
      memory: 48Mi
    limits:
      memory: 192Mi
  metrics:
    enabled: true
  ingress:
    enabled: true
    ingressClassName: nginx
    hostname: argocd.{DOMAIN}
    annotations:
      cert-manager.io/cluster-issuer: demo-ca
    tls: true
applicationSet:
  replicas: 1
  resources:
    requests:
      cpu: 5m
      memory: 32Mi
    limits:
      memory: 128Mi
redis:
  resources:
    requests:
      cpu: 5m
      memory: 16Mi
    limits:
      memory: 96Mi
""", 1, release="argocd",
    comment="Installed first by scripts/vm-bootstrap.sh (same release name), then adopted by this Application.")

APPS["cert-manager"] = chart_app("cert-manager", "cert-manager", "https://charts.jetstack.io", "cert-manager", "v1.18.6", """
crds:
  enabled: true
  keep: true
enableCertificateOwnerRef: true  # deleting a Certificate deletes its Secret
prometheus:
  enabled: true  # metrics, scraped through the service's prometheus.io annotations
  servicemonitor:
    enabled: false
resources:
  requests:
    cpu: 5m
    memory: 48Mi
  limits:
    memory: 160Mi
webhook:
  resources:
    requests:
      cpu: 5m
      memory: 24Mi
    limits:
      memory: 96Mi
cainjector:
  resources:
    requests:
      cpu: 5m
      memory: 48Mi
    limits:
      memory: 192Mi
""", -3, ssa=True)

APPS["trust-manager"] = chart_app("trust-manager", "cert-manager", "https://charts.jetstack.io", "trust-manager", "v0.23.0", """
# Copies the demo CA into a ConfigMap in every namespace (manifests/trust-bundle), so apps can trust the ingresses.
secretTargets:
  enabled: true
  authorizedSecretsAll: true
resources:
  requests:
    cpu: 5m
    memory: 32Mi
  limits:
    memory: 128Mi
""", -1, ssa=True)

APPS["ingress-nginx"] = chart_app("ingress-nginx", "ingress-nginx", "https://kubernetes.github.io/ingress-nginx", "ingress-nginx", "4.12.8", f"""
controller:
  replicaCount: 1
  service:
    type: LoadBalancer  # k3s' service load balancer puts it on the VM's own address, ports 80 and 443
  allowSnippetAnnotations: true  # on purpose: the setting behind 2025's IngressNightmare CVEs, so advisories match here
  config:
    annotations-risk-level: Critical
    use-forwarded-headers: "true"
    enable-real-ip: "true"
    log-format-escape-json: "true"
  admissionWebhooks:
    enabled: true
  metrics:
    enabled: true
  podAnnotations:
    {SCRAPE}
    prometheus.io/port: "10254"
  resources:
    requests:
      cpu: 20m
      memory: 96Mi
    limits:
      memory: 256Mi
""", -2, comment="Upstream retired ingress-nginx in 2026; it stays here because that is exactly what Stackat should flag.")

APPS["external-secrets"] = chart_app("external-secrets", "external-secrets", "https://charts.external-secrets.io", "external-secrets", "2.11.0", """
# installCRDs is left at the chart's default on purpose: Stackat's issues show how to check a setting the repo does not set.
processClusterStore: true
processClusterExternalSecret: true
processPushSecret: true
resources:
  requests:
    cpu: 5m
    memory: 32Mi
  limits:
    memory: 128Mi
webhook:
  resources:
    requests:
      cpu: 5m
      memory: 24Mi
    limits:
      memory: 96Mi
certController:
  resources:
    requests:
      cpu: 5m
      memory: 32Mi
    limits:
      memory: 128Mi
""", -1, ssa=True)

APPS["kyverno"] = chart_app("kyverno", "kyverno", "https://kyverno.github.io/kyverno", "kyverno", "3.6.4", """
features:
  policyExceptions:
    enabled: true
    namespace: kyverno
  admissionReports:
    enabled: true
admissionController:
  replicas: 1
  container:
    resources:
      requests:
        cpu: 20m
        memory: 128Mi
      limits:
        memory: 384Mi
backgroundController:
  replicas: 1
  resources:
    requests:
      cpu: 10m
      memory: 48Mi
    limits:
      memory: 192Mi
cleanupController:
  replicas: 1
  resources:
    requests:
      cpu: 5m
      memory: 32Mi
    limits:
      memory: 128Mi
reportsController:
  replicas: 1
  resources:
    requests:
      cpu: 10m
      memory: 48Mi
    limits:
      memory: 192Mi
""", -1, ssa=True)

APPS["metrics-server"] = chart_app("metrics-server", "kube-system", "https://kubernetes-sigs.github.io/metrics-server", "metrics-server", "3.12.2", """
args:
  - --kubelet-insecure-tls  # k3s kubelets serve self-signed certificates
metrics:
  enabled: true
resources:
  requests:
    cpu: 10m
    memory: 32Mi
  limits:
    memory: 96Mi
""", 0, comment="k3s' built-in metrics-server is turned off (scripts/vm-bootstrap.sh) so this chart owns it.")

APPS["reloader"] = chart_app("reloader", "reloader", "https://stakater.github.io/stakater-charts", "reloader", "2.1.5", """
reloader:
  watchGlobally: true
  reloadOnCreate: true
  enableMetricsByNamespace: true
  deployment:
    resources:
      requests:
        cpu: 5m
        memory: 24Mi
      limits:
        memory: 96Mi
""", 0)

APPS["prometheus"] = chart_app("prometheus", "monitoring", "https://prometheus-community.github.io/helm-charts", "prometheus", "29.36.2", """
alertmanager:
  enabled: false
prometheus-pushgateway:
  enabled: false
kube-state-metrics:
  enabled: true
  resources:
    requests:
      cpu: 5m
      memory: 32Mi
    limits:
      memory: 96Mi
prometheus-node-exporter:
  enabled: true
  resources:
    requests:
      cpu: 5m
      memory: 16Mi
    limits:
      memory: 64Mi
configmapReload:
  prometheus:
    resources:
      requests:
        cpu: 1m
        memory: 8Mi
      limits:
        memory: 32Mi
server:
  global:
    scrape_interval: 1m
    evaluation_interval: 1m
  retention: 3d
  retentionSize: 2GB
  extraFlags:
    - web.enable-lifecycle
  persistentVolume:
    size: 3Gi
  resources:
    requests:
      cpu: 30m
      memory: 384Mi  # measured: about 450 MiB after the first quarter hour, growing with trivy-operator's per-CVE series
    limits:
      memory: 896Mi
# The blackbox exporter probes every UI from inside the cluster: an upgrade that breaks one shows up here,
# whether or not its release notes said anything.
extraScrapeConfigs: |
  - job_name: blackbox-http
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - http://argocd-server.argocd.svc/healthz
          - http://grafana.monitoring.svc/api/health
          - http://headlamp.headlamp.svc/
          - http://podinfo.demo-app.svc:9898/healthz
          - http://prometheus-server.monitoring.svc/-/healthy
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter.monitoring.svc:9115
""", 0)

APPS["prometheus-blackbox-exporter"] = chart_app("prometheus-blackbox-exporter", "monitoring", "https://prometheus-community.github.io/helm-charts", "prometheus-blackbox-exporter", "11.17.2", """
fullnameOverride: blackbox-exporter
resources:
  requests:
    cpu: 5m
    memory: 16Mi
  limits:
    memory: 64Mi
""", 0)

APPS["grafana"] = chart_app("grafana", "monitoring", "https://grafana.github.io/helm-charts", "grafana", "10.2.0", f"""
ingress:
  enabled: true
  ingressClassName: nginx
  annotations:
    cert-manager.io/cluster-issuer: demo-ca
  hosts:
    - grafana.{DOMAIN}
  tls:
    - secretName: grafana-tls
      hosts:
        - grafana.{DOMAIN}
persistence:
  enabled: false  # dashboards come from this repo and grafana.com, nothing to keep
datasources:
  datasources.yaml:
    apiVersion: 1
    datasources:
      - name: Prometheus
        type: prometheus
        url: http://prometheus-server.monitoring.svc
        isDefault: true
sidecar:
  dashboards:
    enabled: true  # also loads dashboards from ConfigMaps labelled grafana_dashboard in any namespace
    searchNamespace: ALL
  resources:
    requests:
      cpu: 5m
      memory: 32Mi
    limits:
      memory: 96Mi
dashboardProviders:
  dashboardproviders.yaml:
    apiVersion: 1
    providers:
      - name: grafana-com
        folder: Stackat demo
        type: file
        options:
          path: /var/lib/grafana/dashboards/grafana-com
dashboards:
  grafana-com:
    node-exporter:
      gnetId: 1860
      revision: 37
      datasource: Prometheus
    blackbox:
      gnetId: 7587
      revision: 3
      datasource: Prometheus
    trivy-operator:
      gnetId: 17813
      revision: 2
      datasource: Prometheus
resources:
  requests:
    cpu: 10m
    memory: 160Mi  # measured: about 190 MiB with the three dashboards
  limits:
    memory: 384Mi
""", 0)

APPS["headlamp"] = chart_app("headlamp", "headlamp", "https://kubernetes-sigs.github.io/headlamp", "headlamp", "0.42.0", f"""
clusterRoleBinding:
  clusterRoleName: view  # read-only: a demo UI, not an admin console
ingress:
  enabled: true
  ingressClassName: nginx
  annotations:
    cert-manager.io/cluster-issuer: demo-ca
  hosts:
    - host: headlamp.{DOMAIN}
      paths:
        - path: /
          type: Prefix
  tls:
    - secretName: headlamp-tls
      hosts:
        - headlamp.{DOMAIN}
resources:
  requests:
    cpu: 5m
    memory: 24Mi
  limits:
    memory: 96Mi
""", 0)

APPS["trivy-operator"] = chart_app("trivy-operator", "trivy-system", "https://aquasecurity.github.io/helm-charts", "trivy-operator", "0.36.0", """
# Scans the images that actually run and keeps a VulnerabilityReport per workload (every CVE: make vulns), with counts
# per image and severity in Prometheus: the cluster's own answer to "which of these CVEs affect us", next to Stackat's.
operator:
  scanJobsConcurrentLimit: 1  # one scan at a time on a small node
  scanJobTTL: 10m
  builtInTrivyServer: true  # one vulnerability database for all scans, not one download per scan
  vulnerabilityScannerEnabled: true
  sbomGenerationEnabled: true
  configAuditScannerEnabled: true
  rbacAssessmentScannerEnabled: true
  exposedSecretScannerEnabled: true
  infraAssessmentScannerEnabled: false
  clusterComplianceEnabled: false
  metricsVulnIdEnabled: false  # one series per CVE and image filled Prometheus; counts per image and severity stay
  metricsFindingsEnabled: true
  metricsConfigAuditInfo: true
trivy:
  resources:
    requests:
      cpu: 50m
      memory: 96Mi
    limits:
      memory: 512Mi
resources:
  requests:
    cpu: 10m
    memory: 64Mi
  limits:
    memory: 256Mi
""", 0, ssa=True)

APPS["descheduler"] = chart_app("descheduler", "kube-system", "https://kubernetes-sigs.github.io/descheduler", "descheduler", "0.34.0", """
kind: CronJob
schedule: "*/30 * * * *"  # every half hour; nothing runs in between
resources:
  requests:
    cpu: 10m
    memory: 32Mi
  limits:
    memory: 96Mi
""", 1)

for name, text in APPS.items():
    (OUT / f"{name}.yaml").write_text(text)

DIRS = {
    "cert-manager-issuers": ("manifests/cert-manager-issuers", "cert-manager", -2, "A private CA for the demo's ingresses (*.demo-k3s.internal)."),
    "trust-bundle": ("manifests/trust-bundle", "cert-manager", 0, "trust-manager copies the demo CA into every namespace."),
    "kyverno-policies": ("manifests/kyverno-policies", "kyverno", 0, "Policies in Audit mode: they report, they never block."),
    "demo-app": ("manifests/demo-app", "demo-app", 1,
                 "podinfo with a secret from External Secrets; Reloader restarts it when the secret changes."),
}
for name, (path, ns, wave, comment) in DIRS.items():
    (OUT / f"{name}.yaml").write_text(dir_app(name, path, ns, wave, comment))
print(f"wrote {len(APPS) + len(DIRS)} applications")
