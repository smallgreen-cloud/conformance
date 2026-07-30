#!/usr/bin/env python3
"""Secrets manifest 一致性（CON-3）：程式碼引用的 env 名 ⊆ manifest ∪ wrangler vars ∪ bindings。

用法：check_secrets_manifest.py --repo <受檢 repo 路徑>
"""
import argparse
import re
import sys
from pathlib import Path

from sg_common import Report, find_all_wrangler, load_yaml, parse_wrangler_file

ENV_RE = re.compile(r"\benv\.([A-Z][A-Z0-9_]*)\b")
PROCESS_ENV_RE = re.compile(r"\bprocess\.env\.([A-Z][A-Z0-9_]*)\b")
CODE_GLOBS = ["*.js", "*.mjs", "*.ts", "*.jsx", "*.tsx"]
# CON-3 範圍＝runtime 程式碼：排除測試、build 工具腳本、生成的型別宣告檔
SKIP_DIRS = {"node_modules", ".git", ".wrangler", "dist", "build", ".conformance", ".spec",
             "tests", "test", "__tests__", "scripts"}
SKIP_SUFFIXES = (".d.ts",)
# 平台標準環境變數，非 secret 亦非 binding
BUILTIN_VARS = {"NODE_ENV", "CI", "CF_PAGES", "GITHUB_ACTIONS", "DEV", "PROD", "VITEST"}


def declared_names(repo: Path) -> set:
    names = set()
    for cfg_path in find_all_wrangler(repo):
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
        for item in wcfg.get("queues_consumers") or []:
            pass  # consumers 無 binding 名
    prof = repo / ".smallgreen" / "profile.yaml"
    if prof.exists():
        try:
            for s in (load_yaml(prof) or {}).get("secrets") or []:
                if isinstance(s, dict) and s.get("name"):
                    names.add(s["name"])
        except Exception:
            pass
    return names


def referenced_names(repo: Path) -> dict:
    refs = {}
    for glob in CODE_GLOBS:
        for f in repo.rglob(glob):
            if any(part in SKIP_DIRS for part in f.parts) or f.name.endswith(SKIP_SUFFIXES):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for regex in (ENV_RE, PROCESS_ENV_RE):
                for m in regex.finditer(text):
                    refs.setdefault(m.group(1), set()).add(str(f.relative_to(repo)))
    return refs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    args = ap.parse_args()

    rep = Report("secrets manifest 一致性 (CON-3)")
    declared = declared_names(args.repo)
    refs = referenced_names(args.repo)
    undeclared = {name: files for name, files in sorted(refs.items())
                  if name not in declared and name not in BUILTIN_VARS}
    if undeclared:
        rep.add("CON-3", False, [f"env.{name} 未宣告（{', '.join(sorted(files)[:3])}）" for name, files in undeclared.items()])
    else:
        rep.add("CON-3", True, f"引用 {len(refs)} 個名稱，全數已宣告" if refs else "程式碼無 env 引用")
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
