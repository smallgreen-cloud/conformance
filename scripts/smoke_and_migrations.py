#!/usr/bin/env python3
"""Migration 空庫重放＋本地 smoke（acceptance.yaml health/smoke 的 CI 落點）。

用法：smoke_and_migrations.py --repo <受檢 repo 路徑> [--port 8787] [--skip-smoke]

- migrations/*.sql 依檔名序在乾淨本地 D1（miniflare state）重放
- wrangler dev 啟動後打 health，再跑 smoke（v0.1 支援 action: http_request 與 wait；
  其他 action 標 skipped——那些屬裁判層 full suite）
- expect 支援 status 與 body_contains；其他鍵忽略（裁判層解讀）
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from sg_common import Report, load_wrangler, load_yaml


def run_migrations(rep: Report, repo: Path, persist_dir: str) -> bool:
    _, wcfg = load_wrangler(repo)
    migrations = sorted((repo / "migrations").glob("*.sql"))
    if not migrations:
        rep.add("migration-replay", True, "無 migrations/，跳過", skipped=True)
        return True
    d1s = (wcfg or {}).get("d1_databases") or []
    if not d1s:
        rep.add("migration-replay", False, "有 migrations/ 但 wrangler 無 d1_databases 宣告")
        return False
    db_name = d1s[0].get("database_name")
    for sql in migrations:
        proc = subprocess.run(
            ["npx", "--yes", "wrangler", "d1", "execute", db_name, "--local",
             "--persist-to", persist_dir, "--file", str(sql.resolve())],
            cwd=repo, capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            rep.add("migration-replay", False, f"{sql.name} 重放失敗: {proc.stderr.strip()[-400:]}")
            return False
    rep.add("migration-replay", True, f"{len(migrations)} 個 migration 於空庫重放成功")
    return True


def http(base: str, params: dict):
    method = (params.get("method") or "GET").upper()
    url = base + params.get("path", "/")
    data = None
    headers = {}
    if "json" in params:
        data = json.dumps(params["json"]).encode()
        headers["Content-Type"] = "application/json"
    elif "body" in params:
        data = str(params["body"]).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def wait_health(base: str, health: dict, timeout_s: int = 90):
    deadline = time.time() + timeout_s
    path = health.get("path", "/healthz")
    want = health.get("expect_status", 200)
    while time.time() < deadline:
        try:
            status, body = http(base, {"path": path})
            if status == want:
                if health.get("expect_body_contains") and health["expect_body_contains"] not in body:
                    return False, f"health {path} 狀態碼符合但 body 缺 {health['expect_body_contains']!r}"
                return True, f"health {path} -> {status}"
        except Exception:
            pass
        time.sleep(2)
    return False, f"health {path} 在 {timeout_s}s 內未回 {want}"


def run_smoke(rep: Report, repo: Path, acceptance: dict, port: int, persist_dir: str) -> None:
    base = f"http://127.0.0.1:{port}"
    dev = subprocess.Popen(
        ["npx", "--yes", "wrangler", "dev", "--local", "--port", str(port),
         "--persist-to", persist_dir],
        cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        ok, msg = wait_health(base, acceptance.get("health") or {})
        rep.add("smoke:health", ok, msg)
        if not ok:
            return
        for test in acceptance.get("smoke") or []:
            name = test.get("name", "unnamed")
            last_status, last_body = None, ""
            skipped_actions = []
            failed = None
            for step in test.get("steps") or []:
                action = step.get("action")
                if action == "http_request":
                    last_status, last_body = http(base, step.get("params") or {})
                elif action == "wait":
                    time.sleep(float((step.get("params") or {}).get("seconds", 1)))
                else:
                    skipped_actions.append(action)
            expect = test.get("expect") or {}
            reasons = []
            if "status" in expect and last_status != expect["status"]:
                failed = True
                reasons.append(f"status {last_status} ≠ {expect['status']}")
            if "body_contains" in expect and expect["body_contains"] not in last_body:
                failed = True
                reasons.append(f"body 缺 {expect['body_contains']!r}")
            if skipped_actions:
                reasons.append(f"跳過非 CI action: {', '.join(skipped_actions)}（裁判層 full suite 執行）")
            rep.add(f"smoke:{name}", not failed, reasons or None)
    finally:
        dev.terminate()
        try:
            dev.wait(timeout=15)
        except subprocess.TimeoutExpired:
            dev.kill()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--skip-smoke", action="store_true")
    args = ap.parse_args()

    rep = Report("migration 重放＋smoke")
    acc_path = args.repo / ".smallgreen" / "acceptance.yaml"
    if not acc_path.exists():
        rep.add("smoke", False, ".smallgreen/acceptance.yaml 不存在")
        return rep.finish()
    acceptance = load_yaml(acc_path)

    persist_dir = tempfile.mkdtemp(prefix="sg-conformance-d1-")  # 乾淨空庫，不吃 repo 既有 state
    try:
        migrations_ok = run_migrations(rep, args.repo, persist_dir)
        if args.skip_smoke:
            rep.add("smoke", True, "依參數跳過", skipped=True)
        elif migrations_ok:
            run_smoke(rep, args.repo, acceptance, args.port, persist_dir)
    finally:
        shutil.rmtree(persist_dir, ignore_errors=True)
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
