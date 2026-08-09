import uvicorn

from .config import RelaySettings

if __name__ == "__main__":
    settings = RelaySettings()
    uvicorn.run(
        "discord_relay.app:app",
        host=settings.bind_host,
        port=settings.port,
        ssl_certfile=str(settings.tls_cert_file) if settings.tls_cert_file else None,
        ssl_keyfile=str(settings.tls_key_file) if settings.tls_key_file else None,
    )
