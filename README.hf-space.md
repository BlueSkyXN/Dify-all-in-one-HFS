# Hugging Face Space 部署说明

本工程已经按 Hugging Face Docker Space 形态调整：

- 根目录 `README.md` 带 `sdk: docker` 和 `app_port: 7860` 元数据。
- 根目录 `Dockerfile` 是 Space 的构建入口。
- 容器运行时使用 UID 1000 的 `user` 用户。
- 所有持久化数据写入 `/data`。
- Nginx 对外监听 `7860`，内部转发到 Dify Web/API/Plugin Daemon。
- 如果运行时存在 `SPACE_HOST` 且 `PUBLIC_URL` 未设置，会自动变成 `https://${SPACE_HOST}`。

建议 Space Settings：

```text
Hardware: CPU Upgrade
Storage: 启用持久化 Storage
Visibility: Private 或 Protected
```

建议 Variables：

```env
MARKETPLACE_ENABLED=false
SANDBOX_ENABLE_NETWORK=false
FORCE_VERIFYING_SIGNATURE=false
```

建议 Secrets：

```env
SECRET_KEY=<固定强随机值>
PLUGIN_DAEMON_KEY=<固定强随机值>
PLUGIN_DIFY_INNER_API_KEY=<固定强随机值>
CODE_EXECUTION_API_KEY=<固定强随机值>
SANDBOX_API_KEY=<固定强随机值>
```

如果只做一次性公开演示，可以不设置 Secret；如果要多次重启后保持登录、文件 URL、插件凭据一致，必须设置固定 Secret 或启用持久化 Storage。
