# Dify All-in-One Docs

这个目录收纳 Hugging Face Docker Space 版本的运维、排障和扩展文档。

## 文档索引

- [Operations Runbook](./ops-runbook.md): Nginx 前置、`ops-service`、健康检查、日志入口、502 排障和发布后验收。

## 快速入口

线上只读诊断入口：

```text
/_ops/
```

常用命令：

```bash
OPS_TOKEN=dify_ops_demo_token \
  scripts/hf-space-smoke.sh https://blueskyxn-dify-all-in-one.hf.space
```

公开 Space 建议在 Space Settings -> Variables 中覆盖 `OPS_TOKEN`，并将 Space 设置为 Private 或 Protected。
