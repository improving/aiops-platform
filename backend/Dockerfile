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

# Application source
COPY api/ ./api/
COPY controller/ ./controller/
COPY db/ ./db/
COPY models/ ./models/
COPY raw_data/ ./raw_data/
COPY repositories/ ./repositories/
COPY schemas/ ./schemas/
COPY templates/ ./templates/
COPY utils/ ./utils/
COPY app.py core.py logger.py paths.py ./

# Non-root user; helm keeps its cache and config under HOME
RUN groupadd --system app && useradd --system --gid app --home-dir /app app && \
    chown -R app:app /app
USER app
ENV HOME=/app

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
