# HFS v2.1 对齐

`dify-all-in-one` 是 Hugging Face Docker Space 的 **Pattern A / port** 仓库：仓库根仍是 Space root，`docker/` 保留 all-in-one runtime glue；它不是把 Dify 产品源码迁入 `cloud/hfs/` 的 Pattern B 项目。

## 交付结论

```text
HFS standard: 2.1
Project class: preview
Canonical target role: primary
Pattern: A / HFS Port Repository
Lane: artifact
Runtime mode: manifest-first artifact-at-runtime
Space root: repo root
Product source: BlueSkyXN/dify producer repository
Wrapper source: this repository
```

`hfs-dev.toml` 是最小语义登记表，只记录 Space、车道、键名、下载面和例外。它不重复 Dify component pins、checksums 或运行时不变量；这些由 artifact 的 `runtime-lock.json`、slot manifest、bootstrap 和 producer release 共同证明。

Preview 日常变更可以直接更新 canonical Space；candidate 只保留为高风险变更的可选隔离验证。
Secret 仍必须以本地明文文件为先：canonical 使用 `.env`，candidate 使用
`local/hfs-targets/candidate.env`，两者都必须保持 Git ignored，不能从 HF Secret 反向当作
唯一事实源。

## Artifact 边界

Space image 只包含 Debian/Python、PostgreSQL、Redis、Nginx、Supervisor、ops/admin、Dify wrappers、健康检查和固定 Sandbox privilege launcher。它不包含 Dify API/Web/Agent/Plugin/Sandbox 产品 payload、上游源码、`.env*`、`local/`、生成数据或凭据。

启动时 `docker/dify-artifact-bootstrap`：

1. 只接受 `DIFY_ARTIFACT_MANIFEST_HF_URI` 指向的 `hf://buckets/<namespace>/hfs-dist/dify-all-in-one/<edge|release>/manifest.json`。
2. 下载一次 manifest，并要求 `DIFY_ARTIFACT_BEARER_TOKEN`；没有 manifest、token 或合法 URI 时退出。
3. 只下载 manifest 中声明的 `dify-runtime-<40-char-sha>.tar.gz`，校验 schema v2、压缩与解包大小、SHA-256、`runtime-lock.json` hash、component 不可变 pins 和 archive 路径。
4. 仅在完整验证后以原子 runtime pointer 切换到 `/opt/dify/runtime`；不会扫描目录、使用直接 URL/PATH/S3、回退旧 image assembly，也不会把产品 payload 写入 `/data`。
5. 恢复原有 `/app`、`/opt/dify/plugin-daemon`、`/conf`、`/dependencies` 的路径语义后，才继续 PostgreSQL、Redis、Dify migration 和 Supervisor 启动。

`runtime-lock.json` 必须覆盖 API、Web、Agent、Plugin Daemon 与 Sandbox；API/Web/Agent 必须绑定同一 immutable fork commit。Sandbox server 是 artifact 内容，但 root-owned setuid launcher 在 wrapper image 构建期固定提供，避免把 bootstrap 提权或把容器改为 root runtime。

## 发布与回退

下载面固定为：

```text
hfs-dist/dify-all-in-one/
  edge/manifest.json
  edge/dify-runtime-<commit>.tar.gz
  release/manifest.json
  release/dify-runtime-<commit>.tar.gz
```

发布顺序严格为 artifact 与 `SHA256SUMS.txt` 上传并 readback，最后才覆盖 manifest 并 readback。`edge` 对应已验证 main commit；`release` 只由显式、owner 批准的 promote 选择 immutable Git tag。历史 artifact 和 manifest 由 `BlueSkyXN/dify` 的 GitHub Release 保存；slot 中旧对象的清理不属于发布动作。

本仓的 `Publish Dify runtime artifact` workflow 只可 `workflow_dispatch`，并要求 `confirm_publish=PUBLISH` 与 environment approval。它从 fork 的指定 Release 下载精确 archive，发布时不使用 credential-bearing Git URL、不 force-push Space、不重启实例；完成后输出 archive/manifest readback 证据。回退是选择已验证 GitHub Release 的 exact archive 并再次走 artifact-first / manifest-last，不回滚 `/data`。

## 配置和状态边界

- `.env` 是 ignored 的本地值账本，`.env.example` 只含空值或无害默认值；`HF_TOKEN` / `GH_TOKEN` 只属于本地控制面。
- `DIFY_ARTIFACT_BEARER_TOKEN` 是 Space Secret；manifest URI、expected source ref、最大 archive 大小是 Space Variables。其余 Dify Secret/Variable 键名见 `hfs-dev.toml`，不记录值。
- `/data`、`/persist`、PostgreSQL、Redis、Dify files、plugin state、generated env 和备份路径保持现有 runtime 责任；artifact 下载面绝不作为 mount 或状态目录。
- 生产 Space 建议 `PERSIST_MODE=bucket` 且 `POSTGRES_BUCKET_FAILURE_MODE=exit`，避免 bucket PGDATA 失败后隐式以 runtime PostgreSQL 成功。现有 `fallback-to-runtime` 仅保留作已知 demo compatibility 行为，不能作为 artifact release 的持久化证据。

## 本地门禁和证据范围

```bash
scripts/static-check.sh
python3 /Users/sky/Github/SKY-Prompt/hfs-dev/scripts/check_hfs_alignment.py .
git diff --check
```

静态门禁验证 registry、ignore boundary、manifest-first bootstrap、archive self-test、shell/Python 语法和既有纯函数测试。它不证明 Docker build、fork artifact producer、HF Bucket readback、Space runtime 接管、Sandbox execution、数据库迁移或 `/data` 恢复。

artifact producer、candidate Space 与生产切换仍需 owner gate：确认 fork Release 的 runtime lock、下载权限、candidate state mount、PostgreSQL RPO/隔离 restore、Plugin/Sandbox 真正启动以及最终 Space `runtime.raw.sha` readback。
