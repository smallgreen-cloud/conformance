"""Preserve Wrangler, pipeline and secret boundaries while adding Sites."""
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
sys.path.insert(0, str(ROOT / "scripts"))
from check_profile import (Report, check_small_app, check_no_daemon_files,
                           check_pipeline, check_license_via_api, declared_profile,
                           resource_hits)
from check_secrets_manifest import declared_names, referenced_names


class LegacyBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)

    def write(self, path, value):
        p = self.repo / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(value)

    def test_missing_malformed_and_mixed_worker_configs(self):
        for files in [{}, {"wrangler.json": "{"}, {"wrangler.json": "{}", "sub/wrangler.toml": "[bad"}]:
            with self.subTest(files=list(files)):
                for name, value in files.items():
                    self.write(name, value)
                report = Report("legacy")
                check_small_app(report, self.repo, {})
                self.assertEqual([c["result"] for c in report.checks], ["fail", "fail"])

    def test_resource_allowlist_and_sqlite_only_durable_objects(self):
        allow = {"allowed": {"db": {"wrangler_keys": ["d1_databases[].binding"]}, "do": {"wrangler_keys": ["durable_objects"]}}, "excluded": {"hyperdrive": {"reason": "external database"}}}
        self.assertEqual(resource_hits({"d1_databases": []}, allow), [])
        for cfg in [{"hyperdrive": []}, {"unsafe": {}}, {"durable_objects": {}}, {"durable_objects": {}, "migrations": [{"new_classes": ["Paid"]}]}, {"durable_objects": {}, "migrations": [{"tag": "v1"}]}]:
            with self.subTest(cfg=cfg):
                self.assertTrue(resource_hits(cfg, allow))
        self.assertEqual(resource_hits({"durable_objects": {}, "migrations": [{"new_sqlite_classes": ["Free"]}]}, allow), [])

    def test_alt_deployment_disclosure_preserved(self):
        self.write("Dockerfile", "FROM scratch")
        for profile, expected in [("[", "fail"), ("alt_deployment: []", "fail"), ("alt_deployment: [docker]", "pass")]:
            self.write(".smallgreen/profile.yaml", profile)
            rep = Report("daemon")
            check_no_daemon_files(rep, self.repo)
            self.assertEqual(rep.checks[0]["result"], expected)
        self.write(".smallgreen/profile.yaml", "[")
        self.assertEqual(declared_profile(self.repo), "small-app")

    def test_pipeline_trigger_interval_and_estimate(self):
        self.write(".smallgreen/profile.yaml", "profile: pipeline\npipeline:\n  estimated_minutes_per_run: 2\n")
        for trigger, expected in [("workflow_dispatch", True), ("[workflow_dispatch]", True), ("\n  schedule:\n  - cron: '*/5 * * * *'", True), ("\n  schedule:\n  - cron: '*/2 * * * *'", False), ("\n  schedule:\n  - cron: '* * * * *'", False)]:
            self.write(".github/workflows/job.yml", "on: " + trigger)
            rep = Report("pipeline")
            check_pipeline(rep, self.repo)
            self.assertEqual(rep.checks[0]["result"], "pass")
            self.assertEqual(rep.checks[1]["result"], "pass" if expected else "fail")
            self.assertEqual(rep.checks[2]["result"], "pass")
        self.write(".github/workflows/job.yml", "[")
        self.write(".smallgreen/profile.yaml", "[")
        rep = Report("invalid pipeline")
        check_pipeline(rep, self.repo)
        self.assertEqual(rep.checks[0]["result"], "fail")
        self.assertEqual(rep.checks[2]["result"], "fail")

    def test_license_api_success_absence_and_failure(self):
        # Synthetic credential only; network mocked and never contacted.
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "fixture/repo", "GH_TOKEN": "fixture-only"}):
            for lic, expected in [("MIT", "pass"), ("NOASSERTION", "fail"), (None, "fail")]:
                response = io.BytesIO(json.dumps({"license": {"spdx_id": lic}}).encode())
                with patch("urllib.request.urlopen", return_value=response):
                    rep = Report("license")
                    check_license_via_api(rep, "SAP-6")
                    self.assertEqual(rep.checks[0]["result"], expected)
            with patch("urllib.request.urlopen", side_effect=OSError("fixture offline")):
                rep = Report("offline")
                check_license_via_api(rep, "SAP-6")
                self.assertEqual(rep.checks[0]["result"], "fail")

    def test_legacy_binding_sources_and_undeclared_name(self):
        cfg = {"vars": {"PUBLIC_SETTING": "fixture"}, "d1_databases": [{"binding": "DB"}], "kv_namespaces": [{"binding": "KV"}], "r2_buckets": [{"binding": "BUCKET"}], "services": [{"binding": "SERVICE"}], "analytics_engine_datasets": [{"binding": "ANALYTICS"}], "ai": {"binding": "AI"}, "assets": {"binding": "ASSETS"}, "browser": {"binding": "BROWSER"}, "send_email": [{"name": "EMAIL"}], "durable_objects": {"bindings": [{"name": "DO"}]}, "queues": {"producers": [{"binding": "QUEUE"}]}}
        self.write("wrangler.json", json.dumps(cfg))
        self.write("bad/wrangler.json", "{")
        self.write(".smallgreen/profile.yaml", "secrets:\n- name: DECLARED_SECRET\n")
        names = declared_names(self.repo)
        self.assertEqual(names, {"PUBLIC_SETTING", "DB", "KV", "BUCKET", "SERVICE", "ANALYTICS", "AI", "ASSETS", "BROWSER", "EMAIL", "DO", "QUEUE", "DECLARED_SECRET"})
        self.assertNotIn("CONNECTORS", names)
        self.write("worker.js", "env.UNKNOWN; process.env.DECLARED_SECRET;")
        self.write("tests/test.js", "env.TEST_ONLY;")
        self.write("types.d.ts", "env.TYPES_ONLY;")
        self.assertEqual(set(referenced_names(self.repo)), {"UNKNOWN", "DECLARED_SECRET"})
        self.write(".smallgreen/profile.yaml", "[")
        self.assertNotIn("DECLARED_SECRET", declared_names(self.repo))


if __name__ == "__main__":
    unittest.main()
