"""Live Phase 2 authentication/RBAC smoke test. Prints no tokens or password data."""

import json

import httpx

BASE_URL = "http://127.0.0.1:18000/api/v1"
PASSWORD = "SIH1@2026"


def sign_in(client: httpx.Client, username: str) -> dict:
    response = client.post(
        f"{BASE_URL}/auth/login",
        json={"username": username, "password": PASSWORD},
    )
    response.raise_for_status()
    assert client.cookies.get("threadline_refresh")
    return response.json()


def headers(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def main() -> None:
    summary = {}
    with httpx.Client(timeout=10) as client:
        unauthenticated = client.get(f"{BASE_URL}/cases")
        assert unauthenticated.status_code == 401

        for username in ("constable.demo", "investigator.demo", "sp.demo"):
            tokens = sign_in(client, username)
            auth = headers(tokens)
            me = client.get(f"{BASE_URL}/auth/me", headers=auth)
            cases = client.get(f"{BASE_URL}/cases", headers=auth)
            review = client.post(f"{BASE_URL}/cases/KSP-CR-2048/review-access", headers=auth)
            approve = client.post(f"{BASE_URL}/cases/KSP-CR-2048/approve-access", headers=auth)
            assert me.status_code == 200
            assert cases.status_code == 200
            summary[username] = {
                "role": me.json()["role"],
                "case_count": len(cases.json()),
                "review_status": review.status_code,
                "approve_status": approve.status_code,
            }

        assert summary["constable.demo"] == {
            "role": "constable",
            "case_count": 1,
            "review_status": 403,
            "approve_status": 403,
        }
        assert summary["investigator.demo"] == {
            "role": "investigator",
            "case_count": 1,
            "review_status": 200,
            "approve_status": 403,
        }
        assert summary["sp.demo"] == {
            "role": "sp",
            "case_count": 2,
            "review_status": 200,
            "approve_status": 200,
        }

    print(json.dumps({"unauthenticated_status": 401, "accounts": summary}, indent=2))


if __name__ == "__main__":
    main()
