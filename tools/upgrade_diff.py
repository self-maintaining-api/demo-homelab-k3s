#!/usr/bin/env python3
"""What a pull request really changes in the cluster, for every Argo CD app (apps/*.yaml) it touches.

Renders each chart at the base and the head version with `helm template` (the same values Argo CD uses) and writes a
Markdown report:

- resources added and removed, and the container images that change;
- CRDs whose served versions change (a removed version breaks the custom resources that still use it);
- chart defaults that changed for settings this repo does NOT set: behaviour that shifts without anyone touching the
  values, the easiest thing for release notes to leave out;
- settings this repo sets that the new chart no longer has: Helm ignores them silently;
- the full manifest diff per resource, folded.

It is how to check a Stackat issue against reality: everything in here should be in the issue, or be harmless.

Usage: python3 tools/upgrade_diff.py --base origin/main [--out report.md]
Needs git and helm (3.x) on the PATH and network access to the chart repositories.
"""
from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

NOISE_LABELS = ("helm.sh/chart", "app.kubernetes.io/version", "chart", "heritage", "release")
NOISE_ANNOTATIONS = ("checksum/",)
MAX_RESOURCE_DIFF = 120  # lines per resource in the folded diff
MAX_REPORT = 60000       # GitHub comments stop at 65536 characters


def git_show(ref: str, path: str) -> str | None:
    out = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def changed_apps(base: str) -> list[str]:
    out = subprocess.run(["git", "diff", "--name-only", f"{base}...HEAD", "--", "apps/"], capture_output=True, text=True,
                         check=True)
    return [p for p in out.stdout.split() if p.endswith(".yaml")]


def chart_source(text: str | None) -> dict | None:
    """repoURL, chart, version, release, namespace and values of an Argo CD Application that installs a Helm chart."""
    if not text:
        return None
    doc = yaml.safe_load(text)
    spec = (doc or {}).get("spec") or {}
    source = spec.get("source") or {}
    if "chart" not in source:
        return None
    helm = source.get("helm") or {}
    values = helm.get("valuesObject") or (yaml.safe_load(helm["values"]) if helm.get("values") else {}) or {}
    return {"repo": source["repoURL"], "chart": source["chart"], "version": str(source["targetRevision"]),
            "release": helm.get("releaseName") or doc["metadata"]["name"],
            "namespace": (spec.get("destination") or {}).get("namespace") or "default", "values": values}


def helm(*args: str) -> str:
    out = subprocess.run(["helm", *args], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f"helm {' '.join(args[:3])} …: {out.stderr.strip()[:500]}")
    return out.stdout


def render(src: dict, workdir: Path) -> dict[str, dict]:
    values = workdir / f"values-{src['version']}.yaml"
    values.write_text(yaml.safe_dump(src["values"]))
    text = helm("template", src["release"], src["chart"], "--repo", src["repo"], "--version", src["version"],
                "--namespace", src["namespace"], "--include-crds", "--skip-tests", "-f", str(values))
    return {key(d): clean(d) for d in yaml.safe_load_all(text) if isinstance(d, dict) and d.get("kind")}


def chart_defaults(src: dict) -> dict:
    return yaml.safe_load(helm("show", "values", src["chart"], "--repo", src["repo"], "--version", src["version"])) or {}


def key(doc: dict) -> str:
    meta = doc.get("metadata") or {}
    return f"{doc['kind']}/{meta.get('namespace', '') + '/' if meta.get('namespace') else ''}{meta.get('name', '?')}"


def clean(doc: dict) -> dict:
    """Drop what changes on every release without meaning anything: chart version labels, config checksums."""
    def strip(meta: dict | None) -> None:
        if not isinstance(meta, dict):
            return
        for field, noise in (("labels", NOISE_LABELS), ("annotations", NOISE_ANNOTATIONS)):
            items = meta.get(field)
            if isinstance(items, dict):
                for k in [k for k in items if any(k == n or k.startswith(n) for n in noise)]:
                    del items[k]
                if not items:
                    del meta[field]
    strip(doc.get("metadata"))
    template = ((doc.get("spec") or {}).get("template") or {}) if isinstance(doc.get("spec"), dict) else {}
    strip(template.get("metadata") if isinstance(template, dict) else None)
    return doc


def images(resources: dict[str, dict]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}

    def walk(node, owner):
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "image" and isinstance(v, str):
                    found.setdefault(v.rsplit(":", 1)[0].split("@")[0], set()).add(v)
                else:
                    walk(v, owner)
        elif isinstance(node, list):
            for v in node:
                walk(v, owner)
    for name, doc in resources.items():
        walk(doc.get("spec"), name)
    return found


def crd_versions(resources: dict[str, dict]) -> dict[str, list[str]]:
    return {doc["metadata"]["name"]: [v["name"] for v in doc.get("spec", {}).get("versions", []) if v.get("served", True)]
            for doc in resources.values() if doc["kind"] == "CustomResourceDefinition"}


def flatten(node, prefix: str = "") -> dict[str, object]:
    """Dotted paths to leaves; lists count as one value (they are replaced, not merged, by Helm)."""
    out: dict[str, object] = {}
    if isinstance(node, dict) and node:
        for k, v in node.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    else:
        out[prefix] = node
    return out


def is_set(path: str, mine: dict[str, object]) -> bool:
    """The repo sets this path, or a parent of it (a whole block), or something under it."""
    return any(path == p or path.startswith(p + ".") or p.startswith(path + ".") for p in mine)


def short(value) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= 60 else text[:57] + "…"


def report_app(path: str, old: dict, new: dict, workdir: Path) -> list[str]:
    title = f"### `{path}`: {old['chart']} {old['version']} → {new['version']}"
    if old["repo"] != new["repo"] or old["chart"] != new["chart"]:
        title += f" (chart moved: {old['repo']}/{old['chart']} → {new['repo']}/{new['chart']})"
    lines = [title, ""]
    try:
        before, after = render(old, workdir), render(new, workdir)
        defaults_old, defaults_new = chart_defaults(old), chart_defaults(new)
    except RuntimeError as error:
        return lines + [f"Could not render: {error}", ""]

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    img_old, img_new = images(before), images(after)
    image_changes = [(repo, ", ".join(sorted(img_old.get(repo, {"(none)"}))), ", ".join(sorted(img_new.get(repo, {"(none)"}))))
                     for repo in sorted(set(img_old) | set(img_new)) if img_old.get(repo) != img_new.get(repo)]
    crd_old, crd_new = crd_versions(before), crd_versions(after)
    crd_changes = [(name, crd_old.get(name, []), crd_new.get(name, [])) for name in sorted(set(crd_old) | set(crd_new))
                   if crd_old.get(name) != crd_new.get(name)]

    mine = flatten(new["values"])
    flat_old, flat_new = flatten(defaults_old), flatten(defaults_new)
    shifted = [(p, flat_old.get(p, "(absent)"), flat_new.get(p, "(absent)")) for p in sorted(set(flat_old) | set(flat_new))
               if flat_old.get(p, "(absent)") != flat_new.get(p, "(absent)") and not is_set(p, mine)]
    gone = sorted(p for p in mine if p not in flat_new and not any(q.startswith(p + ".") for q in flat_new)
                  and not any(p.startswith(q + ".") and isinstance(flat_new[q], (dict, type(None))) for q in flat_new)
                  and (p in flat_old or any(q.startswith(p + ".") for q in flat_old)))

    lines.append(f"| Resources added | removed | changed | Images changed | CRD versions changed | Defaults shifted (not set here) "
                 f"| Settings no longer in the chart |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    lines.append(f"| {len(added)} | {len(removed)} | {len(changed)} | {len(image_changes)} | {len(crd_changes)} | {len(shifted)} | "
                 f"{len(gone)} |")
    lines.append("")
    if gone:
        lines += ["**⚠️ Set in this repo, gone from the new chart (Helm ignores them silently):**", ""]
        lines += [f"- `{p}`" for p in gone] + [""]
    if crd_changes:
        lines += ["**CRD versions served:**", ""]
        lines += [f"- `{n}`: {', '.join(o) or '(new)'} → {', '.join(v) or '(removed)'}" for n, o, v in crd_changes] + [""]
    if removed or added:
        lines += ["**Resources:**", ""]
        lines += [f"- ➖ `{k}`" for k in removed] + [f"- ➕ `{k}`" for k in added] + [""]
    if image_changes:
        lines += ["**Images:**", "", "| Image | Before | After |", "| --- | --- | --- |"]
        lines += [f"| `{r}` | `{o}` | `{n}` |" for r, o, n in image_changes] + [""]
    if shifted:
        lines += [f"<details><summary>Chart defaults that changed and this repo does not set ({len(shifted)})</summary>", "",
                  "| Value | Before | After |", "| --- | --- | --- |"]
        lines += [f"| `{p}` | `{short(o)}` | `{short(n)}` |" for p, o, n in shifted[:150]]
        if len(shifted) > 150:
            lines.append(f"| … and {len(shifted) - 150} more | | |")
        lines += ["", "</details>", ""]
    if changed:
        lines += [f"<details><summary>Manifest diff ({len(changed)} changed resources)</summary>", ""]
        for k in changed:
            diff = list(difflib.unified_diff(yaml.safe_dump(before[k], sort_keys=True).splitlines(),
                                             yaml.safe_dump(after[k], sort_keys=True).splitlines(), "before", "after", lineterm="", n=2))
            body = diff[2:MAX_RESOURCE_DIFF + 2] + ([f"… {len(diff) - MAX_RESOURCE_DIFF - 2} more lines"] if len(diff) > MAX_RESOURCE_DIFF + 2 else [])
            lines += [f"`{k}`", "", "```diff", *body, "```", ""]
        lines += ["</details>", ""]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="git ref to compare with, e.g. origin/main")
    parser.add_argument("--out", default="-")
    args = parser.parse_args()

    out = ["## What this pull request changes in the cluster", "",
           "Rendered with `helm template` at both versions, with this repo's values (tools/upgrade_diff.py). Anything "
           "here that the Stackat issue does not mention is worth a look.", ""]
    found = 0
    with tempfile.TemporaryDirectory() as tmp:
        for path in changed_apps(args.base):
            old, new = chart_source(git_show(args.base, path)), chart_source(Path(path).read_text() if Path(path).exists() else None)
            if not old or not new or (old["version"] == new["version"] and old["values"] == new["values"] and old["repo"] == new["repo"]):
                continue
            found += 1
            out += report_app(path, old, new, Path(tmp))
    if not found:
        out.append("No Helm chart version or values changed.")
    text = "\n".join(out)
    if len(text) > MAX_REPORT:
        text = text[:MAX_REPORT] + "\n\n… cut off: the full report is in the workflow run's summary.\n"
    if args.out == "-":
        sys.stdout.write(text + "\n")
    else:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
