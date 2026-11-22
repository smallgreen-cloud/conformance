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
| Profile 靜態判定 | SAP-1/2/4/6、PIP-1/3/8 | Sites 安裝契約／manifest 與受管資源邊界，或既有 Wrangler／免費層路徑；常駐程序檔、pipeline、license |
| Secrets manifest 一致性 | CON-3 | runtime env 引用 ⊆ secrets manifest ∪ 所選託管模式的 vars／bindings |
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

## Sites-only

提供含 `schemas/install.schema.json` 與 `schemas/sites-hosting.schema.json` 的鎖定 Spec checkout，再執行：

```bash
python scripts/check_profile.py --spec <鎖定Spec路徑> --repo <Sites原始碼>
python scripts/check_secrets_manifest.py --spec <鎖定Spec路徑> --repo <Sites原始碼>
```

`install.yaml` 或 `.openai/hosting.json` 任一出現即選 Sites 分支；缺另一份、舊 Spec、錯 target、未知 manifest 欄位、資源不符、外部基礎設施、任何深度的來源 Wrangler 或 alt_deployment 都 fail，不能回退成自架。公開模板可省略 project_id。原生編譯器的 dist/server/wrangler.json 不作為來源宣告。既有沒有 Sites 宣告的 Wrangler 路徑維持原規則。

CON-3 只加入已驗證的 d1/r2 名稱。根目錄 Vite config 是 build entrypoint；應用程式內同名檔仍掃描。CONNECTORS 不是全域白名單：只有 `worker/index.ts` 與已核對 Sites 1.1.7 starter 的完整 SHA-256 相符才排除該名稱。`tests/connector-preview-worker.txt` 來自 MIT PetMCP runtime `ed20ee8fbda440a7f1b44007528394b726ae4f62` 的原生 starter bridge，保留其 DEV guard 與 request-scoped ctx.props 語意；變更後必須重新審查，不能只更新指紋躲過失敗。仍沿用 literal env.NAME／process.env.NAME 靜態掃描範圍，動態名稱／別名需人工審查。

這些檢查不會建立 Site、Cloudflare 資源或執行部署。Sites 無獨立 Wrangler，不能使用本 repo 的 `smoke_and_migrations.py` 來假裝線上驗收；Sites 的 migrations、登入、MCP、手機、Voice、第二帳號及 teardown 仍由原生平台個別驗收。此版本提供的是靜態支援，reusable workflow 的完整 smoke／build runtime 自動選擇尚未宣稱支援 Sites；接入時逐支執行上述檢查並保留自己的 Sites build／實測流程。

自測（含原有 Wrangler 與新 Sites 的正負案例）：

```bash
SMALLGREEN_TEST_SPEC=<相容Spec路徑> python -m coverage run --branch --source=scripts -m unittest discover -s tests -p 'test_*.py'
python -m coverage report --include='*/sg_sites.py,*/check_profile.py,*/check_secrets_manifest.py' --fail-under=80
```
