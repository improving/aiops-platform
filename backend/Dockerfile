FROM python:3.13-slim

ARG TARGETARCH
ARG HELM_VERSION=4.2.4

# uv binary from the official image
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

# Helm binary with checksum verification
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    curl -fsSLO "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${TARGETARCH}.tar.gz" && \
    curl -fsSLO "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${TARGETARCH}.tar.gz.sha256sum" && \
    sha256sum -c "helm-v${HELM_VERSION}-linux-${TARGETARCH}.tar.gz.sha256sum" && \
    tar -xzf "helm-v${HELM_VERSION}-linux-${TARGETARCH}.tar.gz" && \
    install -m 0755 "linux-${TARGETARCH}/helm" /usr/local/bin/helm && \
    rm -rf "linux-${TARGETARCH}" helm-v* && \
    apt-get purge -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so the layer is cached across source changes
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application source: every package core.py imports (api, auth, controller,
# db, models, registry, utils, and whatever a later stream adds), the
# Alembic migrations and alembic.ini that db/migrate.py runs at startup,
# and the seed data. .dockerignore keeps tests, snapshots, tmp and the
# virtualenv out of the context.
COPY . .

# Non-root user; helm keeps its cache and config under HOME. Fixed uid/gid
# so the chart's securityContext can set runAsNonRoot/runAsUser without
# relying on the image's own idea of the account.
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --home-dir /app app && \
    chown -R app:app /app
USER 10001
ENV HOME=/app

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
