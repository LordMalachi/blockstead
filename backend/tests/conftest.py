from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from blockstead.app import create_app
from blockstead.config import Settings


class PublicIpDiscoveryStub:
    async def discover(self, *, force: bool = False) -> dict[str, object]:
        return {
            "available": False,
            "ip": None,
            "detail": (
                "Blockstead could not detect this network's public IP. "
                "No public Minecraft address is being shown."
            ),
        }


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    fixture_root = Path(__file__).parents[2] / "fixtures" / "servers"
    settings = Settings(
        data_dir=tmp_path / "data", server_root=fixture_root, allowed_origins="http://testserver"
    )
    with TestClient(create_app(settings)) as test_client:
        # Overview requests must not make a real network call during tests.
        test_client.app.state.public_ip_discovery = PublicIpDiscoveryStub()
        yield test_client


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/setup/admin",
        headers={"Origin": "http://testserver"},
        json={"username": "owner", "password": "correct horse battery staple"},
    )
    assert response.status_code == 201
    return {"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]}
