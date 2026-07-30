"""SmallGreen conformance 共用工具：wrangler 設定載入（jsonc/toml/json）、YAML 載入、回報格式。"""
import json
import sys
from pathlib import Path

import yaml

WRANGLER_NAMES = ["wrangler.jsonc", "wrangler.toml", "wrangler.json"]


def strip_jsonc(text: str) -> str:
    """字串感知地移除 // 與 /* */ 註解，再移除尾逗號。不改動字串常值內容。"""
    out = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1

    cleaned = "".join(out)
    # 尾逗號（字串感知第二遍）
    out2 = []
    in_string = False
    i, n = 0, len(cleaned)
    while i < n:
        ch = cleaned[i]
        if in_string:
            out2.append(ch)
            if ch == "\\" and i + 1 < n:
                out2.append(cleaned[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out2.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and cleaned[j] in " \t\r\n":
                j += 1
            if j < n and cleaned[j] in "}]":
                i += 1  # 丟棄尾逗號
                continue
        out2.append(ch)
        i += 1
    return "".join(out2)


def find_wrangler(repo: Path):
    for name in WRANGLER_NAMES:
        p = repo / name
        if p.exists():
            return p
    return None


def find_all_wrangler(repo: Path, max_depth: int = 3):
    """回傳 repo 內所有 wrangler 設定檔路徑（多 worker monorepo 支援），排除依賴目錄。"""
    skip = {"node_modules", ".git", ".wrangler", "dist", "build", ".output", ".vercel"}
    found = []
    for name in WRANGLER_NAMES:
        for p in repo.rglob(name):
            rel = p.relative_to(repo)
            if len(rel.parts) > max_depth or any(part in skip for part in rel.parts):
                continue
            found.append(p)
    return sorted(found)


def parse_wrangler_file(p: Path):
    try:
        if p.suffix == ".toml":
            import tomllib

            return tomllib.loads(p.read_text(encoding="utf-8"))
        return json.loads(strip_jsonc(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def load_wrangler(repo: Path):
    """回傳 (path, dict)；找不到或解析失敗回 (path_or_None, None)。"""
    p = find_wrangler(repo)
    if p is None:
        return None, None
    try:
        if p.suffix == ".toml":
            import tomllib

            return p, tomllib.loads(p.read_text(encoding="utf-8"))
        return p, json.loads(strip_jsonc(p.read_text(encoding="utf-8")))
    except Exception:
        return p, None


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class Report:
    """逐條 check 收集器，輸出與 Profile 判定輸出格式一致。"""

    def __init__(self, title: str):
        self.title = title
        self.checks = []

    def add(self, check_id: str, ok: bool, reasons=None, skipped=False):
        result = "skipped" if skipped else ("pass" if ok else "fail")
        entry = {"id": check_id, "result": result}
        if reasons:
            entry["reasons"] = reasons if isinstance(reasons, list) else [str(reasons)]
        self.checks.append(entry)

    def finish(self) -> int:
        failed = [c for c in self.checks if c["result"] == "fail"]
        print(f"== {self.title} ==")
        for c in self.checks:
            mark = {"pass": "✓", "fail": "✗", "skipped": "-"}[c["result"]]
            line = f" {mark} {c['id']}"
            for r in c.get("reasons", []):
                line += f"\n     · {r}"
            print(line)
        print(json.dumps({"title": self.title, "result": "fail" if failed else "pass", "checks": self.checks}, ensure_ascii=False))
        return 1 if failed else 0


def die(msg: str) -> "sys.NoReturn":
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)
