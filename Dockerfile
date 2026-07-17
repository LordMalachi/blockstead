# syntax=docker/dockerfile:1

FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM eclipse-temurin:21-jre-noble AS runtime

ARG BLOCKSTEAD_UID=10001
ARG BLOCKSTEAD_GID=10001

ENV BLOCKSTEAD_BIND_HOST=0.0.0.0 \
    BLOCKSTEAD_PORT=8765 \
    BLOCKSTEAD_DATA_DIR=/var/lib/blockstead \
    BLOCKSTEAD_SERVER_ROOT=/srv/minecraft \
    BLOCKSTEAD_STATIC_DIR=/opt/blockstead/frontend/dist \
    BLOCKSTEAD_SECURE_COOKIES=false \
    BLOCKSTEAD_ALLOWED_ORIGINS=http://127.0.0.1:8765,http://localhost:8765 \
    PATH=/opt/blockstead/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        python3.12 \
        python3.12-venv \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${BLOCKSTEAD_GID}" blockstead \
    && useradd --uid "${BLOCKSTEAD_UID}" --gid blockstead --home-dir /var/lib/blockstead \
        --shell /usr/sbin/nologin blockstead

WORKDIR /opt/blockstead

COPY backend/ ./backend/
RUN python3.12 -m venv .venv \
    && .venv/bin/pip install --no-cache-dir ./backend

COPY --from=frontend-builder /build/frontend/dist ./frontend/dist
COPY docker/docker-entrypoint.sh ./docker/docker-entrypoint.sh

RUN mkdir -p /var/lib/blockstead /srv/minecraft \
    && chown -R blockstead:blockstead /var/lib/blockstead /srv/minecraft

USER blockstead:blockstead

EXPOSE 8765 25565

VOLUME ["/var/lib/blockstead", "/srv/minecraft"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; port = os.environ.get('BLOCKSTEAD_PORT', '8765'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=3).read()"]

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/blockstead/docker/docker-entrypoint.sh"]
