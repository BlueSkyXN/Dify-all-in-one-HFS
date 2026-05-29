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
- `docs/architecture.md` 中的组件来源说明：本仓库只维护 runtime glue，Dify 官方镜像资产和系统依赖是构建输入。
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

发布态要求是：构建输入必须能 pin 到不可变或足够明确的标识。当前开发默认值仍允许 `latest` / `main-local`，方便 demo 跟随上游；正式发布记录必须写清实际使用的上游镜像 tag 或 digest。

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
| Secrets boundary | `.env.local`、`*.secret`、`*.key`、`*.pem` 被忽略或排除构建上下文 |
| `/_ops` boundary | ops-service 是只读诊断面 |
| `/_admin` boundary | admin-service 默认关闭，写操作有独立 token、CSRF/confirm、审计和白名单 |
| Static gate | `.github/workflows/static-check.yml` 调用 `scripts/static-check.sh` |
| Smoke | `scripts/hf-space-smoke.sh` 覆盖 `/`、`/nginx-health`、`/healthz`、`/_ops/*` 和 admin 默认关闭状态 |

## 当前 Gap

主要 gap 是发布态 pin 还没有完全机器化。`hfs-dev.toml` 已把 release pin surface 作为显式字段，但当前 `Dockerfile` 仍保留历史兼容的 `DIFY_VERSION` + `DIFY_API_IMAGE` / `DIFY_WEB_IMAGE` 拼接模式。

当前 `Dockerfile` 允许通过 build args 覆盖 Dify、Plugin Daemon、Sandbox 和 uv 输入，但默认值仍偏开发便利：

```text
DIFY_VERSION=latest
UV_VERSION=latest
PLUGIN_DAEMON_IMAGE=langgenius/dify-plugin-daemon:main-local
SANDBOX_IMAGE=langgenius/dify-sandbox:latest
```

这不等于发布态不可复现。发布或长期演示前应记录并传入明确版本，优先使用镜像 digest；至少不能只把 `latest` / `main-local` 当作最终发布依据。

建议后续增强：

- 在 release checklist 里记录 Dify Web/API、Plugin Daemon、Sandbox、uv 和 base image 的实际 tag/digest。
- 如果要强制 digest pin，再重构 `Dockerfile` 的 image ref build args，避免 `image:tag` 拼接阻碍 `image@sha256:...` 形式。

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
