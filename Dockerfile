# SPDX-License-Identifier: Apache-2.0
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.12.12-slim-bookworm AS development
COPY --from=uv /uv /usr/local/bin/uv
RUN --mount=type=secret,id=ca,required=false,mode=0444 set -eu; \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    if [ -f /run/secrets/ca ]; then printf 'Acquire::https::CaInfo "/run/secrets/ca";\n' > /etc/apt/apt.conf.d/99-build-ca; fi; \
    if [ -n "${HTTPS_PROXY:-}" ]; then printf 'Acquire::https::Proxy "%s";\n' "$HTTPS_PROXY" > /etc/apt/apt.conf.d/98-build-proxy; fi; \
    apt-get update; apt-get install -y --no-install-recommends chromium ca-certificates curl git; \
    rm -f /etc/apt/apt.conf.d/99-build-ca /etc/apt/apt.conf.d/98-build-proxy; rm -rf /var/lib/apt/lists/*
ARG TASK_VERSION=3.54.0
RUN --mount=type=secret,id=ca,required=false,mode=0444 set -eu; \
    if [ -f /run/secrets/ca ]; then export CURL_CA_BUNDLE=/run/secrets/ca; fi; \
    arch="$(dpkg --print-architecture)"; mkdir /tmp/task; cd /tmp/task; \
    curl -fsSLO "https://github.com/go-task/task/releases/download/v${TASK_VERSION}/task_linux_${arch}.tar.gz"; \
    curl -fsSLO "https://github.com/go-task/task/releases/download/v${TASK_VERSION}/task_checksums.txt"; \
    sha256sum --ignore-missing -c task_checksums.txt; \
    tar -xzf "task_linux_${arch}.tar.gz" task; install task /usr/local/bin/task; rm -rf /tmp/task
ENV UV_PROJECT_ENVIRONMENT=/opt/docs-venv UV_CACHE_DIR=/tmp/uv-cache CHROMIUM_PATH=/usr/bin/chromium
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=ca,required=false,mode=0444 set -eu; \
    if [ -f /run/secrets/ca ]; then export SSL_CERT_FILE=/run/secrets/ca; fi; \
    uv sync --locked --no-python-downloads && chmod -R a+rX /opt/docs-venv && rm -rf /tmp/uv-cache
ENV PATH="/opt/docs-venv/bin:${PATH}" XDG_CONFIG_HOME=/tmp/docs-config XDG_CACHE_HOME=/tmp/docs-cache
CMD ["task", "verify"]
