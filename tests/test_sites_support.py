"""Sites declaration truth table; no account, deployment or real secrets involved."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = Path(os.environ.get("SMALLGREEN_TEST_SPEC", ROOT.parent / "spec-sites-20261123"))
sys.path.insert(0, str(ROOT / "scripts"))
import check_profile
import check_secrets_manifest


class SitesSupportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.install = yaml.safe_load((SPEC / "schemas/examples/install.valid.yaml").read_text())
        self.install["interaction"]["generated_secrets"] = []
        self.install["interaction"]["user_inputs"] = []
        self.manifest = {"d1": "DB", "r2": "BUCKET", "capabilities": ["mcp"]}
        self.profile = {"profile": "small-app", "secrets": [], "alt_deployment": []}
        self.save()
        self.write("worker/index.ts", "export const read = env.DB; export const photo = env.BUCKET;")

    def write(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def save(self):
        self.write(".smallgreen/install.yaml", yaml.safe_dump(self.install))
        self.write(".smallgreen/profile.yaml", yaml.safe_dump(self.profile))
        self.write(".openai/hosting.json", json.dumps(self.manifest))

    def run_check(self, module, *, with_spec=True):
        argv = [module.__file__, "--repo", str(self.repo)]
        if with_spec:
            argv += ["--spec", str(SPEC)]
        output = io.StringIO()
        with patch.object(sys, "argv", argv), patch.dict(os.environ, {"GITHUB_REPOSITORY": "", "GH_TOKEN": "", "GITHUB_TOKEN": ""}), contextlib.redirect_stdout(output):
            code = module.main()
        report = json.loads(output.getvalue().splitlines()[-1])
        return code, {entry["id"]: entry["result"] for entry in report["checks"]}

    def assert_profile(self, ok):
        code, checks = self.run_check(check_profile)
        self.assertEqual(code, 0 if ok else 1)
        self.assertEqual(checks["SAP-2"], "pass" if ok else "fail")
        if ok:
            self.assertEqual(checks["SAP-1"], "pass")

    def assert_secrets(self, ok):
        code, checks = self.run_check(check_secrets_manifest)
        self.assertEqual(code, 0 if ok else 1)
        self.assertEqual(checks["CON-3"], "pass" if ok else "fail")

    def test_native_bindings_without_wrangler(self):
        self.assert_profile(True)
        self.assert_secrets(True)

    def test_static_site_and_nullable_unused_bindings(self):
        self.manifest = {"static": {"directory": "dist"}, "d1": None, "r2": None}
        self.install["hosting"]["managed_resources"] = ["site"]
        self.save()
        self.write("worker/index.ts", "export const app = {};")
        self.assert_profile(True)
        self.assert_secrets(True)

    def test_custom_binding_names_and_private_project_id(self):
        self.manifest = {"project_id": "fixture-project", "d1": "PET_DATA", "r2": "PHOTOS"}
        self.save()
        self.write("worker/index.ts", "export const app = [env.PET_DATA, env.PHOTOS];")
        self.assert_profile(True)
        self.assert_secrets(True)

    def test_native_connector_declarations_are_not_infrastructure(self):
        self.manifest = {**self.manifest, "plugins": [{"id": "fixture-plugin", "connector_ids": ["fixture-connector"]}], "connectors": [{"id": "fixture-connector", "action_selection_mode": "read_only"}]}
        self.save()
        self.assert_profile(True)

    def test_missing_or_malformed_declarations_fail_closed(self):
        for filename, value in [(".openai/hosting.json", "{"), (".openai/hosting.json", "[]"), (".smallgreen/install.yaml", "["), (".smallgreen/install.yaml", "null")]:
            with self.subTest(filename=filename, value=value):
                self.save()
                self.write(filename, value)
                self.assert_profile(False)
                self.assert_secrets(False)
        for filename in [".openai/hosting.json", ".smallgreen/install.yaml"]:
            with self.subTest(missing=filename):
                self.save()
                (self.repo / filename).unlink()
                self.assert_profile(False)
                self.assert_secrets(False)

    def test_wrong_target_external_infrastructure_and_invalid_contract(self):
        original = copy.deepcopy(self.install)
        for key, value in [("target", {"client": "chatgpt-work", "hosting": "cloudflare", "execution_mode": "native-sites"}), ("hosting", {"manifest": ".openai/hosting.json", "managed_resources": ["site", "d1", "r2"], "external_infrastructure": ["BYOC"]}), ("source", {"repository": "example/app", "commit": "main", "license": "MIT"})]:
            with self.subTest(key=key):
                self.install = {**original, key: value}
                self.save()
                self.assert_profile(False)
                self.assert_secrets(False)

    def test_manifest_rejects_unknown_resources_and_bad_bindings(self):
        for manifest in [{"kv": "CACHE"}, {"queues": []}, {"d1": {"binding": "DB"}}, {"d1": ""}, {"d1": "DB", "r2": "DB"}, {"capabilities": ["unknown"]}, {"static": {"directory": "../../private"}}, {"r2": "BUCKET", "services": []}]:
            with self.subTest(manifest=manifest):
                self.manifest = manifest
                self.save()
                self.assert_profile(False)
                self.assert_secrets(False)

    def test_resource_inventory_must_match_manifest_exactly(self):
        for resources in [["site"], ["d1", "r2"], ["site", "d1", "r2", "kv"]]:
            with self.subTest(resources=resources):
                self.install["hosting"]["managed_resources"] = resources
                self.save()
                self.assert_profile(False)
                self.assert_secrets(False)

    def test_source_wrangler_at_any_depth_is_rejected(self):
        for path in ["wrangler.toml", "packages/api/wrangler.json", "a/b/c/d/wrangler.jsonc"]:
            with self.subTest(path=path):
                self.write(path, "{}")
                self.assert_profile(False)
                self.assert_secrets(False)
                (self.repo / path).unlink()

    def test_generated_deployment_metadata_is_not_independent_infrastructure(self):
        self.write("dist/server/wrangler.json", '{"d1_databases":[]}')
        self.write("node_modules/example/wrangler.json", "{}")
        self.assert_profile(True)
        self.assert_secrets(True)

    def test_ci_checker_checkouts_are_not_application_source(self):
        self.write(".conformance/fixtures/pass/wrangler.json", "{}")
        self.write(".spec/examples/wrangler.json", "{}")
        self.assert_profile(True)
        self.assert_secrets(True)
        self.write("app/.conformance/wrangler.json", "{}")
        self.assert_profile(False)

    def test_alternative_hosting_is_not_sites_only(self):
        self.profile["alt_deployment"] = ["docker"]
        self.save()
        self.assert_profile(False)
        self.assert_secrets(False)

    def test_build_config_exclusion_does_not_hide_runtime_secret(self):
        self.write("vite.config.ts", "export default process.env.CODEX_SANDBOX;")
        self.assert_secrets(True)
        self.write("app/page.ts", "export const x = process.env.CODEX_SANDBOX;")
        self.assert_secrets(False)
        self.write("app/page.ts", "export const x = env.UNDECLARED_SECRET;")
        self.assert_secrets(False)
        self.profile["secrets"] = [{"name": "UNDECLARED_SECRET"}]
        self.save()
        self.assert_secrets(True)

    def test_nested_build_filename_is_still_runtime(self):
        self.write("app/vite.config.ts", "export const x = env.NOT_DECLARED;")
        self.assert_secrets(False)

    def test_connector_preview_exception_is_narrow(self):
        starter = ROOT / "tests/connector-preview-worker.txt"
        self.write("worker/index.ts", starter.read_text())
        self.assert_secrets(True)
        self.write("app/page.ts", "export const connector = env.CONNECTORS;")
        self.assert_secrets(False)
        self.write("app/page.ts", "")
        self.write("worker/index.ts", starter.read_text().replace("import.meta.env.DEV && ", ""))
        self.assert_secrets(False)

    def test_sites_requires_an_explicit_compatible_spec(self):
        code, checks = self.run_check(check_secrets_manifest, with_spec=False)
        self.assertEqual((code, checks["CON-3"]), (1, "fail"))

    def test_old_spec_and_invalid_schema_are_explicit_failures(self):
        old_spec = self.repo / "old-spec"
        schemas = old_spec / "schemas"
        schemas.mkdir(parents=True)
        (schemas / "install.schema.json").write_text((SPEC / "schemas/install.schema.json").read_text())
        with patch(__name__ + ".SPEC", old_spec):
            self.assert_profile(False)
            self.assert_secrets(False)
            (schemas / "sites-hosting.schema.json").write_text('{"type":"not-a-type"}')
            self.assert_profile(False)
            self.assert_secrets(False)

    def test_malformed_profile_is_not_silently_ignored_for_sites(self):
        for text in ["null", "["]:
            with self.subTest(text=text):
                self.write(".smallgreen/profile.yaml", text)
                self.assert_profile(False)
                self.assert_secrets(False)


class LegacyRegressionTest(unittest.TestCase):
    def test_existing_wrangler_fixture_truth_table(self):
        for name, ok in [("pass", True), ("pass-altdeploy", True), ("fail", False)]:
            with self.subTest(fixture=name):
                rep = check_profile.Report("legacy")
                check_profile.check_small_app(rep, ROOT / "fixtures" / name, yaml.safe_load((SPEC / "profiles/free-tier-allowlist.yaml").read_text()))
                self.assertEqual(all(x["result"] == "pass" for x in rep.checks), ok)
        names = check_secrets_manifest.declared_names(ROOT / "fixtures/pass")
        self.assertIn("DB", names)
        self.assertNotIn("CONNECTORS", names)


if __name__ == "__main__":
    unittest.main()
