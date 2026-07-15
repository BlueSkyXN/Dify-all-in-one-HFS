# Release Checklist

本文档用于记录一次从 GitHub PR 到 `main`，再到可选 Hugging Face Space 发布的最小证据链。它不是生产发布流程；目标是让 demo 仓库每次变更都能说明“提交了什么、验证了什么、线上是否接管”。

## 发布边界

默认发布顺序：

```text
feature branch -> GitHub PR -> origin/main -> optional hf/main -> HF runtime -> smoke
```

当前常见 remote 语义：

```text
origin  GitHub remote: https://github.com/BlueSkyXN/Dify-all-in-one-HFS.git
hf      Hugging Face Space: https://huggingface.co/spaces/<space-id>
```

推送 `origin/main` 不会触发 Hugging Face Space rebuild。只有推送到实际指向 Space 的 remote，通常是 `hf main`，才会触发 Docker build。

## PR 合并前

记录：

```text
PR number:
Branch:
Base:
Head SHA:
Diff summary:
Files:
```

最小检查：

```bash
git status --short --branch
scripts/static-check.sh
git diff --check
```

HFS 范式记录：

```text
Classification: Pattern A / HFS Port Repository
Runtime mode: image-assembly
Space root: repo root
Manifest: hfs-dev.toml
HFS contract check: scripts/validate-hfs-contract.sh
```

发布态 build inputs 记录：

```text
BASE_IMAGE_REF:
DIFY_API_IMAGE_REF:
DIFY_WEB_IMAGE_REF:
PLUGIN_DAEMON_IMAGE_REF:
SANDBOX_IMAGE_REF:
UV_VERSION:
DIFY_VERSION metadata:
All image refs use digest? yes/no:
Mutable defaults used? yes/no + reason:
```

当前 Dify Web/API 默认已固定为兼容的 `1.16.0-rc1` digest pair；Plugin Daemon、Sandbox、base image 和 uv 仍可能使用现有可移动开发默认值。发布或长期演示必须记录并固定全部输入；`DIFY_VERSION` 只作为 metadata，不是 selected image content 的证据。

`scripts/build.sh` 会透传当前 shell 中同名 build arg 环境变量；如果不用脚本，必须在 `docker build` 命令里显式传入对应 `--build-arg`。

如果改动涉及 `docker/` runtime lifecycle、Nginx、Supervisor、env、ops-service、admin-service 或 build 行为，额外记录是否运行：

```text
Docker build:
Local run:
Local smoke:
Reason if skipped:
```

对应命令：

```bash
scripts/build.sh
scripts/run-demo.sh
ALLOW_DEMO_OPS_TOKEN=true OPS_TOKEN=dify_ops_demo_token scripts/hf-space-smoke.sh http://localhost:8080
```

如果 PR 改动了 `docker/sandbox-python-requirements.txt`，至少记录目标 Python wheel 检查：

```bash
python3 -m pip download --only-binary=:all: --python-version 3.12 --implementation cp --abi cp312 --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 -r docker/sandbox-python-requirements.txt
python3 -m pip download --only-binary=:all: --python-version 3.14 --implementation cp --abi cp314 --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 -r docker/sandbox-python-requirements.txt
```

## 合并到 GitHub main

合并后记录：

```text
Merge method:
Merged PR:
origin/main SHA:
GitHub checks:
```

回读：

```bash
git fetch origin
git rev-parse origin/main
gh pr view <number> --json state,mergedAt,mergeCommit,statusCheckRollup
```

本地收口：

```bash
git switch main
git pull --ff-only origin main
git status --short --branch
```

## 发布到 Hugging Face Space

只有需要更新 live demo 时执行。

发布前确认 remote：

```bash
git remote -v
```

推送：

```bash
git push hf main
```

记录：

```text
Expected Space SHA:
HF push result:
Build log checked:
App log checked:
```

回读 Space runtime：

```bash
hf spaces info <space-id>
```

必须确认：

```text
runtime.stage = RUNNING
runtime.raw.sha = <expected main sha>
```

注意：`sha` 更新只能说明 Space repo 收到了提交；`runtime.raw.sha` 等于目标提交才说明新镜像接管流量。

## 发布后 smoke

线上 smoke：

```bash
OPS_TOKEN=your-configured-ops-token \
  scripts/hf-space-smoke.sh https://your-space.hf.space
```

必要时增加重试：

```bash
OPS_TOKEN=your-configured-ops-token \
SMOKE_RETRIES=60 \
SMOKE_DELAY=5 \
scripts/hf-space-smoke.sh https://your-space.hf.space
```

记录：

```text
Smoke command:
Smoke result:
Ops health:
Ops errors:
Known skipped checks:
```

只读诊断：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://your-space.hf.space/_ops/health

curl -H "X-Ops-Token: $OPS_TOKEN" \
  https://your-space.hf.space/_ops/errors
```

## 发布记录模板

```text
Date:
Operator:
PR:
Branch:
Head SHA:
Merge SHA:
origin/main SHA:
hf/main SHA:
HF runtime.raw.sha:

Checks:
- GitHub Static Check:
- Local static-check:
- Docker build:
- Local smoke:
- HF runtime info:
- HF smoke:

Notes:
- Not run:
- Known risks:
- Follow-up PR:
```
