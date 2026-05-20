# Dify All-in-One Docs

这个目录是 `dify-all-in-one` 的完整工程文档入口。本文档体系以当前仓库实现为准，覆盖从镜像构建、启动初始化、进程编排、Nginx 路由、配置变量、数据目录、运维诊断到开发验证的完整链路。

## 推荐阅读顺序

1. [Project Overview](./project-overview.md): 项目目标、适用场景、边界、目录结构和核心设计取舍。
2. [Project Status and Roadmap](./project-status-and-roadmap.md): 当前实现状态、未完成事项、下一步计划和本次审查循环。
3. [Architecture](./architecture.md): 容器内组件拓扑、请求路由、启动顺序、数据流和依赖关系。
4. [Runtime Lifecycle](./runtime-lifecycle.md): Dockerfile 构建阶段、entrypoint 初始化、supervisord 进程生命周期和迁移顺序。
5. [Configuration Reference](./configuration.md): 环境变量分组、默认值、覆盖优先级、Secrets 和 Hugging Face Space 设置。
6. [Deployment Guide](./deployment.md): Hugging Face Space 部署、本地 Docker 运行、发布后 smoke 和 runtime 状态确认。
7. [Release Checklist](./release-checklist.md): GitHub PR、`main`、Hugging Face runtime 和 smoke 的证据记录模板。
8. [Bucket-Lite Persistence Drill](./bucket-lite-drill.md): `/persist`、PostgreSQL fallback、dump backup 和重启保留的演练模板。
9. [Operations Runbook](./ops-runbook.md): `/_ops` 诊断入口、健康检查、日志查看、502 排障和发布验收。
10. [Development Guide](./development.md): 本地开发、改动点、验证命令、提交前检查和常见修改流程。
11. [File Reference](./file-reference.md): 仓库内每个受版本控制文件的职责说明。
12. [Security Notes](./security.md): 演示环境安全边界、默认密钥、公开 Space 风险和生产化注意事项。

## 快速命令

线上 smoke：

```bash
OPS_TOKEN=your-configured-ops-token \
  scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

线上只读诊断入口：

```text
https://blueskyxn-dify-all-in-one.hf.space/_ops/
```

本地构建：

```bash
scripts/build.sh
```

静态检查：

```bash
scripts/static-check.sh
```

本地运行：

```bash
scripts/run-demo.sh
```

公开 Space 建议在 Space Settings -> Secrets 中覆盖 `OPS_TOKEN`，并将 Space 设置为 Private 或 Protected。`dify_ops_demo_token` 只是未覆盖时的 demo 默认值，线上命令应使用 Space 当前配置的 token。
