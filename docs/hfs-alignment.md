# HFS Paradigm Alignment

本文档说明 `dify-all-in-one` 如何对齐本机 `hfs-dev` HFS 开发范式。

它不是新的部署说明，也不是把本仓库改造成另一个模板；它只记录当前仓库在范式中的分类、目录主权、runtime 获取模式、已满足的契约和仍需注意的发布态 gap。

## 结论

`dify-all-in-one` 属于：

```text
Pattern A: HFS Port Repository
Runtime mode: image-assembly
Space root: repo root
Source of truth: official Dify images
Maintained here: HFS runtime glue, ops/admin, docs, smoke and CI
Alignment manifest: hfs-dev.toml
```

因此本仓库不应迁入 `cloud/hfs/`。`cloud/hfs/` 适用于自研产品仓的 HFS 适配层，即产品源码仍在仓库根维护，而 HFS 只是额外部署目标的 Pattern B。当前仓库维护的不是 Dify 产品源码，而是把官方 Dify Web/API/Plugin/Sandbox 镜像资产组装成 Hugging Face Docker Space demo 的交付包，所以 repo root 必须同时是 Hugging Face Space root 和 GitHub maintenance root。

## Source-of-Truth 判定

判定问题是：

```text
这个仓库到底在维护产品本身，还是在维护某个程序的 HFS 部署交付包？
```

当前事实：

- `README.md` 顶部包含 Hugging Face Space metadata，说明 repo root 是 Space root。
- `Dockerfile` 用多阶段 `FROM` 引入 `langgenius/dify-web`、`langgenius/dify-api`、Plugin Daemon 和 Sandbox 镜像资产。
- `hfs-dev.toml` 声明 Pattern A、image-assembly、repo-root Space root 和发布态 pin surface。
- `docs/architecture.md` 中的组件来源说明：本仓库维护 runtime glue，自维护 Dify GHCR 镜像、独立官方 Plugin/Sandbox 资产和系统依赖都是构建输入。
- `docker/` 承载 entrypoint、Nginx、Supervisor、env defaults、healthcheck、ops-service 和 admin-service。

所以它不是自研产品仓的 `cloud/hfs/` adapter，而是第三方/上游程序的 HFS port repository。

## 目录对齐

当前目录应保持为 Pattern A 结构：

```text
repo-root/
  README.md                 # HF Space card + GitHub 入口，含 metadata
  README.hf-space.md        # HF Space 部署说明
  Dockerfile                # Space build 入口
  hfs-dev.toml              # HFS alignment manifest
  docker/                   # 多进程 runtime glue
  scripts/                  # build/run/smoke/static-check
  docs/                     # 架构、配置、部署、运维、开发、发布
  AGENTS.md                 # repo-local agent router
  .github/workflows/        # static check gate
```

不要新增：

```text
cloud/hfs/README.md
cloud/hfs/Dockerfile
```

对本仓库来说，把 Space root 藏进 `cloud/hfs/` 会让 Hugging Face 直推部署、GitHub 维护入口、文档链接和现有 smoke/CI 契约全部变复杂，并且违反 Pattern A 的目录主权。

## Runtime 获取模式

本仓库是 `image-assembly`：

- Dify Web/API 来自官方上游镜像。
- Plugin Daemon 和 Sandbox 来自官方上游镜像。
- 本仓库把这些资产复制进单个 runtime image，并补齐 PostgreSQL、Redis、Nginx、Supervisor、ops/admin 和 HFS 运行约束。

发布态要求是：构建输入必须能 pin 到不可变标识。当前开发默认值仍允许 `latest` / `main-local`，方便 demo 跟随上游；正式发布记录必须传入并记录实际使用的上游镜像 digest ref。

## Shared HFS Runtime Contract

当前已对齐的契约：

| Contract | Current evidence |
| --- | --- |
| Space metadata | `README.md` frontmatter 含 `sdk: docker` 和 `app_port: 7860` |
| Docker Space build root | repo root 有 `Dockerfile` |
| Alignment manifest | `hfs-dev.toml` 声明 Pattern A、image-assembly 和 repo-root |
| Single public port | `README.md app_port`、`Dockerfile EXPOSE`、`docker/nginx.conf listen` 均为 `7860` |
| Multi-service reverse proxy | `docker/nginx.conf` 把 Web/API/Plugin/Ops/Admin 汇聚到单一入口 |
| Runtime glue location | 多进程 glue 收在 `docker/` |
| `/data` boundary | runtime state 经 `/data` 和 `/persist` 管理，不把 generated state 放进 repo |
| Secrets boundary | `.env.local`、`.env.*.local`、`*.secret`、`*.key`、`*.pem` 被忽略或排除构建上下文 |
| `/_ops` boundary | ops-service 是只读诊断面 |
| `/_admin` boundary | admin-service 默认关闭，写操作有独立 token、CSRF/confirm、审计和白名单 |
| Static gate | `.github/workflows/static-check.yml` 调用 `scripts/static-check.sh` |
| Smoke | `scripts/hf-space-smoke.sh` 覆盖 `/`、`/nginx-health`、`/healthz`、`/_ops/*` 和 admin 默认关闭状态 |

## Release Pin Contract

`hfs-dev.toml` v2 使用结构化 `[[release_pins]]` 描述 release pin contract，并已对齐 `Dockerfile` 真实可消费的 build args。每个 pin 都声明 `name`、`type`、`source`、`required_for_release` 和 `dev_mutable_default_allowed`；image ref pin 还声明 `release_requires_digest=true`。

所有镜像和 source provenance 都通过独立输入完成：

```text
BASE_IMAGE_REF
DIFY_SOURCE_REPO
DIFY_SOURCE_MAIN_REF
DIFY_UPSTREAM_BASE_REF
DIFY_WEB_IMAGE_REF
DIFY_API_IMAGE_REF
DIFY_AGENT_IMAGE_REF
DIFY_AGENT_RUNTIME_IMAGE_REF
PLUGIN_DAEMON_IMAGE_REF
SANDBOX_IMAGE_REF
DIFY_SANDBOX_SOURCE_REF
```

当前 self runtime contract 使用已验证的 GHCR image-specific digest：

```text
BASE_IMAGE_REF=python:3.12-slim-bookworm
DIFY_SOURCE_REPO=https://github.com/BlueSkyXN/dify.git
DIFY_SOURCE_MAIN_REF=4d010cc912753e4a0443cc01721e24d0752bce46
DIFY_UPSTREAM_BASE_REF=ef0115d34030eb496a1bc761b842e3bcd8f5598d
DIFY_WEB_IMAGE_REF=ghcr.io/blueskyxn/dify-web@sha256:17c5a57c432e24179b42c210a5ea48a5c79f4f9844c6944f6bf33a5d0cdb9054
DIFY_API_IMAGE_REF=ghcr.io/blueskyxn/dify-api@sha256:ff5cfc41d95fb28abf13854c0c215d0680a611d53390bd012a6b83191ae68ad9
DIFY_AGENT_IMAGE_REF=ghcr.io/blueskyxn/dify-agent-backend@sha256:45938ec2584eaf43a4d0ca6502874ac5c84dc960c60cd6067d79117aea7b58df
DIFY_AGENT_RUNTIME_IMAGE_REF=ghcr.io/blueskyxn/dify-agent-local-sandbox@sha256:f88faab3f5cc8aa24ca07d1cc45750aaa531c6147fd504d690bae3d6e922e93b
PLUGIN_DAEMON_IMAGE_REF=langgenius/dify-plugin-daemon@sha256:1c1f80c9814f896a31ef84c0551245fa1876d054bc51c53c3f075ae20ccc2566
SANDBOX_IMAGE_REF=langgenius/dify-sandbox@sha256:cb076f71cc84c14d4e4f7753ff95c4ba70a3b5816962b4f93bcf42f23a6e5cb8
DIFY_SANDBOX_SOURCE_REF=97c8097d51d0f46238bb720b1e9e9439ce68784d
UV_VERSION=0.11.21
DIFY_VERSION=BlueSkyXN-dify-main-4d010cc912753e4a0443cc01721e24d0752bce46
```

self source revision 和四个 image-specific digest 已由同一 Actions release artifact 验证，使 API、Web、Agent venv 与 Agent Go runtime 保持同一 release 边界。更新时必须继续原子替换这些 pin。`DIFY_UPSTREAM_BASE_REF` 只记录已合入 self fork 的 upstream commit，不参与 `FROM`。Sandbox 的 `/conf` 和 `/dependencies` 仍来自 `SANDBOX_IMAGE_REF`，server binary 仍来自 source-pinned HFS patch build；Agent 的两个 venv 必须保持隔离。

`DIFY_VERSION` 只保留为 metadata，供 runtime 展示和人工记录使用。它不是 selected image content 的证据；只改它不会改变 self GHCR artifacts。Sandbox server binary 来自 `DIFY_SANDBOX_SOURCE_REF` 加本仓库 patch，`SANDBOX_IMAGE_REF` 仍用于提供官方 `/conf` 和 `/dependencies`，并且必须通过启动期 `sandbox_exec` 真实执行自检后才能进入可送审状态。这个自检不只看 marker，还要求 sandbox response 的 `exit_code=0` 且 `error=""`。

## 对其他 HFS 项目的迁移规则

统一规范时不要从 `dify-all-in-one` 直接复制目录；先按 source of truth 分类：

```text
第三方/上游程序 HFS 移植:
  Pattern A
  repo root == Space root
  多服务 glue 放 docker/ 或 hfs/

自研产品额外支持 HFS:
  Pattern B
  产品根保持产品维护语义
  HFS 实现放 cloud/hfs/
  cloud/hfs/ 必须能导出或同步为独立 Space root
```

再按 runtime 获取模式选择 pin 策略：

```text
self-contained             -> base image tag/digest
image-assembly             -> upstream image digest
source-fetch               -> git commit SHA
artifact-at-build-time     -> release version + artifact SHA256
artifact-at-runtime        -> artifact SHA256
```

最后套用 shared contract：Space metadata、single public port、Nginx/reverse proxy、healthcheck、smoke、`/data`、secrets、`/_ops`、`/_admin` 和 static gate。
