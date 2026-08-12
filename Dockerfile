# syntax=docker/dockerfile:1.7
#
# Dify all-in-one artifact consumer for Hugging Face Docker Spaces.
# Product runtime files are deliberately absent from this build context and are
# installed once at startup from a manifest-selected, immutable artifact.

ARG BASE_IMAGE_REF=python:3.12-slim-bookworm
ARG UV_VERSION=0.11.21

# The sandbox server needs a root-owned setuid boundary, but the downloaded
# runtime artifact is installed by UID 1000. Compile only the fixed launcher at
# image build time; it execs the manifest-verified sandbox binary.
FROM ${BASE_IMAGE_REF} AS sandbox-launcher-builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY docker/sandbox-artifact-launcher.c /src/sandbox-artifact-launcher.c
RUN gcc -O2 -Wall -Wextra -Werror -o /sandbox-artifact-launcher /src/sandbox-artifact-launcher.c

FROM ${BASE_IMAGE_REF} AS runtime

ARG BASE_IMAGE_REF
ARG UV_VERSION

ENV DIFY_AIO_BUILD_BASE_IMAGE_REF=${BASE_IMAGE_REF} \
    DIFY_AIO_BUILD_UV_VERSION=${UV_VERSION} \
    DIFY_AIO_RUNTIME_DELIVERY=manifest-first-artifact \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    DEPLOYMENT_EDITION=COMMUNITY \
    DEPLOY_ENV=PRODUCTION \
    TZ=UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    NLTK_DATA=/opt/dify/runtime/usr/local/share/nltk_data \
    HOME=/home/user \
    HF_HOME=/tmp/dify-aio/hf-cache \
    HF_HUB_CACHE=/tmp/dify-aio/hf-cache/hub

# Base infrastructure remains image-built. Dify API/Web/Agent/Plugin/Sandbox
# application payloads are exclusively supplied by the runtime artifact.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates curl gnupg lsb-release \
       openssl tini procps netcat-openbsd tmux util-linux \
       nginx supervisor redis-server \
       libcap2-bin \
       libseccomp2 \
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

# The Sandbox discovers the host Python installation before it creates the
# restricted execution root. Preinstall the approved dependency set so it can
# copy a complete, immutable environment instead of repeatedly attempting a
# large runtime install inside the Space sandbox.
COPY docker/sandbox-python-requirements.txt /dependencies/python-requirements.txt
RUN python3 -m pip install --no-cache-dir -r /dependencies/python-requirements.txt \
    && python3 -m pip check

# Hugging Face Docker Spaces execute as UID 1000. All ordinary runtime code and
# state remain rootless; only the fixed sandbox launcher retains setuid root.
RUN groupadd --gid 1000 user \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash user \
    && groupadd --gid 65537 sandbox \
    && useradd --uid 65537 --gid 65537 --no-create-home --shell /usr/sbin/nologin sandbox \
    && mkdir -p \
      /data/postgres /data/redis /data/dify/storage /data/plugin_daemon /data/config /data/logs /data/run/postgresql \
      /data/run/nginx/client_body /data/run/nginx/proxy /data/run/nginx/fastcgi /data/run/nginx/uwsgi /data/run/nginx/scgi \
      /persist \
      /tmp/dify-aio/logs /tmp/dify-aio/run /tmp/dify-aio/redis /tmp/dify-aio/hf-cache /tmp/dify-aio/plugin_cwd \
      /var/sandbox/sandbox-python /var/sandbox/sandbox-nodejs \
      /conf /dependencies /opt/dify/sandbox /opt/dify \
    && ln -s /opt/dify/runtime/app /app \
    && ln -s /opt/dify/runtime/opt/dify/plugin-daemon /opt/dify/plugin-daemon \
    && ln -s /opt/dify/runtime/opt/dify-agent /opt/dify-agent \
    && ln -s /opt/dify/runtime/usr/local/bin/dify-agent /usr/local/bin/dify-agent \
    && ln -s /opt/dify/runtime/usr/local/bin/shellctl /usr/local/bin/shellctl \
    && ln -s /opt/dify/runtime/usr/local/bin/shellctl-runner /usr/local/bin/shellctl-runner \
    && ln -s /opt/dify/runtime/usr/local/bin/shellctl-runner-exit /usr/local/bin/shellctl-runner-exit \
    && ln -s /opt/dify/runtime/usr/local/bin/shellctl-sanitize-pty /usr/local/bin/shellctl-sanitize-pty \
    && chown -R user:user /home/user /data /persist /tmp/dify-aio /conf /dependencies /var/sandbox /opt/dify \
    && chmod 700 /data/postgres /data/redis /data/config \
    && chmod 755 /data /data/dify /data/dify/storage /data/plugin_daemon /data/logs /data/run /data/run/postgresql \
      /data/run/nginx/client_body /data/run/nginx/proxy /data/run/nginx/fastcgi /data/run/nginx/uwsgi /data/run/nginx/scgi \
    && rm -f /etc/nginx/sites-enabled/default

# Runtime glue and artifact verifier only. No Dify product source, OCI runtime
# image contents, build caches, generated data, or local environment ledger is
# copied into the consumer image.
RUN mkdir -p /etc/dify /usr/local/lib
COPY docker/dify.env.runtime /etc/dify/dify.env.runtime
COPY docker/entrypoint.sh /usr/local/bin/dify-all-in-one-entrypoint
COPY docker/dify-artifact-bootstrap /usr/local/bin/dify-artifact-bootstrap
COPY docker/dify_artifact_contract.py /usr/local/lib/dify_artifact_contract.py
COPY docker/with-dify-env /usr/local/bin/with-dify-env
COPY docker/with-plugin-env /usr/local/bin/with-plugin-env
COPY docker/plugin_runtime_patches /opt/dify/plugin-runtime-patches
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
COPY --from=sandbox-launcher-builder /sandbox-artifact-launcher /opt/dify/sandbox/main

RUN cp "$(readlink -f /usr/local/bin/python3)" /opt/dify/sandbox/python3-sandbox \
    && chmod 755 /opt/dify/sandbox/python3-sandbox \
    && setcap cap_sys_chroot,cap_setuid,cap_setgid+ep /opt/dify/sandbox/python3-sandbox \
    && getcap /opt/dify/sandbox/python3-sandbox \
    && chown root:root /opt/dify/sandbox/main \
    && chmod 4755 /opt/dify/sandbox/main \
    && chmod +x \
      /usr/local/bin/dify-all-in-one-entrypoint \
      /usr/local/bin/dify-artifact-bootstrap \
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
      /usr/local/lib/dify_artifact_contract.py \
    && chmod -R 755 /var/sandbox

USER user
WORKDIR /home/user/app

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
  CMD /usr/local/bin/dify-demo-healthcheck

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/dify-all-in-one-entrypoint"]
