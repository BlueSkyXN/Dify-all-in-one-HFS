# Release Checklist

本清单记录 all-in-one wrapper 与 Dify runtime artifact 的分层证据。它不是生产发布授权；任何 Space、bucket、Settings、restart、数据恢复或清理操作都需要独立 owner gate。

## 0. 变更前

```bash
git status --short --branch
scripts/static-check.sh
python3 /Users/sky/Github/SKY-Prompt/hfs-dev/scripts/check_hfs_alignment.py .
git diff --check
```

记录：

```text
Wrapper commit:
Dify producer repository:
Dify immutable source commit:
Source kind/ref (commit or tag):
GitHub Release tag and archive name:
Candidate slot (edge or release):
Candidate Space:
State mount and backup baseline:
Owner approval for publish / promote / restart / restore:
```

不要把历史 `RUNNING`、旧 GHCR digest、旧 Space SHA 或静态检查当成当前 release 证据。

## 1. Producer artifact

producer 必须输出唯一命名的：

```text
dify-runtime-<40-char-commit>.tar.gz
```

archive 内必须有 schema v2 `runtime-lock.json`，覆盖 API、Web、Agent、Plugin Daemon 和 Sandbox，并让 API/Web/Agent 绑定同一个 fork commit、其余组件绑定 immutable image/source pin。记录 producer build、archive SHA-256、压缩与解包 size、lock SHA-256、component pins、Sandbox privilege-launcher compatibility 和 GitHub Release asset readback。

```text
Producer build:
Archive SHA-256:
Archive size:
Runtime lock SHA-256:
GitHub Release asset readback:
```

没有 archive/lock 内容、Sandbox startup 和 component compatibility 的真实 build/runtime 证据时，不能切换 consumer Space。

## 2. Slot publication

只允许 manual `Publish Dify runtime artifact` workflow，且需 `confirm_publish=PUBLISH` 与 environment approval。workflow 不使用 whole-repo force-push 或 credential-bearing Git URL。

严格 **manifest-last**：

1. 上传 `dify-runtime-<commit>.tar.gz` 和 `SHA256SUMS.txt`；
2. 从 bucket readback archive/checksum，确认 byte/hash；
3. 最后覆盖 `<slot>/manifest.json`；
4. readback manifest，确认其 artifact、commit、size、SHA-256、runtime lock hash 与 slot key；
5. 观察后才由 owner 批准清理未引用对象。

```text
Slot:
Artifact upload/readback:
Manifest upload/readback:
Manifest source kind/ref:
Manifest artifact_ref:
Rollback GitHub Release tag:
```

`edge` 可指向已验证 main commit；`release` 必须由显式 promote 选择 immutable tag。旧 slot object 删除不是本轮发布步骤。

## 3. Space Settings and deployment readback

本地 `.env` 是值账本；`.env.example` 只提供空值/无害默认值。Space 只登记键名：

```text
Secret: DIFY_ARTIFACT_BEARER_TOKEN
Variable: DIFY_ARTIFACT_MANIFEST_HF_URI
Variable: DIFY_ARTIFACT_EXPECTED_SOURCE_REF
Variable: DIFY_ARTIFACT_MAX_BYTES
```

Secret 只核验 key presence，不能回读值。其余 Dify keys 见 `hfs-dev.toml`。确认 manifest 下载面没有挂载为 `/data`，现有 `/persist` state mount 未改名、未覆盖生成配置或业务数据。

部署后先回读：

```text
Expected wrapper commit:
Space repo SHA:
Space runtime.stage:
Space runtime.raw.sha:
Selected manifest/slot:
/_ops/version artifact provenance:
```

只有 `runtime.stage=RUNNING` 且 `runtime.raw.sha` 等于预期 wrapper commit，才可认为新 consumer image 接管；它不自动证明 artifact 或应用功能已正确。

## 4. Candidate and production runtime checks

在隔离 candidate state mount 完成，再由 owner 批准生产窗口：

```bash
OPS_TOKEN=<configured-token> scripts/hf-space-smoke.sh https://<space>.hf.space
```

另行记录：

```text
Manifest missing / malformed negative startup:
Wrong archive hash / runtime lock negative startup:
PostgreSQL migration:
Redis and Celery:
Dify login / application API:
File storage:
Plugin tool:
Sandbox execution:
Restart persistence:
PostgreSQL dump and isolated restore:
```

`PERSIST_MODE=bucket` 的 release profile 应设 `POSTGRES_BUCKET_FAILURE_MODE=exit`。仅运行 legacy demo fallback 或通过 syntax check，不能作为 state restore 证据。

## 5. Rollback and cleanup

回退选择已验证 GitHub Release 的 exact archive，重新执行 artifact-first/readback/manifest-last，然后确认 consumer Space readback 和 smoke。只回退 payload pointer；绝不自动回滚或删除 `/data`、`/persist`、PostgreSQL、Redis、插件或 generated secrets。

Settings prune、bucket/Space/object 删除、mount 重命名、factory reboot 和恢复生产数据均需要单独 owner/data-owner/release-owner 确认。