# Dify All-in-One Docs

这个目录是 `dify-all-in-one` 的完整工程文档入口。本文档体系以当前仓库实现为准，覆盖从镜像构建、启动初始化、进程编排、Nginx 路由、配置变量、数据目录、运维诊断到开发验证的完整链路。

## 推荐阅读顺序

1. [Project Overview](./project-overview.md): 项目目标、适用场景、边界、目录结构和核心设计取舍。
2. [Architecture](./architecture.md): 容器内组件拓扑、请求路由、启动顺序、数据流和依赖关系。
3. [Runtime Lifecycle](./runtime-lifecycle.md): Dockerfile 构建阶段、entrypoint 初始化、supervisord 进程生命周期和迁移顺序。
4. [Configuration Reference](./configuration.md): 环境变量分组、默认值、覆盖优先级、Secrets 和 Hugging Face Space 设置。
5. [Deployment Guide](./deployment.md): Hugging Face Space 部署、本地 Docker 运行、发布后 smoke 和 runtime 状态确认。
6. [Operations Runbook](./ops-runbook.md): `/_ops` 诊断入口、健康检查、日志查看、502 排障和发布验收。
7. [Development Guide](./development.md): 本地开发、改动点、验证命令、提交前检查和常见修改流程。
8. [File Reference](./file-reference.md): 仓库内每个受版本控制文件的职责说明。
9. [Security Notes](./security.md): 演示环境安全边界、默认密钥、公开 Space 风险和生产化注意事项。

## 快速命令

线上 smoke：

```bash
OPS_TOKEN=dify_ops_demo_token \
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

本地运行：

```bash
scripts/run-demo.sh
```

公开 Space 建议在 Space Settings -> Variables 中覆盖 `OPS_TOKEN`，并将 Space 设置为 Private 或 Protected。
