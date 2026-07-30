#!/usr/bin/env python3
"""契約檔檢查（CON-1/2/4/5/6）：.smallgreen/ 三檔存在、通過 spec JSON Schema、UPSTREAM.md 一致性。

用法：check_contract.py --spec <spec repo 路徑> --repo <受檢 repo 路徑>
"""
import argparse
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from sg_common import Report, die, load_yaml

CONTRACTS = [
    ("profile", "profile.yaml", "schemas/profile.schema.json"),
    ("acceptance", "acceptance.yaml", "schemas/acceptance.schema.json"),
    ("maintenance", "maintenance.yaml", "schemas/maintenance.schema.json"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, type=Path)
    ap.add_argument("--repo", required=True, type=Path)
    args = ap.parse_args()
    if not args.spec.is_dir():
        die(f"spec 路徑不存在: {args.spec}")

    rep = Report("contract (CON-1/2/4/5/6)")
    contract_dir = args.repo / ".smallgreen"
    docs = {}

    for label, fname, schema_rel in CONTRACTS:
        fpath = contract_dir / fname
        if not fpath.exists():
            rep.add(f"CON-1:{label}", False, f".smallgreen/{fname} 不存在")
            continue
        try:
            doc = load_yaml(fpath)
        except Exception as exc:
            rep.add(f"CON-1:{label}", False, f"YAML 解析失敗: {exc}")
            continue
        import json

        schema = json.loads((args.spec / schema_rel).read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(doc))
        if errors:
            rep.add(f"CON-1:{label}", False, [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in errors[:5]])
        else:
            rep.add(f"CON-1:{label}", True)
            docs[label] = doc

    # CON-2 由 profile schema additionalProperties: false 涵蓋（上面 validate 即檢）
    # CON-4/5 由 acceptance / maintenance schema required 涵蓋

    # CON-6：適配 repo（profile.upstream 存在）必須有 UPSTREAM.md 且 commit 一致
    profile = docs.get("profile")
    if profile and profile.get("upstream"):
        upstream_md = args.repo / "UPSTREAM.md"
        commit = profile["upstream"].get("commit", "")
        if not upstream_md.exists():
            rep.add("CON-6", False, "profile.yaml 有 upstream 但 UPSTREAM.md 不存在")
        elif commit and commit not in upstream_md.read_text(encoding="utf-8"):
            rep.add("CON-6", False, f"UPSTREAM.md 未包含 profile.yaml 鎖定的 commit {commit[:12]}")
        else:
            rep.add("CON-6", True)
    else:
        rep.add("CON-6", True, skipped=True)

    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
