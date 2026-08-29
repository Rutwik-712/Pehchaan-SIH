from typing import Dict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.config import Settings, validate_security_settings
from app.main import app
from app.models import User

PASSWORD = "SIH1@2026"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str) -> Dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def auth_header(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_unauthenticated_case_request_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/cases")
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("username", "expected_role"),
    [
        ("constable.demo", "constable"),
        ("investigator.demo", "investigator"),
        ("sp.demo", "sp"),
    ],
)
def test_demo_accounts_login_and_report_role(
    client: TestClient, username: str, expected_role: str
) -> None:
    tokens = login(client, username)
    response = client.get(
        "/api/v1/auth/me",
        headers=auth_header(tokens["access_token"]),
    )
    assert response.status_code == 200
    assert response.json()["role"] == expected_role
    assert response.json()["username"] == username


def test_passwords_are_stored_as_argon2_hashes(client: TestClient) -> None:
    with SessionLocal() as session:
        users = session.scalars(select(User)).all()
        assert len(users) == 3
        assert all(user.password_hash.startswith("$argon2") for user in users)
        assert all(user.password_hash != PASSWORD for user in users)


def test_refresh_token_is_http_only_and_not_returned_to_javascript(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "investigator.demo", "password": PASSWORD},
    )
    assert response.status_code == 200
    assert "refresh_token" not in response.json()
    cookie = response.headers["set-cookie"]
    assert "threadline_refresh=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie


def test_constable_is_case_scoped_and_cannot_review(client: TestClient) -> None:
    tokens = login(client, "constable.demo")
    headers = auth_header(tokens["access_token"])

    cases_response = client.get("/api/v1/cases", headers=headers)
    assert cases_response.status_code == 200
    assert len(cases_response.json()) == 19
    assert "KSP-CR-2048" in {case["id"] for case in cases_response.json()}
    assert client.get("/api/v1/cases/KSP-CR-2099", headers=headers).status_code == 404
    assert client.post("/api/v1/cases/KSP-CR-2048/review-access", headers=headers).status_code == 403


def test_investigator_can_review_but_cannot_approve(client: TestClient) -> None:
    tokens = login(client, "investigator.demo")
    headers = auth_header(tokens["access_token"])

    review = client.post("/api/v1/cases/KSP-CR-2048/review-access", headers=headers)
    approve = client.post("/api/v1/cases/KSP-CR-2048/approve-access", headers=headers)
    assert review.status_code == 200
    assert review.json()["permission"] == "entity:review"
    assert approve.status_code == 403


def test_sp_can_view_all_cases_approve_and_assign(client: TestClient) -> None:
    tokens = login(client, "sp.demo")
    headers = auth_header(tokens["access_token"])

    cases_response = client.get("/api/v1/cases", headers=headers)
    assert cases_response.status_code == 200
    assert len(cases_response.json()) == 20
    assert {"KSP-CR-2048", "KSP-CR-2099"}.issubset({case["id"] for case in cases_response.json()})

    approve = client.post("/api/v1/cases/KSP-CR-2048/approve-access", headers=headers)
    assignment = client.post(
        "/api/v1/cases/KSP-CR-2048/assignments",
        headers=headers,
        json={"username": "constable.demo"},
    )
    assert approve.status_code == 200
    assert approve.json()["permission"] == "brief:approve"
    assert assignment.status_code == 200
    assert assignment.json()["username"] == "constable.demo"


def test_refresh_tokens_rotate_and_logout_revokes_session(client: TestClient) -> None:
    login(client, "investigator.demo")
    original_refresh = client.cookies.get("threadline_refresh")
    assert original_refresh
    rotated_response = client.post("/api/v1/auth/refresh")
    assert rotated_response.status_code == 200
    rotated_refresh = client.cookies.get("threadline_refresh")
    assert rotated_refresh and rotated_refresh != original_refresh

    client.cookies.clear()
    client.cookies.set(
        "threadline_refresh", original_refresh, domain="testserver.local", path="/api/v1/auth"
    )
    reused = client.post("/api/v1/auth/refresh")
    assert reused.status_code == 401

    client.cookies.clear()
    client.cookies.set(
        "threadline_refresh", rotated_refresh, domain="testserver.local", path="/api/v1/auth"
    )
    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    client.cookies.clear()
    client.cookies.set(
        "threadline_refresh", rotated_refresh, domain="testserver.local", path="/api/v1/auth"
    )
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_wrong_password_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "investigator.demo", "password": "incorrect-password"},
    )
    assert response.status_code == 401


def test_production_rejects_default_jwt_secret() -> None:
    settings = Settings(
        app_name="test",
        app_env="production",
        app_debug=False,
        api_v1_prefix="/api/v1",
        frontend_origin="http://localhost",
        build_version="test",
        database_url="sqlite://",
        jwt_secret="phase2-local-only-change-before-shared-deployment-2026",
        access_token_minutes=30,
        refresh_token_days=7,
        demo_account_password=PASSWORD,
        seed_demo_data=False,
        object_storage_backend="local",
        local_object_root="./data/test-objects",
        max_upload_bytes=1024,
        minio_endpoint="127.0.0.1:9000",
        minio_access_key="test",
        minio_secret_key="test-secret",
        minio_bucket="test",
        minio_secure=False,
    )
    with pytest.raises(RuntimeError, match="non-default JWT_SECRET"):
        validate_security_settings(settings)
