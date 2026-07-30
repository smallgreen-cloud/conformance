# SmallGreen Conformance

> [SmallGreen Spec](https://github.com/smallgreen-cloud/spec) 的可執行載體：reusable GitHub Actions workflow＋檢查腳本。spec 各文件 test_matrix 中落點標「conformance CI」的列，由本 repo 實現。

**Status: v0.1 — 對應 spec v0.1.0**

## 用法（受檢 repo 一段 YAML 接入）

```yaml
# .github/workflows/conformance.yml
name: conformance
on:
  push:
    branches: [main]
  pull_request:
jobs:
  conformance:
    uses: smallgreen-cloud/conformance/.github/workflows/conformance.yml@main
    with:
      spec_ref: v0.1.0    # 依哪版標準受檢（服務卡 spec_version 以此為準）
      run_smoke: true     # wrangler dev 本地 smoke
```

## 五支檢查與 requirement 對應

| 檢查 | Requirements | 說明 |
|---|---|---|
| Secrets 掃描（gitleaks） | CON-7／SAP-3／PIP-4 | 在 checkout 輔助 repo 前執行，repo 零真實 secret |
| 契約 schema | CON-1/2/4/5/6 | `.smallgreen/` 三檔對 spec JSON Schema 驗證＋UPSTREAM.md 一致性 |
| Profile 靜態判定 | SAP-1/2/4/6、PIP-1/3/8 | wrangler 解析、免費層允許清單、常駐程序檔、pipeline 觸發器、license（CI 內經 GitHub API） |
| Secrets manifest 一致性 | CON-3 | 程式碼 env 引用 ⊆ manifest ∪ wrangler vars ∪ bindings |
| Migration 重放＋smoke | acceptance 落點 | migrations/*.sql 乾淨空庫重放；wrangler dev 打 health＋smoke（http_request） |

不在本 repo 的檢查（分工邊界）：SAP-5/PIP-7 行為分析器動態層、SAP-7 agent 矩陣、teardown 資源歸零——屬部署期，由裁判層 MCP／驗證 harness 執行（見 spec `judge/`）。

## 自測

`fixtures/pass`（必須全綠）與 `fixtures/fail`（必須被拒）truth-table 對跑，見 [.github/workflows/ci.yml](.github/workflows/ci.yml)。改腳本壞掉任一預期即紅燈。本機執行：

```bash
pip install jsonschema pyyaml
python scripts/check_contract.py --spec <spec路徑> --repo <受檢repo>
python scripts/check_profile.py --spec <spec路徑> --repo <受檢repo>
python scripts/check_secrets_manifest.py --repo <受檢repo>
python scripts/smoke_and_migrations.py --repo <受檢repo>   # 需 node + npx wrangler
```

License：Apache-2.0（見 spec repo [LICENSE.md](https://github.com/smallgreen-cloud/spec/blob/main/LICENSE.md) 同一政策）。
