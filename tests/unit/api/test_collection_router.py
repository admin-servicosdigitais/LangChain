from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from value_betting_api.main import app

_SECRET = "dev-secret"
_ALGORITHM = "HS256"


def _admin_token(role: str = "ops") -> str:
    payload = {
        "sub": "admin_001",
        "role": role,
        "exp": datetime.now(UTC) + timedelta(hours=4),
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {_admin_token()}"}


@pytest.fixture
def elite_headers():
    return {"X-API-Key": "vb_elite_abcdef1234567890abcdef1234567890"}


class TestLeagueEndpoints:
    @patch("value_betting_api.routers.collection._get_table")
    def test_list_leagues(self, mock_table, client, admin_headers):
        table = MagicMock()
        table.scan.return_value = {
            "Items": [
                {"league_id": "premier_league", "sport": "football", "active": True}
            ]
        }
        mock_table.return_value = table

        resp = client.get("/api/v1/admin/collection/leagues", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1

    @patch("value_betting_api.routers.collection._get_table")
    def test_create_league(self, mock_table, client, admin_headers):
        table = MagicMock()
        table.get_item.return_value = {}
        mock_table.return_value = table

        resp = client.post(
            "/api/v1/admin/collection/leagues",
            headers=admin_headers,
            json={
                "league_id": "serie_a",
                "name": "Serie A",
                "sport": "football",
                "country": "IT",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["data"]["league_id"] == "serie_a"

    @patch("value_betting_api.routers.collection._get_table")
    def test_create_league_conflict(self, mock_table, client, admin_headers):
        table = MagicMock()
        table.get_item.return_value = {"Item": {"league_id": "serie_a"}}
        mock_table.return_value = table

        resp = client.post(
            "/api/v1/admin/collection/leagues",
            headers=admin_headers,
            json={
                "league_id": "serie_a",
                "name": "Serie A",
                "sport": "football",
                "country": "IT",
            },
        )
        assert resp.status_code == 409

    def test_unauthorized_without_token(self, client):
        resp = client.get("/api/v1/admin/collection/leagues")
        assert resp.status_code == 422

    def test_forbidden_with_bad_role(self, client):
        token = jwt.encode(
            {"sub": "user_1", "role": "viewer", "exp": datetime.now(UTC) + timedelta(hours=1)},
            _SECRET,
            algorithm=_ALGORITHM,
        )
        resp = client.get(
            "/api/v1/admin/collection/leagues",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


class TestEliteSnapshots:
    @patch("value_betting_api.routers.collection._get_table")
    def test_list_snapshots_requires_filter(self, mock_table, client, elite_headers):
        resp = client.get(
            "/api/v1/elite/snapshots",
            headers=elite_headers,
        )
        assert resp.status_code == 400

    @patch("value_betting_api.routers.collection._get_table")
    def test_list_snapshots_by_event(self, mock_table, client, elite_headers):
        table = MagicMock()
        table.query.return_value = {
            "Items": [{"event_id": "match_001", "odds_home": 2.10}],
        }
        mock_table.return_value = table

        resp = client.get(
            "/api/v1/elite/snapshots?eventId=match_001",
            headers=elite_headers,
        )
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 1

    def test_invalid_api_key_rejected(self, client):
        resp = client.get(
            "/api/v1/elite/snapshots?eventId=x",
            headers={"X-API-Key": "invalid_key"},
        )
        assert resp.status_code == 401


class TestDegradation:
    @patch("value_betting_api.routers.collection._get_table")
    def test_activate_degraded_mode(self, mock_table, client, admin_headers):
        table = MagicMock()
        table.get_item.return_value = {"Item": {"active": True, "reason": "test"}}
        mock_table.return_value = table

        resp = client.post(
            "/api/v1/admin/collection/degradation/activate",
            headers=admin_headers,
            json={"reason": "Investigando instabilidade The Odds API"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["active"] is True
