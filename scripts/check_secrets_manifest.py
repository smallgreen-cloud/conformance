#!/usr/bin/env python3
"""CON-3：runtime env 名 ⊆ secrets manifest ∪ 所選託管模式的已驗證 bindings。

用法：check_secrets_manifest.py --repo <repo> [--spec <Sites 相容 Spec>]
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

from sg_common import Report, find_all_wrangler, load_yaml, parse_wrangler_file
from sg_sites import SitesError, has_sites_declaration, sites_binding_names

ENV_RE = re.compile(r"\benv\.([A-Z][A-Z0-9_]*)\b")
PROCESS_ENV_RE = re.compile(r"\bprocess\.env\.([A-Z][A-Z0-9_]*)\b")
CODE_GLOBS = ["*.js", "*.mjs", "*.ts", "*.jsx", "*.tsx"]
# CON-3 範圍＝runtime 程式碼：排除測試、build 工具腳本、生成的型別宣告檔
SKIP_DIRS = {"node_modules", ".git", ".wrangler", "dist", "build", ".conformance", ".spec",
             "tests", "test", "__tests__", "scripts"}
SKIP_SUFFIXES = (".d.ts",)
# 平台標準環境變數，非 secret 亦非 binding
BUILTIN_VARS = {"NODE_ENV", "CI", "CF_PAGES", "GITHUB_ACTIONS", "DEV", "PROD", "VITEST"}
# Build entrypoints only: an app/vite.config.ts remains runtime input to CON-3.
BUILD_CONFIG_NAMES = {f"vite.config.{ext}" for ext in ("js", "mjs", "cjs", "ts", "mts", "cts")}
# 2026-11-23 / PetMCP ed20ee8f: this exact Sites 1.1.7 starter bridge uses
# ctx.props.CONNECTORS in production and env.CONNECTORS only behind DEV. Do not
# globally whitelist CONNECTORS: a changed bridge must be reviewed and re-tested.
# Fixture + source provenance: tests/connector-preview-worker.txt, README Sites.
PREVIEW_BRIDGE_SHA256 = "a0a10229cdda6f5fdb32234e3539007412233bb4938a671866c9295a44a3bdb6"


def declared_names(repo: Path, spec: Path | None = None) -> set:
    sites_names = sites_binding_names(repo, spec)
    names = set(sites_names or ())
    for cfg_path in ([] if sites_names is not None else find_all_wrangler(repo)):
        wcfg = parse_wrangler_file(cfg_path)
        if not wcfg:
            continue
        names.update((wcfg.get("vars") or {}).keys())
        for key in ("d1_databases", "kv_namespaces", "r2_buckets", "services", "analytics_engine_datasets"):
            for item in wcfg.get(key) or []:
                if isinstance(item, dict) and item.get("binding"):
                    names.add(item["binding"])
        for key in ("ai", "assets", "browser"):
            item = wcfg.get(key)
            if isinstance(item, dict) and item.get("binding"):
                names.add(item["binding"])
        for item in wcfg.get("send_email") or []:
            if isinstance(item, dict) and item.get("name"):
                names.add(item["name"])
        for item in (wcfg.get("durable_objects") or {}).get("bindings") or []:
            if isinstance(item, dict) and item.get("name"):
                names.add(item["name"])
        for item in (wcfg.get("queues") or {}).get("producers") or []:
            if isinstance(item, dict) and item.get("binding"):
                names.add(item["binding"])
        # queues.consumers 無 binding 名（consumer 以 handler 接收，不經 env）
    prof = repo / ".smallgreen" / "profile.yaml"
    if prof.exists():
        try:
            for s in (load_yaml(prof) or {}).get("secrets") or []:
                if isinstance(s, dict) and s.get("name"):
                    names.add(s["name"])
        except Exception:
            pass
    return names


def referenced_names(repo: Path, *, sites=False) -> dict:
    refs = {}
    for glob in CODE_GLOBS:
        for f in repo.rglob(glob):
            rel = f.relative_to(repo)
            if any(part in SKIP_DIRS for part in rel.parts) or f.name.endswith(SKIP_SUFFIXES):
                continue
            if len(rel.parts) == 1 and f.name in BUILD_CONFIG_NAMES:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for regex in (ENV_RE, PROCESS_ENV_RE):
                for m in regex.finditer(text):
                    if (sites and m.group(1) == "CONNECTORS" and rel.as_posix() == "worker/index.ts"
                            and hashlib.sha256(f.read_bytes()).hexdigest() == PREVIEW_BRIDGE_SHA256):
                        continue
                    refs.setdefault(m.group(1), set()).add(str(f.relative_to(repo)))
    return refs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--spec", type=Path, help="Sites-only 必填：含 install 與 sites-hosting schema 的 Spec checkout")
    args = ap.parse_args()

    rep = Report("secrets manifest 一致性 (CON-3)")
    try:
        declared = declared_names(args.repo, args.spec)
    except SitesError as exc:
        rep.add("CON-3", False, str(exc))
        return rep.finish()
    refs = referenced_names(args.repo, sites=has_sites_declaration(args.repo))
    undeclared = {name: files for name, files in sorted(refs.items())
                  if name not in declared and name not in BUILTIN_VARS}
    if undeclared:
        rep.add("CON-3", False, [f"env.{name} 未宣告（{', '.join(sorted(files)[:3])}）" for name, files in undeclared.items()])
    else:
        rep.add("CON-3", True, f"引用 {len(refs)} 個名稱，全數已宣告" if refs else "程式碼無 env 引用")
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
