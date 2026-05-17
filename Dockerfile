# syntax=docker/dockerfile:1.7
#
# Dify all-in-one demo image
# Target: Hugging Face Docker Space training / demo / PoC, not production.
# Runtime is intentionally rootless to match HF Spaces UID 1000 expectations.
#
# Build example:
#   docker build -t dify-all-in-one-hf-space:1.14.1 .
#
# Run example:
#   docker run --rm -it \
#     -p 8080:7860 \
#     -v dify-hf-demo-data:/data \
#     --env-file docker/dify.env.demo \
#     dify-all-in-one-hf-space:1.14.1

ARG DIFY_VERSION=1.14.1
ARG NODE_VERSION=22
ARG UV_VERSION=0.8.9
ARG PLUGIN_DAEMON_IMAGE=langgenius/dify-plugin-daemon:0.6.0-local
ARG SANDBOX_IMAGE=langgenius/dify-sandbox:0.2.15

# -----------------------------
# Build Dify Web from source
# -----------------------------
FROM node:${NODE_VERSION}-bookworm AS web-builder
ARG DIFY_VERSION

ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_OPTIONS="--max-old-space-size=4096"
ENV pnpm_config_verify_deps_before_run=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --depth 1 --branch ${DIFY_VERSION} https://github.com/langgenius/dify.git .

RUN corepack enable && corepack install
RUN VITE_GIT_HOOKS=0 pnpm install --frozen-lockfile

WORKDIR /src/web
RUN pnpm build && pnpm build:vinext
RUN touch /tmp/web-builder.done


# -----------------------------
# Build Dify API virtualenv from source
# -----------------------------
FROM python:3.12-slim-bookworm AS api-builder
COPY --from=web-builder /tmp/web-builder.done /tmp/web-builder.done
ARG DIFY_VERSION
ARG UV_VERSION

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git ca-certificates curl \
       g++ build-essential pkg-config \
       libmpfr-dev libmpc-dev libgmp-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==${UV_VERSION}

WORKDIR /src
RUN git clone --depth 1 --branch ${DIFY_VERSION} https://github.com/langgenius/dify.git .

WORKDIR /src/api
RUN uv sync --locked --no-dev
RUN touch /tmp/api-builder.done


# -----------------------------
# External official runtime assets
# -----------------------------
FROM ${PLUGIN_DAEMON_IMAGE} AS plugin-daemon-image
FROM ${SANDBOX_IMAGE} AS sandbox-image


# -----------------------------
# Final runtime image
# -----------------------------
FROM python:3.12-slim-bookworm AS runtime
COPY --from=api-builder /tmp/api-builder.done /tmp/api-builder.done

ARG DIFY_VERSION
ARG UV_VERSION

ENV DIFY_VERSION=${DIFY_VERSION}
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
ENV VIRTUAL_ENV=/opt/dify/api/.venv
ENV PATH="/opt/dify/api/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ENV NLTK_DATA=/usr/local/share/nltk_data
ENV TIKTOKEN_CACHE_DIR=/opt/dify/api/.tiktoken_cache

# BuildKit can otherwise run the web, API, and runtime stages concurrently on
# Hugging Face. Keep the heavyweight stages ordered to reduce peak memory.

# System packages, Node.js, PostgreSQL 15 + pgvector, and runtime tools.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl gnupg lsb-release git \
       openssl tini procps netcat-openbsd \
       nginx supervisor redis-server \
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
    && pip install --no-cache-dir uv==${UV_VERSION} \
    && python3 -m pip install --no-cache-dir \
       "httpx[socks]==0.27.2" requests==2.32.3 jinja2==3.1.6 PySocks \
    && rm -rf /var/lib/apt/lists/*

# Dedicated non-root runtime user. Hugging Face Docker Spaces run containers as UID 1000.
RUN groupadd --gid 1000 user \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash user
ENV HOME=/home/user
ENV HF_HOME=/data/.huggingface
ENV HF_HUB_CACHE=/data/.huggingface/hub

# Copy Dify API source + venv.
COPY --from=api-builder --chown=user:user /src/api /opt/dify/api

# Download NLTK/tiktoken caches during image build, mirroring Dify's official API image behavior.
RUN mkdir -p /usr/local/share/nltk_data ${TIKTOKEN_CACHE_DIR} \
    && python -c "import nltk; nltk.download('punkt'); nltk.download('averaged_perceptron_tagger'); nltk.download('stopwords')" \
    && python -c "import tiktoken; tiktoken.encoding_for_model('gpt2')" \
    && chmod -R 755 /usr/local/share/nltk_data \
    && chown -R user:user ${TIKTOKEN_CACHE_DIR}

# Copy Dify Web standalone build in the same layout expected by Dify's official web entrypoint.
RUN mkdir -p /app/targets/next/web /app/targets/vinext
COPY --from=web-builder --chown=user:user /src/web/public /app/targets/next/web/public
COPY --from=web-builder --chown=user:user /src/web/.next/standalone /app/targets/next/
COPY --from=web-builder --chown=user:user /src/web/.next/static /app/targets/next/web/.next/static
COPY --from=web-builder --chown=user:user /src/web/dist/standalone /app/targets/vinext
COPY --from=web-builder --chown=user:user --chmod=755 /src/web/docker/entrypoint.sh /app/entrypoint.sh

# Copy official Plugin Daemon and Sandbox runtime artifacts.
COPY --from=plugin-daemon-image --chown=user:user /app /opt/dify/plugin-daemon
COPY --from=sandbox-image --chown=user:user /main /opt/dify/sandbox/main
COPY --from=sandbox-image --chown=user:user /conf /conf
COPY --from=sandbox-image --chown=user:user /dependencies /dependencies

# Runtime scripts and config.
RUN mkdir -p /etc/dify
COPY docker/dify.env.runtime /etc/dify/dify.env.runtime
COPY docker/entrypoint.sh /usr/local/bin/dify-all-in-one-entrypoint
COPY docker/with-dify-env /usr/local/bin/with-dify-env
COPY docker/with-plugin-env /usr/local/bin/with-plugin-env
COPY docker/with-sandbox-env /usr/local/bin/with-sandbox-env
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/healthcheck.sh /usr/local/bin/dify-demo-healthcheck
COPY docker/wait-for-core /usr/local/bin/wait-for-core

RUN chmod +x \
      /usr/local/bin/dify-all-in-one-entrypoint \
      /usr/local/bin/with-dify-env \
      /usr/local/bin/with-plugin-env \
      /usr/local/bin/with-sandbox-env \
      /usr/local/bin/dify-demo-healthcheck \
      /usr/local/bin/wait-for-core \
      /opt/dify/api/docker/entrypoint.sh \
      /app/entrypoint.sh \
      /opt/dify/plugin-daemon/main \
      /opt/dify/sandbox/main \
    && mkdir -p \
      /data/postgres /data/redis /data/dify/storage /data/plugin_daemon /data/config /data/logs /data/run/postgresql \
      /data/run/nginx/client_body /data/run/nginx/proxy /data/run/nginx/fastcgi /data/run/nginx/uwsgi /data/run/nginx/scgi \
      /var/sandbox \
    && chown -R user:user /opt/dify /app /data /conf /dependencies /var/sandbox \
    && chmod -R 777 /data \
    && rm -f /etc/nginx/sites-enabled/default

USER user
WORKDIR /home/user/app

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
  CMD /usr/local/bin/dify-demo-healthcheck

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/dify-all-in-one-entrypoint"]
