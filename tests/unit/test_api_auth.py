from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_fyers_client, get_runtime_manager
from src.api.routes import auth as auth_routes
from src.api.routes.auth import _extract_auth_code


class DummyFyersClient:
    def __init__(self) -> None:
        self.auth_codes: list[str] = []

    def authenticate(self, auth_code: str) -> None:
        self.auth_codes.append(auth_code)


class DummyRuntimeManager:
    async def restart_if_authenticated(self) -> None:
        return None


def _build_client() -> tuple[TestClient, DummyFyersClient]:
    application = FastAPI()
    application.include_router(auth_routes.router, prefix="/api/v1")

    fyers_client = DummyFyersClient()
    runtime_manager = DummyRuntimeManager()

    application.dependency_overrides[get_fyers_client] = lambda: fyers_client
    application.dependency_overrides[get_runtime_manager] = lambda: runtime_manager

    return TestClient(application, raise_server_exceptions=False), fyers_client


class TestManualAuthCodeParsing:
    def test_extract_auth_code_preserves_literal_plus(self) -> None:
        raw_url = "https://example.com/callback?auth_code=abc+def%2Bghi"

        assert _extract_auth_code(raw_url) == "abc+def+ghi"

    def test_manual_code_endpoint_preserves_plus_from_full_url(self) -> None:
        client, fyers_client = _build_client()

        response = client.post(
            "/api/v1/auth/manual-code",
            json={"auth_code": "https://example.com/callback?auth_code=abc+def%2Bghi"},
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert fyers_client.auth_codes == ["abc+def+ghi"]

    def test_manual_code_endpoint_repairs_space_corrupted_code(self) -> None:
        client, fyers_client = _build_client()

        response = client.post(
            "/api/v1/auth/manual-code",
            json={"auth_code": "abc def+ghi"},
        )

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert fyers_client.auth_codes == ["abc+def+ghi"]
