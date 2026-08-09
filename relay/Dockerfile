FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/relay/.venv/bin:$PATH

WORKDIR /opt/relay
COPY pyproject.toml ./
COPY src/ ./src/
RUN python -m venv .venv \
    && .venv/bin/pip install --no-cache-dir .

RUN useradd --system --uid 10001 --home-dir /opt/relay --shell /usr/sbin/nologin relay \
    && mkdir -p /var/lib/blockstead-relay \
    && chown -R relay:relay /opt/relay /var/lib/blockstead-relay

USER relay:relay
ENV RELAY_DATABASE_PATH=/var/lib/blockstead-relay/relay.db
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, ssl, urllib.request; u=('https' if os.getenv('RELAY_TLS_CERT_FILE') else 'http') + '://127.0.0.1:8080/healthz'; c=ssl._create_unverified_context() if u.startswith('https') else None; urllib.request.urlopen(u, context=c, timeout=3).read()"

CMD ["python", "-m", "discord_relay"]
