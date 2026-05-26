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
#     -v dify-hf-demo-persist:/persist \
#     --env-file docker/dify.env.demo \
#     dify-all-in-one-hf-space:1.14.1

ARG DIFY_VERSION=1.14.1
ARG UV_VERSION=0.8.9
ARG DIFY_API_IMAGE=langgenius/dify-api
ARG DIFY_WEB_IMAGE=langgenius/dify-web
ARG PLUGIN_DAEMON_IMAGE=langgenius/dify-plugin-daemon:0.6.0-local
ARG SANDBOX_IMAGE=langgenius/dify-sandbox:0.2.15

# -----------------------------
# Use official prebuilt Dify Web assets
# -----------------------------
FROM ${DIFY_WEB_IMAGE}:${DIFY_VERSION} AS web-builder
RUN test -d /app/targets/next \
    && test -d /app/targets/vinext \
    && test -x /app/entrypoint.sh
RUN touch /tmp/web-builder.done


# -----------------------------
# Use official prebuilt Dify API source and virtualenv
# -----------------------------
FROM ${DIFY_API_IMAGE}:${DIFY_VERSION} AS api-image
COPY --from=web-builder /tmp/web-builder.done /tmp/web-builder.done
RUN test -d /app/api/.venv \
    && test -x /app/api/.venv/bin/flask \
    && test -x /app/api/docker/entrypoint.sh
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
COPY --from=api-image /tmp/api-builder.done /tmp/api-builder.done

ARG DIFY_VERSION
ARG UV_VERSION
ARG TARGETARCH
ARG DIFY_API_IMAGE
ARG DIFY_WEB_IMAGE
ARG PLUGIN_DAEMON_IMAGE
ARG SANDBOX_IMAGE

ENV DIFY_VERSION=${DIFY_VERSION}
ENV DIFY_AIO_BUILD_DIFY_VERSION=${DIFY_VERSION}
ENV DIFY_AIO_BUILD_UV_VERSION=${UV_VERSION}
ENV DIFY_AIO_BUILD_DIFY_API_IMAGE=${DIFY_API_IMAGE}
ENV DIFY_AIO_BUILD_DIFY_WEB_IMAGE=${DIFY_WEB_IMAGE}
ENV DIFY_AIO_BUILD_PLUGIN_DAEMON_IMAGE=${PLUGIN_DAEMON_IMAGE}
ENV DIFY_AIO_BUILD_SANDBOX_IMAGE=${SANDBOX_IMAGE}
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
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash user \
    && groupadd --gid 65537 sandbox \
    && useradd --uid 65537 --gid 65537 --no-create-home --shell /usr/sbin/nologin sandbox
ENV HOME=/home/user
ENV HF_HOME=/tmp/dify-aio/hf-cache
ENV HF_HUB_CACHE=/tmp/dify-aio/hf-cache/hub

# Copy Dify API source + venv. Keep the official /app/api path because console
# script shebangs inside .venv point there.
COPY --from=api-image --chown=user:user /app/api /app/api

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

# Copy official Plugin Daemon and Sandbox runtime artifacts.
COPY --from=plugin-daemon-image --chown=user:user /app /opt/dify/plugin-daemon
COPY --from=sandbox-image /main /opt/dify/sandbox/main
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
COPY docker/postgres-backup-loop /usr/local/bin/postgres-backup-loop
COPY docker/ops_service.py /usr/local/bin/dify-ops-service
COPY docker/admin_service.py /usr/local/bin/dify-admin-service
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY docker/healthcheck.sh /usr/local/bin/dify-demo-healthcheck
COPY docker/wait-for-core /usr/local/bin/wait-for-core

RUN chmod +x \
      /usr/local/bin/dify-all-in-one-entrypoint \
      /usr/local/bin/with-dify-env \
      /usr/local/bin/with-plugin-env \
      /usr/local/bin/with-sandbox-env \
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
    && chmod -R 777 /data \
    && rm -f /etc/nginx/sites-enabled/default

USER user
WORKDIR /home/user/app

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
  CMD /usr/local/bin/dify-demo-healthcheck

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/dify-all-in-one-entrypoint"]
