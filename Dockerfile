# syntax=docker/dockerfile:1.7
#
# Dify all-in-one demo image
# Target: Hugging Face Docker Space training / demo / PoC, not production.
# Runtime is intentionally rootless to match HF Spaces UID 1000 expectations.
#
# Build example:
#   docker build -t dify-all-in-one-hf-space:latest .
#
# Run example:
#   docker run --rm -it \
#     -p 8080:7860 \
#     -v dify-hf-demo-persist:/persist \
#     --env-file docker/dify.env.demo \
#     dify-all-in-one-hf-space:latest

ARG BASE_IMAGE_REF=python:3.12-slim-bookworm
ARG DIFY_WEB_IMAGE_REF=langgenius/dify-web@sha256:a9da248482d446889b4b153a44766eaf9b34934a29b3406307b4dba7085d62c7
ARG DIFY_API_IMAGE_REF=langgenius/dify-api@sha256:d4be5a72cf33b29de4b7d00c30f1ca8ab929bb35948ecdcbb3e18bfb6f6d6857
ARG PLUGIN_DAEMON_IMAGE_REF=langgenius/dify-plugin-daemon@sha256:3c694329357bc580b28bdec59321a981acd3279f8f69d1a3fb59a47cf7f770c3
ARG SANDBOX_IMAGE_REF=langgenius/dify-sandbox@sha256:41632ad63bddd8bcea83453270f3284d287c9e7cb463dac96644268770270788
ARG DIFY_SOURCE_REPO=https://github.com/BlueSkyXN/dify.git
ARG DIFY_SOURCE_MAIN_REF=d5ecd503008d2ce21e93ff07d864dcb82307f93a
ARG DIFY_AGENT_SOURCE_REF=d5ecd503008d2ce21e93ff07d864dcb82307f93a
ARG DIFY_SANDBOX_SOURCE_REF=44cdbd5d1991b97e40cb113c669800f4628920bb
ARG DIFY_VERSION=BlueSkyXN-dify-main-d5ecd503008d2ce21e93ff07d864dcb82307f93a-agent-d5ecd503008d2ce21e93ff07d864dcb82307f93a
ARG UV_VERSION=0.11.21

# -----------------------------
# Use official prebuilt Dify Web assets
# -----------------------------
FROM ${DIFY_WEB_IMAGE_REF} AS web-builder
RUN test -d /app/targets/next \
    && test -d /app/targets/vinext \
    && test -x /app/entrypoint.sh
RUN touch /tmp/web-builder.done


# -----------------------------
# Use official prebuilt Dify API source and virtualenv
# -----------------------------
FROM ${DIFY_API_IMAGE_REF} AS api-image
COPY --from=web-builder /tmp/web-builder.done /tmp/web-builder.done
RUN test -d /app/api/.venv \
    && test -x /app/api/.venv/bin/flask \
    && test -x /app/api/docker/entrypoint.sh
RUN touch /tmp/api-builder.done


# -----------------------------
# External official runtime assets
# -----------------------------
FROM ${PLUGIN_DAEMON_IMAGE_REF} AS plugin-daemon-image
FROM ${SANDBOX_IMAGE_REF} AS sandbox-image


# -----------------------------
# Build a small HFS-compatible Dify Sandbox binary patch
# -----------------------------
FROM golang:1.25-bookworm AS sandbox-builder
ARG DIFY_SANDBOX_SOURCE_REF
ARG TARGETARCH
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates git pkg-config gcc libseccomp-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init \
    && git remote add origin https://github.com/langgenius/dify-sandbox.git \
    && git fetch --depth 1 origin "${DIFY_SANDBOX_SOURCE_REF}" \
    && git checkout --detach FETCH_HEAD
COPY docker/patches/dify-sandbox-hfs-uidpool.patch /tmp/dify-sandbox-hfs-uidpool.patch
RUN git apply --unidiff-zero /tmp/dify-sandbox-hfs-uidpool.patch \
    && go mod download \
    && case "${TARGETARCH:-amd64}" in \
         amd64) export GOARCH=amd64 ;; \
         arm64) export GOARCH=arm64 ;; \
         *) echo "Unsupported architecture: ${TARGETARCH}" && exit 1 ;; \
       esac \
    && CGO_ENABLED=1 GOOS=linux go build -o internal/core/runner/python/python.so -buildmode=c-shared -ldflags="-s -w" cmd/lib/python/main.go \
    && CGO_ENABLED=1 GOOS=linux go build -o internal/core/runner/nodejs/nodejs.so -buildmode=c-shared -ldflags="-s -w" cmd/lib/nodejs/main.go \
    && GOOS=linux go build -o main -ldflags="-s -w" cmd/server/main.go


# -----------------------------
# Final runtime image
# -----------------------------
FROM ${BASE_IMAGE_REF} AS runtime
COPY --from=api-image /tmp/api-builder.done /tmp/api-builder.done

ARG BASE_IMAGE_REF
ARG DIFY_WEB_IMAGE_REF
ARG DIFY_API_IMAGE_REF
ARG PLUGIN_DAEMON_IMAGE_REF
ARG SANDBOX_IMAGE_REF
ARG DIFY_SOURCE_REPO
ARG DIFY_SOURCE_MAIN_REF
ARG DIFY_AGENT_SOURCE_REF
ARG DIFY_SANDBOX_SOURCE_REF
ARG DIFY_VERSION
ARG UV_VERSION
ARG TARGETARCH

ENV DIFY_VERSION=${DIFY_VERSION}
ENV DIFY_AIO_BUILD_DIFY_VERSION=${DIFY_VERSION}
ENV DIFY_AIO_BUILD_UV_VERSION=${UV_VERSION}
ENV DIFY_AIO_BUILD_BASE_IMAGE_REF=${BASE_IMAGE_REF}
ENV DIFY_AIO_BUILD_DIFY_API_IMAGE_REF=${DIFY_API_IMAGE_REF}
ENV DIFY_AIO_BUILD_DIFY_WEB_IMAGE_REF=${DIFY_WEB_IMAGE_REF}
ENV DIFY_AIO_BUILD_PLUGIN_DAEMON_IMAGE_REF=${PLUGIN_DAEMON_IMAGE_REF}
ENV DIFY_AIO_BUILD_SANDBOX_IMAGE_REF=${SANDBOX_IMAGE_REF}
ENV DIFY_AIO_BUILD_DIFY_SOURCE_REPO=${DIFY_SOURCE_REPO}
ENV DIFY_AIO_BUILD_DIFY_SOURCE_MAIN_REF=${DIFY_SOURCE_MAIN_REF}
ENV DIFY_AIO_BUILD_DIFY_AGENT_SOURCE_REF=${DIFY_AGENT_SOURCE_REF}
ENV DIFY_AIO_BUILD_DIFY_SANDBOX_SOURCE_REF=${DIFY_SANDBOX_SOURCE_REF}
ENV DIFY_AIO_BUILD_DIFY_API_IMAGE=${DIFY_API_IMAGE_REF}
ENV DIFY_AIO_BUILD_DIFY_WEB_IMAGE=${DIFY_WEB_IMAGE_REF}
ENV DIFY_AIO_BUILD_PLUGIN_DAEMON_IMAGE=${PLUGIN_DAEMON_IMAGE_REF}
ENV DIFY_AIO_BUILD_SANDBOX_IMAGE=${SANDBOX_IMAGE_REF}
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV DEBIAN_FRONTEND=noninteractive
ENV FLASK_APP=app.py
ENV EDITION=SELF_HOSTED
ENV DEPLOY_ENV=PRODUCTION
ENV TZ=UTC
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8
ENV VIRTUAL_ENV=/app/api/.venv
ENV PATH="/app/api/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENV NLTK_DATA=/usr/local/share/nltk_data
ENV TIKTOKEN_CACHE_DIR=/app/api/.tiktoken_cache

# BuildKit can otherwise run the web, API, and runtime stages concurrently on
# Hugging Face. Keep the heavyweight stages ordered to reduce peak memory.

# System packages, Node.js, PostgreSQL 15 + pgvector, and runtime tools.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl gnupg lsb-release git \
       openssl tini procps netcat-openbsd tmux util-linux \
       nginx supervisor redis-server \
       libcap2-bin \
       libgmp-dev libmpfr-dev libmpc-dev \
       libseccomp2 libseccomp-dev \
       libmagic1 media-types fonts-noto-cjk \
       libldap-2.5-0 perl libsqlite3-0 zlib1g \
    && install -d -m 0755 /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key -o /tmp/nodesource.gpg \
    && gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg /tmp/nodesource.gpg \
    && rm -f /tmp/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /tmp/postgresql.asc \
    && gpg --dearmor -o /etc/apt/keyrings/postgresql.gpg /tmp/postgresql.asc \
    && rm -f /tmp/postgresql.asc \
    && echo "deb [signed-by=/etc/apt/keyrings/postgresql.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       nodejs \
       postgresql-15 postgresql-client-15 postgresql-15-pgvector \
    && npm install -g corepack@latest \
    && corepack enable \
    && if [ "${UV_VERSION}" = "latest" ]; then \
         pip install --no-cache-dir uv; \
       else \
         pip install --no-cache-dir uv==${UV_VERSION}; \
       fi \
    && python3 -m pip install --no-cache-dir \
       "httpx[socks]==0.27.2" requests==2.32.3 jinja2==3.1.6 PySocks \
    && rm -rf /var/lib/apt/lists/*

# Dedicated non-root runtime user. Hugging Face Docker Spaces run containers as UID 1000.
RUN groupadd --gid 1000 user \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash user \
    && groupadd --gid 65537 sandbox \
    && useradd --uid 65537 --gid 65537 --no-create-home --shell /usr/sbin/nologin sandbox
ENV HOME=/home/user
ENV HF_HOME=/tmp/dify-aio/hf-cache
ENV HF_HUB_CACHE=/tmp/dify-aio/hf-cache/hub

# Copy Dify API source + venv. Keep the official /app/api path because console
# script shebangs inside .venv point there.
COPY --from=api-image --chown=user:user /app/api /app/api

# NEXT Agent v2 needs the local dify-agent FastAPI run server. API/Web assets
# use a digest-pinned Docker Hub main image, then dify-agent is overlaid from
# the maintained fork main because fork merge commits have no image tag.
RUN set -eu; \
    uv pip install --python /app/api/.venv/bin/python --no-cache --no-deps \
      "dify-agent @ git+${DIFY_SOURCE_REPO}@${DIFY_AGENT_SOURCE_REF}#subdirectory=dify-agent" \
    && uv pip install --python /app/api/.venv/bin/python --no-cache \
      "fastapi==0.136.0" \
      "graphon==0.5.3" \
      "jsonschema>=4.23.0,<5.0.0" \
      "jwcrypto>=1.5.6,<2" \
      "logfire[fastapi,httpx,redis]>=4.37.0,<5.0.0" \
      "pydantic-ai-slim>=1.85.1,<2.0.0" \
      "pydantic-settings>=2.12.0,<3.0.0" \
      "redis>=7.4.0,<8.0.0" \
      "shell-session-manager==2.2.1" \
      "uvicorn[standard]==0.46.0" \
    && /app/api/.venv/bin/python -c "import dify_agent.server.app" \
    && /app/api/.venv/bin/python -c 'import inspect; from dify_agent.adapters.llm import model; assert "\"\".join(item.data for item in content)" in inspect.getsource(model._normalize_prompt_content)' \
    && /app/api/.venv/bin/shellctl --help >/dev/null \
    && if ! uv pip check --python /app/api/.venv/bin/python > /tmp/dify-agent-uv-pip-check.txt 2>&1; then \
         cat /tmp/dify-agent-uv-pip-check.txt; \
         unexpected="$(grep '^The package ' /tmp/dify-agent-uv-pip-check.txt \
           | grep -Ev '^The package `(alibabacloud-tea-openapi|clickzetta-connector-python|msal)` requires ' || true)"; \
         if [ -n "$unexpected" ]; then \
           printf '%s\n' "$unexpected"; \
           exit 1; \
         fi; \
       fi

# Download NLTK/tiktoken caches during image build, mirroring Dify's official API image behavior.
RUN mkdir -p /usr/local/share/nltk_data ${TIKTOKEN_CACHE_DIR} \
    && python -c "import nltk; nltk.download('punkt'); nltk.download('averaged_perceptron_tagger'); nltk.download('stopwords')" \
    && python -c "import tiktoken; tiktoken.encoding_for_model('gpt2')" \
    && chmod -R 755 /usr/local/share/nltk_data \
    && chown -R user:user ${TIKTOKEN_CACHE_DIR}

# Copy Dify Web standalone build in the same layout expected by Dify's official web entrypoint.
RUN mkdir -p /app
COPY --from=web-builder --chown=user:user /app/targets/ /app/targets/
COPY --from=web-builder --chown=user:user --chmod=755 /app/entrypoint.sh /app/entrypoint.sh

# Copy official Plugin Daemon and Sandbox runtime artifacts. NEXT replaces the
# sandbox server binary with a tiny source-pinned HFS UID/GID compatibility patch.
COPY --from=plugin-daemon-image --chown=user:user /app /opt/dify/plugin-daemon
COPY --from=sandbox-builder /src/main /opt/dify/sandbox/main
COPY --from=sandbox-image --chown=user:user /conf /conf
COPY --from=sandbox-image --chown=user:user /dependencies /dependencies
COPY docker/sandbox-python-requirements.txt /dependencies/python-requirements.txt

RUN /usr/local/bin/python3 -m pip install --no-cache-dir -r /dependencies/python-requirements.txt \
    && /usr/local/bin/python3 -m pip check

# Runtime scripts and config.
RUN mkdir -p /etc/dify
COPY docker/dify.env.runtime /etc/dify/dify.env.runtime
COPY docker/entrypoint.sh /usr/local/bin/dify-all-in-one-entrypoint
COPY docker/with-dify-env /usr/local/bin/with-dify-env
COPY docker/with-plugin-env /usr/local/bin/with-plugin-env
COPY docker/with-sandbox-env /usr/local/bin/with-sandbox-env
COPY docker/run-postgres /usr/local/bin/run-postgres
COPY docker/run-dify-agent /usr/local/bin/run-dify-agent
COPY docker/run-shellctl /usr/local/bin/run-shellctl
COPY docker/sandbox-selfcheck /usr/local/bin/dify-sandbox-selfcheck
COPY docker/postgres-backup-loop /usr/local/bin/postgres-backup-loop
COPY docker/ops_service.py /usr/local/bin/dify-ops-service
COPY docker/admin_service.py /usr/local/bin/dify-admin-service
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/healthcheck.sh /usr/local/bin/dify-demo-healthcheck
COPY docker/wait-for-core /usr/local/bin/wait-for-core

RUN cp "$(readlink -f /usr/local/bin/python3)" /opt/dify/sandbox/python3-sandbox \
    && chmod 755 /opt/dify/sandbox/python3-sandbox \
    && setcap cap_sys_chroot,cap_setuid,cap_setgid+ep /opt/dify/sandbox/python3-sandbox \
    && getcap /opt/dify/sandbox/python3-sandbox \
    && chmod +x \
      /usr/local/bin/dify-all-in-one-entrypoint \
      /usr/local/bin/with-dify-env \
      /usr/local/bin/with-plugin-env \
      /usr/local/bin/with-sandbox-env \
      /usr/local/bin/run-postgres \
      /usr/local/bin/run-dify-agent \
      /usr/local/bin/run-shellctl \
      /usr/local/bin/dify-sandbox-selfcheck \
      /usr/local/bin/postgres-backup-loop \
      /usr/local/bin/dify-ops-service \
      /usr/local/bin/dify-admin-service \
      /usr/local/bin/dify-demo-healthcheck \
      /usr/local/bin/wait-for-core \
      /app/api/docker/entrypoint.sh \
      /app/entrypoint.sh \
      /opt/dify/plugin-daemon/commandline \
      /opt/dify/plugin-daemon/main \
      /opt/dify/sandbox/main \
      /opt/dify/sandbox/python3-sandbox \
    && test -x /opt/dify/plugin-daemon/commandline \
    && mkdir -p \
      /data/postgres /data/redis /data/dify/storage /data/plugin_daemon /data/config /data/logs /data/run/postgresql \
      /data/run/nginx/client_body /data/run/nginx/proxy /data/run/nginx/fastcgi /data/run/nginx/uwsgi /data/run/nginx/scgi \
      /persist \
      /tmp/dify-aio/logs /tmp/dify-aio/run /tmp/dify-aio/redis /tmp/dify-aio/hf-cache /tmp/dify-aio/plugin_cwd \
      /var/sandbox/sandbox-python /var/sandbox/sandbox-nodejs \
    && chown -R user:user /data /persist /tmp/dify-aio /conf /dependencies /var/sandbox \
    && chown root:root /opt/dify/sandbox/main \
    && chmod 4755 /opt/dify/sandbox/main \
    && chmod -R 755 /var/sandbox \
    && chmod 755 /data /data/dify /data/dify/storage /data/plugin_daemon /data/logs /data/run /data/run/postgresql \
      /data/run/nginx/client_body /data/run/nginx/proxy /data/run/nginx/fastcgi /data/run/nginx/uwsgi /data/run/nginx/scgi \
    && chmod 700 /data/postgres /data/redis /data/config \
    && rm -f /etc/nginx/sites-enabled/default

USER user
WORKDIR /home/user/app

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
  CMD /usr/local/bin/dify-demo-healthcheck

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/dify-all-in-one-entrypoint"]
