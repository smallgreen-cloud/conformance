#!/usr/bin/env python3
"""乾淨環境建置閘（CON-8）＋建置需求宣告完整性（CON-9）。

用法：check_build_gates.py --repo <受檢 repo 路徑> [--install-only]

CON-8：profile.yaml 的 build_requirements.gates 逐條執行，全數 exit 0。
       未宣告 gates → skip（不強制專案必須有驗證腳本）。
CON-9：CON-8 失敗時，若失敗訊息指向缺少的工具／依賴，該項須已列於 build_requirements
       （system_tools／runtime／notes）；未列即 fail（同構於 CON-3 的 env 對帳）。

前置：呼叫端負責 fresh clone 與標準安裝（CI job 做）；本腳本只跑 gates 並判定。
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

from sg_common import Report, load_yaml

# 失敗訊息 → 缺少項目的推斷規則（保守：只認高信心 pattern）
MISSING_PATTERNS = [
    (re.compile(r"command not found:?\s*(\S+)", re.I), "system_tools"),
    (re.compile(r"(\S+):\s*command not found", re.I), "system_tools"),
    (re.compile(r"Cannot find module '(node:[^']+)'", re.I), "runtime"),
    (re.compile(r"Cannot find (?:module|type definition file for) '([^']+)'", re.I), "dependency"),
    (re.compile(r"Could not resolve \"([^\"]+)\"", re.I), "dependency"),
    (re.compile(r"error TS2307[^\n]*'([^']+)'", re.I), "dependency"),
]
# 版本不符（非缺項）：宣告的 runtime 版本低於實際需求時，CON-9 一樣要判 fail——
# 「宣告了但宣告錯」與「沒宣告」對部署者是同一種傷害（實證：second-brain adapter 宣告
# node>=20，上游 wrangler 4.x 實需 node>=22，CI 才擋下）。
RUNTIME_VERSION_PATTERNS = [
    re.compile(r"requires at least (\S+?)\.?\s+v?(\d+)", re.I),
    re.compile(r"(\S+)\s+version\s+[\"']?>=?\s*v?(\d+)[^\n]*required", re.I),
]


def required_runtime_version(output: str):
    """從失敗訊息抽出「某 runtime 至少要 vN」；抽不到回 None。"""
    for pat in RUNTIME_VERSION_PATTERNS:
        m = pat.search(output)
        if m:
            return m.group(1).strip().rstrip(".").lower(), int(m.group(2))
    return None


def declared_major(runtime: str, name: str):
    """從 build_requirements.runtime（如 node>=20）取宣告的主版號；名稱不符或無版號回 None。"""
    m = re.match(r"\s*([A-Za-z.]+)\s*>?=?\s*v?(\d+)", runtime or "")
    if not m:
        return None
    decl_name = m.group(1).lower()
    if name not in decl_name and decl_name not in name:
        return None
    return int(m.group(2))
INSTALL_CMD = {"npm": ["npm", "ci"], "pnpm": ["pnpm", "install", "--frozen-lockfile"],
               "yarn": ["yarn", "install", "--immutable"], "bun": ["bun", "install", "--frozen-lockfile"]}


def infer_missing(output: str) -> list:
    """從失敗輸出推斷缺少的項目（保守推斷；找不到就回空）。"""
    found = []
    for pat, kind in MISSING_PATTERNS:
        for m in pat.finditer(output):
            item = m.group(1).strip()
            if item and (item, kind) not in found:
                found.append((item, kind))
    return found


def declared_terms(br: dict) -> str:
    """build_requirements 宣告過的所有字串（用於 CON-9 對帳的寬鬆比對）。"""
    parts = [str(br.get("runtime") or ""), str(br.get("package_manager") or ""),
             str(br.get("notes") or "")]
    parts += [str(t) for t in (br.get("system_tools") or [])]
    return " ".join(parts).lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, type=Path)
    ap.add_argument("--install-only", action="store_true", help="只跑標準安裝，不跑 gates")
    args = ap.parse_args()

    rep = Report("乾淨環境建置閘 (CON-8/CON-9)")
    prof_path = args.repo / ".smallgreen" / "profile.yaml"
    if not prof_path.exists():
        rep.add("CON-8", False, "找不到 .smallgreen/profile.yaml")
        return rep.finish()
    prof = load_yaml(prof_path) or {}
    br = prof.get("build_requirements") or {}
    gates = br.get("gates") or []

    # 標準安裝（依 package_manager；未宣告則跳過安裝，由呼叫端負責）
    pm = br.get("package_manager")
    if pm in INSTALL_CMD and (args.repo / "package.json").exists():
        if shutil.which(INSTALL_CMD[pm][0]) is None:
            rep.add("CON-9", False, f"宣告的 package_manager '{pm}' 不存在於環境")
            return rep.finish()
        r = subprocess.run(INSTALL_CMD[pm], cwd=args.repo, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            rep.add("CON-8", False, [f"標準安裝失敗（{' '.join(INSTALL_CMD[pm])}）",
                                     (r.stderr or r.stdout)[-500:]])
            return rep.finish()

    if args.install_only:
        rep.add("CON-8", True, "install-only 模式：標準安裝成功，gates 未執行", skipped=True)
        return rep.finish()

    if not gates:
        rep.add("CON-8", True, "profile.build_requirements.gates 未宣告——本條 skip（專案未宣稱任何驗證閘門）", skipped=True)
        rep.add("CON-9", True, "因 CON-8 skip 而不適用", skipped=True)
        return rep.finish()

    # CON-8：逐條執行 gates
    failed = None
    for cmd in gates:
        r = subprocess.run(cmd, cwd=args.repo, shell=True, capture_output=True, text=True, timeout=1800)
        if r.returncode != 0:
            failed = (cmd, (r.stdout or "") + (r.stderr or ""))
            break
    if failed is None:
        rep.add("CON-8", True, f"{len(gates)} 個閘門指令全數 exit 0")
        rep.add("CON-9", True, "無失敗，無須對帳")
        return rep.finish()

    cmd, output = failed
    rep.add("CON-8", False, [f"閘門失敗：{cmd}", output[-800:]])

    # CON-9：失敗項是否已宣告——先看 runtime 版本不符，再看缺工具／依賴
    need = required_runtime_version(output)
    if need:
        name, need_major = need
        decl = declared_major(str(br.get("runtime") or ""), name)
        if decl is None:
            rep.add("CON-9", False, [f"建置需要 {name} v{need_major}+，但 build_requirements.runtime "
                                     f"未宣告該 runtime（現值：{br.get('runtime') or '未填'}）"])
        elif decl < need_major:
            rep.add("CON-9", False, [f"build_requirements.runtime 宣告 {name}>={decl}，"
                                     f"實際需要 v{need_major}+——宣告錯與未宣告對部署者同害"])
        else:
            rep.add("CON-9", True, f"宣告 {name}>={decl} 已涵蓋需求 v{need_major}（環境未達宣告，非宣告缺漏）")
        rep.finish()
        return 1

    missing = infer_missing(output)
    if not missing:
        rep.add("CON-9", True, "失敗原因無法自動歸因為「缺工具／依賴」——不判定（人工審閱）", skipped=True)
    else:
        decl = declared_terms(br)
        undeclared = [f"{item}（{kind}）" for item, kind in missing
                      if item.lower() not in decl and item.lower().lstrip("node:").split("/")[0] not in decl]
        if undeclared:
            rep.add("CON-9", False, ["建置實際需要但 build_requirements 未宣告："] + undeclared)
        else:
            rep.add("CON-9", True, "失敗項皆已於 build_requirements 宣告（環境前置問題，非宣告缺漏）")
    rep.finish()
    return 1


if __name__ == "__main__":
    sys.exit(main())
