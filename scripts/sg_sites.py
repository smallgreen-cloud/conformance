"""Fail-closed static Sites declarations shared by SAP-1/2 and CON-3.

2026-11-23: legacy 82600612 requires Wrangler and rejects PetMCP's native
manifest (runtime ed20ee8f). Never repair that mismatch by adding BYOC resources.
Spec cafaf20 introduced the install contract; a compatible Spec must also carry
sites-hosting.schema.json. Static success is not live platform acceptance.
"""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from sg_common import find_all_wrangler, load_yaml


class SitesError(ValueError):
    """An invalid declaration must not fall back to a different hosting mode."""


def has_sites_declaration(repo: Path) -> bool:
    return any((repo / path).exists() for path in (".openai/hosting.json", ".smallgreen/install.yaml"))


def read_document(path: Path, *, json_format=False):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if json_format else load_yaml(path)
    except Exception as exc:
        # Do not print the parser's input excerpt: manifests must not leak secrets.
        raise SitesError(f"{path.name}: 無法讀取或解析 ({type(exc).__name__})") from exc


def validate_schema(document, spec: Path, name: str):
    path = spec / "schemas" / name
    if not path.is_file():
        raise SitesError(f"Spec 缺 schemas/{name}；請釘選含 Sites 支援的版本")
    schema = read_document(path, json_format=True)
    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema).iter_errors(document))
    except Exception as exc:
        raise SitesError(f"{name}: schema 無效 ({type(exc).__name__})") from exc
    if errors:
        # Report paths/rules, never values which might contain misplaced credentials.
        details = [f"{error.json_path} ({error.validator})" for error in errors[:5]]
        raise SitesError(f"{name}: " + "; ".join(details))


def load_sites(repo: Path, spec: Path | None):
    """Return validated source documents, or None for the unchanged Wrangler path."""
    if not has_sites_declaration(repo):
        return None
    if spec is None:
        raise SitesError("Sites 檢查需要 --spec 指定相容且鎖定的 Spec checkout")
    install = read_document(repo / ".smallgreen/install.yaml")
    manifest = read_document(repo / ".openai/hosting.json", json_format=True)
    validate_schema(install, spec, "install.schema.json")
    validate_schema(manifest, spec, "sites-hosting.schema.json")
    return install, manifest


def sites_boundary_errors(repo: Path, install: dict, manifest: dict) -> list[str]:
    errors = []
    resources = {"site"} | {kind for kind in ("d1", "r2") if manifest.get(kind)}
    if set(install["hosting"]["managed_resources"]) != resources:
        errors.append("install.hosting.managed_resources 必須與 Sites manifest 完全一致（含 site）")
    bindings = [manifest[kind] for kind in ("d1", "r2") if manifest.get(kind)]
    if len(set(bindings)) != len(bindings):
        errors.append("Sites d1/r2 binding 名稱不可重複")
    # Unlike the legacy monorepo search, Sites-only rejects source configs at ANY
    # depth. Generated dist/build and dependency metadata are not source configs.
    configs = find_all_wrangler(repo, max_depth=10000)
    if configs:
        errors.append("Sites-only 不得混入獨立 Wrangler 設定：" + ", ".join(str(p.relative_to(repo)) for p in configs))
    profile_path = repo / ".smallgreen/profile.yaml"
    profile = read_document(profile_path)
    if not isinstance(profile, dict):
        errors.append("profile.yaml 必須為 object")
    elif profile.get("alt_deployment"):
        errors.append("Sites-only 不得宣告 alt_deployment 替代託管")
    return errors


def sites_binding_names(repo: Path, spec: Path | None) -> set[str] | None:
    documents = load_sites(repo, spec)
    if documents is None:
        return None
    install, manifest = documents
    errors = sites_boundary_errors(repo, install, manifest)
    if errors:
        raise SitesError("; ".join(errors))
    return {manifest[kind] for kind in ("d1", "r2") if manifest.get(kind)}
