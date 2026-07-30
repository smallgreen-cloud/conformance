#!/usr/bin/env python3
"""Profile 靜態判定（SAP-1/2/4 與 PIP-1/3 靜態子集）：wrangler 存在與解析、資源允許清單、常駐程序檔、pipeline 觸發器。

用法：check_profile.py --spec <spec repo 路徑> --repo <受檢 repo 路徑>
SAP-5/7（行為分析、agent 矩陣）與 SAP-6/PIP-2/8（GitHub API）不在本腳本：前者屬部署期，後者由 CI 端以 GITHUB_TOKEN 檢查（缺 token 時標 skipped）。
"""
import argparse
import os
import sys
from pathlib import Path

from sg_common import Report, die, find_all_wrangler, load_wrangler, load_yaml, parse_wrangler_file

FORBIDDEN_FILES = ["Dockerfile", "docker-compose.yml", "docker-compose.yaml", "Procfile"]
# wrangler 的「資源型」top-level key 全集（白名單語意：出現在此集合但不在 spec 允許清單 → fail）。
# 非資源 key（name/main/compatibility_date/vars/observability…）不在此集合，不受 SAP-2 管。
WRANGLER_RESOURCE_KEYS = {
    "d1_databases", "kv_namespaces", "r2_buckets", "ai", "assets",
    "queues", "durable_objects", "hyperdrive", "vectorize", "browser",
    "analytics_engine_datasets", "send_email", "services", "workflows",
    "pipelines", "dispatch_namespaces", "mtls_certificates", "tail_consumers",
    "queues_consumers", "version_metadata", "unsafe",
}
EXCLUDED_KEY_TO_NAME = {
    "queues": "queues",
    "durable_objects": "durable_objects",
    "hyperdrive": "hyperdrive",
    "vectorize": "vectorize",
    "browser": "browser_rendering",
}


def allowed_wrangler_keys(allowlist: dict) -> set:
    keys = set()
    for entry in (allowlist.get("allowed") or {}).values():
        for k in entry.get("wrangler_keys") or []:
            keys.add(k.split(".")[0].split("[")[0])
    return keys


def declared_profile(repo: Path) -> str:
    p = repo / ".smallgreen" / "profile.yaml"
    if p.exists():
        try:
            return (load_yaml(p) or {}).get("profile", "small-app")
        except Exception:
            pass
    return "small-app"


def resource_hits(wcfg: dict, allowlist: dict, prefix: str = "") -> list:
    allowed = allowed_wrangler_keys(allowlist)
    hits = []
    for key in sorted(WRANGLER_RESOURCE_KEYS):
        if key not in wcfg or key in allowed:
            continue
        name = EXCLUDED_KEY_TO_NAME.get(key)
        if name and name in (allowlist.get("excluded") or {}):
            hits.append(f"{prefix}{key}（{allowlist['excluded'][name].get('reason', '')}）")
        else:
            hits.append(f"{prefix}{key}（不在 v0.1 允許清單——未評估資源，請開 spec issue 附免費層額度證據）")
    # DO 條件式：免費層限 SQLite-backed；new_classes（KV-backed）＝付費限定
    for mig in wcfg.get("migrations", []) or []:
        if isinstance(mig, dict) and mig.get("new_classes"):
            hits.append(f"{prefix}migrations[].new_classes（KV-backed durable_objects 為付費限定；免費層限 new_sqlite_classes）")
    if "durable_objects" in wcfg and "durable_objects" in allowed:
        migs = wcfg.get("migrations", []) or []
        has_sqlite = any(isinstance(m, dict) and m.get("new_sqlite_classes") for m in migs)
        if not migs:
            hits.append(f"{prefix}durable_objects 宣告但無 migrations——無法確認 SQLite-backed（免費層條件）")
        elif not has_sqlite:
            hits.append(f"{prefix}durable_objects 宣告但 migrations 無 new_sqlite_classes——免費層限 SQLite-backed")
    return hits


def check_small_app(rep: Report, repo: Path, allowlist: dict):
    # SAP-1（v0.1.3）：根目錄或子目錄（深度 ≤3）存在至少一個可解析的 wrangler 設定
    configs = find_all_wrangler(repo)
    if not configs:
        rep.add("SAP-1", False, "找不到任何 wrangler.jsonc / wrangler.toml / wrangler.json（根目錄與深度 3 內子目錄）")
        rep.add("SAP-2", False, reasons="因 SAP-1 失敗無法判定")
        return
    parse_fails = [str(p.relative_to(repo)) for p in configs if parse_wrangler_file(p) is None]
    if parse_fails:
        rep.add("SAP-1", False, [f"{p} 解析失敗" for p in parse_fails])
        rep.add("SAP-2", False, reasons="因 SAP-1 失敗無法判定")
        return
    rep.add("SAP-1", True, f"{len(configs)} 個 wrangler 設定：{', '.join(str(p.relative_to(repo)) for p in configs)}")

    # 多 worker monorepo：所有 wrangler 設定檔都受 SAP-2 判定
    hits = []
    for cfg_path in configs:
        cfg = parse_wrangler_file(cfg_path)
        hits.extend(resource_hits(cfg, allowlist, prefix=f"{cfg_path.relative_to(repo)}: "))
    rep.add("SAP-2", not hits, hits or None)


FILE_TO_ALT_LABEL = {
    "Dockerfile": "docker",
    "docker-compose.yml": "docker-compose",
    "docker-compose.yaml": "docker-compose",
    "Procfile": "procfile",
}


def check_no_daemon_files(rep: Report, repo: Path):
    """SAP-4 v0.2：常駐基礎設施檔存在時必須在 profile.yaml alt_deployment 揭露（issue #4）。"""
    declared = set()
    prof = repo / ".smallgreen" / "profile.yaml"
    if prof.exists():
        try:
            declared = set((load_yaml(prof) or {}).get("alt_deployment") or [])
        except Exception:
            pass
    hits = []
    for f in FORBIDDEN_FILES:
        if not (repo / f).exists():
            continue
        label = FILE_TO_ALT_LABEL.get(f, "other")
        if label not in declared:
            hits.append(f"{f} 存在但未在 profile.yaml alt_deployment 揭露（已揭露＝pass＋服務卡標注）")
    rep.add("SAP-4", not hits, hits or None)


def check_pipeline(rep: Report, repo: Path):
    wf_dir = repo / ".github" / "workflows"
    workflows = sorted(wf_dir.glob("*.y*ml")) if wf_dir.is_dir() else []
    triggered = []
    min_interval_ok = True
    interval_reasons = []
    for wf in workflows:
        try:
            doc = load_yaml(wf) or {}
        except Exception:
            continue
        on = doc.get("on", doc.get(True, {}))  # YAML 會把 on 解析成 True
        if isinstance(on, str):
            on = {on: None}
        if isinstance(on, list):
            on = {k: None for k in on}
        if "schedule" in on or "workflow_dispatch" in on:
            triggered.append(wf.name)
        for sched in (on or {}).get("schedule") or []:
            cron = (sched or {}).get("cron", "")
            minute = cron.split()[0] if cron else ""
            if minute.startswith("*/"):
                try:
                    if int(minute[2:]) < 5:
                        min_interval_ok = False
                        interval_reasons.append(f"{wf.name}: cron '{cron}' 間隔 < 5 分鐘")
                except ValueError:
                    pass
            if minute == "*":
                min_interval_ok = False
                interval_reasons.append(f"{wf.name}: cron '{cron}' 每分鐘觸發")
    rep.add("PIP-1", bool(triggered), None if triggered else "無 schedule/workflow_dispatch 觸發的 workflow")
    rep.add("PIP-3:interval", min_interval_ok, interval_reasons or None)

    prof = repo / ".smallgreen" / "profile.yaml"
    has_estimate = False
    if prof.exists():
        try:
            has_estimate = "estimated_minutes_per_run" in ((load_yaml(prof) or {}).get("pipeline") or {})
        except Exception:
            pass
    rep.add("PIP-3:estimate", has_estimate, None if has_estimate else "profile.yaml 缺 pipeline.estimated_minutes_per_run")


def check_license_via_api(rep: Report, req_id: str):
    repo_slug = os.environ.get("GITHUB_REPOSITORY")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not repo_slug or not token:
        rep.add(req_id, True, "無 GITHUB_REPOSITORY/GITHUB_TOKEN，於 CI 外執行時跳過", skipped=True)
        return
    import json
    import urllib.request

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo_slug}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except Exception as exc:
        rep.add(req_id, False, f"GitHub API 查詢失敗: {exc}")
        return
    lic = (data.get("license") or {}).get("spdx_id")
    ok = bool(lic) and lic != "NOASSERTION"
    rep.add(req_id, ok, None if ok else f"license 欄位為 {lic!r}（需 OSI-approved license）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, type=Path)
    ap.add_argument("--repo", required=True, type=Path)
    args = ap.parse_args()
    allowlist_path = args.spec / "profiles" / "free-tier-allowlist.yaml"
    if not allowlist_path.exists():
        die(f"允許清單不存在: {allowlist_path}")
    allowlist = load_yaml(allowlist_path)

    profile = declared_profile(args.repo)
    rep = Report(f"profile 靜態判定（{profile}）")

    if "small-app" in profile:
        check_small_app(rep, args.repo, allowlist)
        check_license_via_api(rep, "SAP-6")
    if "pipeline" in profile:
        check_pipeline(rep, args.repo)
        check_license_via_api(rep, "PIP-8")
    check_no_daemon_files(rep, args.repo)

    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
