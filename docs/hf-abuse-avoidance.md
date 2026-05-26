# Hugging Face Abuse Avoidance

本文档记录 `dify-all-in-one` 在 Hugging Face Docker Space 上避免触发平台 abuse-handler 的原则、发布前检查和触发后的处理流程。它不是 Hugging Face 官方政策解释；实际判定以 Hugging Face 平台、Support 和 Space runtime metadata 为准。

## 背景

本仓库是单容器 Dify demo bundle，适合企业内训、课程演示、PoC 和快速功能验证，不是生产部署方案。Hugging Face Space 是受管平台，平台侧会对 runtime 进程、网络行为、公开入口和资源使用做自动化风控。

2026-05-26 的一次 live Space 排查中，`BlueSkyXN/dify-all-in-one` 的 Space metadata 显示：

```text
runtime.stage=PAUSED
runtime.raw.errorMessage=Flagged as abusive
runtime.raw.abuse.detector=abuse-handler
```

核心触发原因是 runtime 里出现了可写 Web terminal 进程：

```text
cmdline match: 'ttyd' in
'ttyd --interface 127.0.0.1 --port 7681 --base-path /_admin/terminal --max-clients 1 --writable /bin/bash'
```

这说明问题不只是 sleep time、pause/restart UI 或仓库可见性，而是 Hugging Face runtime 被 abuse-handler 标记。即使 Web terminal 只绑定 `127.0.0.1`，并且前面有 Nginx `auth_request`、`ADMIN_TOKEN` 或 Private Space 边界，平台自动风控仍可能直接按进程命令行特征拦截。

## 如何检查具体风控信息

Hugging Face UI 可能只显示通用错误，例如 pause/restart 失败、Space 无法启动或 sleep setting 不可修改。具体风控原因通常要从 Space runtime metadata 里看，而不是只看页面提示。

前提：

- 本机已安装并登录 Hugging Face CLI。
- 当前 token 对目标 Space 有读取权限。
- 已知目标 Space ID，例如 `BlueSkyXN/dify-all-in-one`。

如果不确定 Space ID，可以先按账号和关键词列出候选 Space：

```bash
hf spaces list \
  --author BlueSkyXN \
  --search dify \
  --limit 20 \
  --expand author,disabled,private,runtime,sdk,sha,subdomain,lastModified \
  --json
```

确认 Space ID 后，读取目标 Space metadata：

```bash
hf spaces info BlueSkyXN/dify-all-in-one \
  --expand author,disabled,private,runtime,sdk,sha,subdomain,lastModified \
  --json
```

重点检查这些字段：

| Field | Meaning |
| --- | --- |
| `disabled` | Space repo 是否被平台禁用。`false` 表示仓库实体通常还在。 |
| `private` | Space 可见性，不等于 runtime 安全状态。 |
| `runtime.stage` | 简化 runtime 状态，例如 `RUNNING`、`BUILDING`、`PAUSED`。 |
| `runtime.raw.stage` | 平台 raw runtime 状态，排障时优先保留。 |
| `runtime.raw.errorMessage` | 平台返回的 runtime 错误摘要，例如 `Flagged as abusive`。 |
| `runtime.raw.abuse.flaggedAt` | 被 abuse-handler 标记的时间。 |
| `runtime.raw.abuse.detector` | 命中的检测器，例如 `abuse-handler`。 |
| `runtime.raw.abuse.reason` | 具体命中原因，通常是最关键证据。 |
| `sha` | Space repo 当前顶层 SHA，不等于 runtime 已接管该 SHA。 |
| `runtime.raw.sha` | 如果存在，表示 runtime 实际接管的 commit SHA。 |

本次定位 web terminal 风控的关键不是 UI 文案，而是 metadata 中的这组字段：

```text
runtime.stage=PAUSED
runtime.raw.errorMessage=Flagged as abusive
runtime.raw.abuse.detector=abuse-handler
runtime.raw.abuse.reason=Blocked by abuse-handler by rule: cmdline match: 'ttyd' ...
```

如果 `runtime.raw.abuse.reason` 里出现 `cmdline match`，要优先按进程命令行理解触发源。比如 `ttyd --writable /bin/bash` 表明平台检测到一个可写 Web shell 形态的进程，而不是单纯的页面路由、Nginx 配置或 sleep setting 问题。

这些字段是 live runtime 状态，可能随 Hugging Face 平台处理、重新构建、人工解除 flag 或 CLI/API 版本变化而变化。排障记录里应保存当时的 `space-id`、命令、时间、`sha`、`runtime.stage`、`errorMessage` 和 `abuse.reason`，但不要保存 token、secret、`.env` 内容或客户数据。

## 外部相似案例与共性模式

公开社区案例显示，Hugging Face Spaces 的风控或审核类拦截并不总是在 UI 中直观显示。多个案例中，用户在页面上只看到 restart、resume、factory rebuild 或 pause 失败，甚至 build/container logs 没有明显错误；但通过 HF API 或 runtime metadata 才能看到更具体的 moderation / abuse 信息。

相似案例：

| Case | Public signal | Shared lesson |
| --- | --- | --- |
| [Cloudflare rule false positive](https://discuss.huggingface.co/t/space-flagged-as-abusive-by-cloudflare-rule-false-positive-requesting-review/176047) | `errorMessage` 显示 Space 被标记，原因指向 `abuse-handler` 的 Cloudflare rule | HF 存在自动 abuse-handler 规则，可能按高风险关键词或行为特征触发 |
| [Tunnel / Cloudflare pattern](https://discuss.huggingface.co/t/space-flagged-as-abusive-false-positive-cannot-restart-after-removing-flagged-file/173676) | Detector 为 `RepoScanner`，Category 为 `huggingface:tunnel`，删除文件后 flag 仍存在 | 修改或删除触发文件不一定自动解除 moderation flag |
| [Trojan proxy on port 7860](https://discuss.huggingface.co/t/space-flagged-as-abusive-reason-trojan-proxy-need-help-unblocking/176099) | UI 只显示 restart 失败；HF API 显示 moderation pause 和 proxy 相关原因 | UI 的 503 / restart 失败只是表层症状，metadata 才是定性依据 |
| [Generic restart 503](https://discuss.huggingface.co/t/having-error-in-restarting-space/173572) | 社区排障说明 restart 503 可能来自 build、runtime、health 或平台状态等多种阶段 | 看到 503 不能直接判定为 build 问题或风控问题，必须继续查 logs 和 runtime metadata |

这些案例的共性：

- UI 的 503、restart 失败、pause 失败或 factory rebuild 失败只是表层症状，不能直接判定根因。
- 一旦 Space 被 abuse / moderation flag 标记，删除文件、rollback、factory rebuild、resume 或 restart 不一定自动解除。
- tunnel、proxy、VPN、remote management、remote shell、VNC、Chrome Remote Server、Cloudflare Tunnel 等能力属于平台风控高敏感区域。
- 对 HF Space 来说，应避免自带 Web terminal、SSH server、reverse tunnel、proxy、remote desktop、任意命令执行入口。
- 如确需调试运行中容器，应优先使用 Hugging Face 官方 [Spaces Dev Mode](https://huggingface.co/docs/hub/spaces-dev-mode)，而不是在普通 Space runtime 中内置 `ttyd`、WebSSH 或 browser shell。
- 触发后应保存 runtime metadata 证据，移除或禁用高风险能力，然后联系 Hugging Face Support / appeal，请求解除 moderation flag。

Hugging Face 的 [Content Policy](https://huggingface.co/content-policy) 将 Platform Abuse、Security Violations 和 Spam 列为 Restricted Content，并把 unauthorized remote management tools、Cloudflare Tunnel、TOR、proxies、VNC、Chrome Remote Server 等绕过限制或远程控制能力放在高风险范围。该政策没有逐字列出 `ttyd`，因此本文档不应写成“HF 明文禁止 ttyd”。更稳妥的工程表述是：`ttyd --writable /bin/bash` 在普通 Space runtime 中呈现为 Web 可达的交互式 shell，容易被 abuse-handler 按 remote management / remote shell 风险族群处理。

`ttyd` 自身项目定位是把 terminal 暴露到 Web。它本身不是恶意工具；问题在于把 `ttyd --writable /bin/bash` 放进 HF Space runtime，会让平台看到类似“Web 可达可写 shell”的能力特征。即使前面有 Nginx 鉴权、只绑定 `127.0.0.1`、Space 是 private，平台风控也可能基于进程命令行和能力特征直接拦截。

## 核心原则

- 不要在 Hugging Face Space runtime 中启动可交互 shell、反向 shell、Web terminal、SSH server、remote desktop 或类似远程控制面。
- 不要依赖 `127.0.0.1`、Nginx 鉴权、Private Space 或 admin token 来证明 Web shell 是安全的；平台风控可能只看到容器进程和命令行。
- 不要把 `/_ops`、`/_admin` 或 demo token 包装成生产级安全边界。
- 不要让公开入口暴露任意命令执行、任意文件读取、SQL 执行、服务重启、配置写入或 secret 原文读取。
- 不要在 Space 上长时间运行与 demo 无关的后台任务、爬虫、代理、隧道、下载器或高频外联任务。
- 需要排障时优先使用 Hugging Face logs、`/_ops` 只读诊断、健康检查和 smoke 脚本，而不是交互式 shell。

## 可接受的控制面替代方案

移除 `ttyd`、WebSSH、SSH daemon 或 remote desktop 后，仍然可以保留必要的诊断和受控管理能力，但设计目标应从“远程进入容器 shell”改为“自研、白名单、可审计的有限控制面”。

推荐方向：

- 使用自研 HTTP API 或 WebSocket API 承载明确的业务事件、状态流和进度输出，而不是承载通用 shell stdin/stdout。
- 将控制动作编译进服务端二进制或自研服务逻辑中，通过白名单 action 暴露，例如 health check、reload Nginx、restart 指定 supervisor program。
- 只接受结构化参数，不接受任意 command string、SQL string、文件路径直通或 shell snippet。
- 每个写操作都要求强 token、显式 `confirm=true`、CSRF 边界、audit log 和最小权限。
- 诊断面优先只读，管理面单独放在 `/_admin`，不要把写操作塞进 `/_ops`。
- WebSocket 只用于状态推送、日志 tail、任务进度或交互式表单状态，不用于实现浏览器 shell。

这些方案只能降低平台风控和应用安全风险，不能保证 Hugging Face 一定接受。平台仍可能根据进程名、命令行、网络行为、资源使用、外联目标或历史规则判定风险。因此，自研控制面也要避免出现明显的远控形态，例如 `bash`、`sh`、`ssh`、`ttyd`、`vnc`、`proxy`、`tunnel`、任意代码执行或可写文件系统浏览器。

本仓库当前保留的控制面属于这一路线：

| Surface | Type | Boundary |
| --- | --- | --- |
| `/_ops/` | 自研只读诊断面 | health、status、system、metrics、config 摘要、日志白名单、errors，不执行写操作 |
| `/_admin/` | 自研受控管理面 | 默认关闭；白名单 action、强 `ADMIN_TOKEN`、CSRF/confirm、audit；不接受任意 shell command |
| `/_admin/api/files/*` | 自研可选 file manager | 默认关闭；读写和 destructive action 分开 gate；保护 secret/key/token 路径 |

如果未来需要更强交互能力，优先做“领域专用控制协议”，而不是恢复通用 shell。比如：

- 用 WebSocket 推送 build/smoke 进度，但后端只运行固定 action id。
- 用按钮触发固定 diagnostic bundle，但不允许用户输入任意命令。
- 用结构化表单修改允许列表内的配置项，但不暴露 `.env` 原文或任意文件写入。
- 用只读日志 tail 观察指定 service 白名单，而不是打开 shell 后 `tail -f`。

## 明确高风险能力

以下能力在 Hugging Face Space 上应默认禁止，除非已经确认符合平台政策并且接受被风控的风险：

| Capability | Risk | Repository stance |
| --- | --- | --- |
| `ttyd --writable /bin/bash` | Web 页面可写 shell，容易被识别为远程交互式 shell | 不应在 HF runtime 启动 |
| `WEBSSH_ENABLED=true` | 会启动 Web terminal 路径 | HF Space 上不要开启 |
| SSH daemon / remote desktop | 远程控制面 | 不要加入 demo image |
| Arbitrary command endpoint | 任意命令执行 | 不要放进 `/_ops` 或 `/_admin` |
| Arbitrary file browser with destructive writes | 数据泄露和破坏风险 | 必须有独立 gate，HF 上默认关闭 |
| Public proxy / tunnel / port forwarder | 可能被滥用为代理服务 | 不要作为 demo 默认能力 |
| Secret echo / raw config dump | 凭据泄露 | 只返回 presence boolean 或脱敏摘要 |

## Web terminal policy

`ttyd` 是把命令行程序暴露成 Web terminal 的工具。典型链路是：

```text
browser <-> HTTP/WebSocket <-> ttyd <-> /bin/bash
```

在本仓库的历史设计中，`WEBSSH_ENABLED=true` 时，`/_admin/terminal/` 会通过 admin 鉴权代理到容器内的 `ttyd`。这类能力适合本地临时调试，不适合 Hugging Face Space runtime。

HF Space 的推荐策略是：

- 镜像不安装 `ttyd`
- Nginx 不暴露 `/_admin/terminal/`
- `WEBSSH_*` 不作为受支持配置
- 不在 Space Variables 或 Secrets 中保存用于开启 Web terminal 的配置
- 如果未来重新引入 terminal 能力，必须把 HF Space 与本地/private runtime 区分开，并在发布前确认镜像不会启动 `ttyd`、SSH 或其他交互式 shell server

## 推荐诊断方式

优先使用只读、可审计的诊断入口：

```bash
hf spaces info <space-id> --expand runtime,disabled,private,sdk,sha,subdomain --json
hf spaces logs <space-id> -n 220
hf spaces logs <space-id> --build -n 220
curl https://your-space.hf.space/nginx-health
curl https://your-space.hf.space/healthz
curl -H "X-Ops-Token: $OPS_TOKEN" https://your-space.hf.space/_ops/health
```

如果需要更完整的发布后检查，使用仓库 smoke 脚本：

```bash
OPS_TOKEN=your-configured-ops-token \
  scripts/hf-space-smoke.sh https://your-space.hf.space
```

这些诊断方式不应触发写操作，也不需要交互式 shell。

## 发布前 abuse 自检

修改 Dockerfile、Supervisor、Nginx、admin、ops、terminal、下载器、启动脚本或外联逻辑后，发布到 Hugging Face Space 前做一次 abuse-oriented 自检。

检查高风险关键字：

```bash
rg -n "ttyd|WEBSSH|web-terminal|ssh|sshd|dropbear|vnc|novnc|xrdp|tmux|screen|/bin/bash|/bin/sh|--writable|proxy|tunnel|ngrok|cloudflared" \
  Dockerfile docker scripts docs README.md README.hf-space.md
```

检查 Space runtime metadata：

```bash
hf spaces info <space-id> --expand runtime,disabled,private,sdk,sha,subdomain --json
```

重点看：

- `runtime.stage` 是否是预期状态
- `runtime.raw.errorMessage` 是否为空或符合预期
- `runtime.raw.abuse` 是否存在
- `runtime.raw.sha` 是否等于本次期望 commit
- Space 是否使用了不应出现在 HF 上的 Variables 或 Secrets

如果看到 `Flagged as abusive`、`abuse-handler`、`cmdline match`、`ttyd`、`shell` 等字段，不要继续反复 restart；先移除触发源并准备申诉。

## Space 设置建议

Hugging Face Space 上建议保持：

```env
ADMIN_ENABLED=false
```

如果演示确实需要 `/_admin`，只在 Private 或 Protected Space 中短期开启：

```env
ADMIN_ENABLED=true
ADMIN_TOKEN=<strong-random-token>
```

不要重新添加或开启 Web terminal。`ADMIN_TOKEN` 可以保护应用路由，但不能保证平台风控接受交互式 shell 进程。

## 触发后的处理流程

1. 停止反复点击 Pause、Restart 或切换 sleep setting，避免制造更多不确定状态。
2. 读取 Space metadata，确认是否存在 `runtime.raw.errorMessage` 和 `runtime.raw.abuse`。
3. 记录 `space-id`、`sha`、`runtime.stage`、`flaggedAt`、`detector` 和 `reason`。
4. 移除或禁用触发源，例如 `ttyd`、Web terminal、SSH、proxy、tunnel 或任意命令执行入口。
5. 重新提交一个不包含触发源的修复版本。
6. 如果 Space 仍不能 restart，联系 Hugging Face Support 或提交 appeal，说明触发源、修复 commit 和当前期望状态。

申诉说明可以包含：

```text
This Space is a private Docker Space demo for Dify all-in-one training/PoC usage.
The abuse flag appears to have been triggered by a break-glass web terminal process using ttyd.
We have removed or disabled the web terminal path and no longer start ttyd, SSH, or any writable shell server in the Space runtime.
Please review and clear the runtime abuse flag for <space-id>.
```

不要在申诉、公开 issue、PR 描述或截图里粘贴真实 token、secret、内部 URL、客户数据或 `.env` 内容。

## 文档同步要求

如果未来调整 Hugging Face runtime 安全边界，同步检查：

- `README.hf-space.md`
- `docs/deployment.md`
- `docs/configuration.md`
- `docs/security.md`
- `docs/ops-runbook.md`
- `docker/dify.env.runtime`
- `docker/supervisord.conf`
- `scripts/hf-space-smoke.sh`

涉及 shell、Nginx、Dockerfile、env、Supervisor、ops-service 或 runtime lifecycle 的改动，按根级 `AGENTS.md` 的验证标准选择最小验证集合。不要把 syntax check 通过写成 Docker image 可运行的证据；runtime 可用性仍需 Docker 或 live Space smoke 证明。
