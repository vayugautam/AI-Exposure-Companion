from fastapi.testclient import TestClient
from httpx import Response

from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def mobile_payload() -> dict[str, object]:
    return {
        "user": {"user_id": "demo-user-001", "name": "Demo User"},
        "places": [
            {
                "name": "Home",
                "latitude": 26.4499,
                "longitude": 80.3319,
                "duration_minutes": 720,
            }
        ],
    }


def test_mobile_exposure_endpoint_returns_clearly_labelled_mock() -> None:
    response = client.post("/api/v1/exposure", json=mobile_payload())

    assert response.status_code == 200
    assert response.json() == {
        "status": "mock",
        "mock": True,
        "user_id": "demo-user-001",
        "places_received": 1,
        "total_requested_duration_minutes": 720,
        "message": (
            "Mock response only: no air-quality provider was queried and no exposure "
            "estimate was calculated."
        ),
        "warnings": [
            "PM2.5 readings, coverage, and exposure estimates are not available yet."
        ],
    }


def test_mobile_exposure_rejects_missing_required_fields() -> None:
    response = client.post("/api/v1/exposure", json={"user": {"user_id": "user-1"}})

    assert_validation_error(response, "places")

    response = client.post("/api/v1/exposure", json={"places": mobile_payload()["places"]})

    assert_validation_error(response, "user")


def test_mobile_exposure_rejects_invalid_coordinates() -> None:
    payload = mobile_payload()
    payload["places"][0]["latitude"] = 90.1  # type: ignore[index]
    response = client.post("/api/v1/exposure", json=payload)

    assert_validation_error(response, "places", 0, "latitude")


def test_mobile_exposure_rejects_non_positive_duration() -> None:
    payload = mobile_payload()
    payload["places"][0]["duration_minutes"] = 0  # type: ignore[index]
    response = client.post("/api/v1/exposure", json=payload)

    assert_validation_error(response, "places", 0, "duration_minutes")


def test_mobile_exposure_rejects_empty_places_list() -> None:
    response = client.post(
        "/api/v1/exposure", json={"user": {"user_id": "user-1"}, "places": []}
    )

    assert_validation_error(response, "places")


def test_mobile_exposure_rejects_request_larger_than_limit() -> None:
    response = client.post(
        "/api/v1/exposure",
        content="x" * (32 * 1024 + 1),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"


def test_valid_routine_returns_explicit_unavailable_report() -> None:
    response = client.post(
        "/v1/exposure/reports",
        json={
            "name": "Morning commute",
            "stops": [
                {
                    "label": "Home",
                    "duration_minutes": 30,
                    "coordinates": {"latitude": 28.6139, "longitude": 77.2090},
                },
                {"label": "Office", "duration_minutes": 480},
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["pm25_value"] is None
    assert body["pm25_unit"] == "µg/m³"
    assert body["provenance"]["data_type"] == "unknown"
    assert body["coverage"] == {
        "usable_duration_minutes": 0,
        "total_requested_duration_minutes": 510,
        "ratio": 0,
        "percentage": 0,
    }
    assert body["error_code"] == "PROVIDER_NOT_IMPLEMENTED"


def test_rejects_invalid_coordinates() -> None:
    response = client.post(
        "/v1/exposure/reports",
        json={
            "stops": [
                {
                    "label": "Invalid",
                    "duration_minutes": 10,
                    "coordinates": {"latitude": 91, "longitude": 0},
                }
            ]
        },
    )

    assert_validation_error(response, "stops", 0, "coordinates", "latitude")


def test_rejects_non_positive_duration() -> None:
    response = client.post(
        "/v1/exposure/reports",
        json={"stops": [{"label": "Invalid", "duration_minutes": 0}]},
    )

    assert_validation_error(response, "stops", 0, "duration_minutes")


def test_rejects_more_than_maximum_stops() -> None:
    response = client.post(
        "/v1/exposure/reports",
        json={
            "stops": [
                {"label": f"Stop {index}", "duration_minutes": 1}
                for index in range(21)
            ]
        },
    )

    assert_validation_error(response, "stops")


def test_rejects_missing_stops() -> None:
    response = client.post("/v1/exposure/reports", json={})

    assert_validation_error(response, "stops")


def test_rejects_empty_routine() -> None:
    response = client.post("/v1/exposure/reports", json={"stops": []})

    assert_validation_error(response, "stops")


def test_rejects_missing_stop_values() -> None:
    response = client.post(
        "/v1/exposure/reports",
        json={"stops": [{"label": "Home"}]},
    )

    assert_validation_error(response, "stops", 0, "duration_minutes")


def test_accepts_upper_limits() -> None:
    response = client.post(
        "/v1/exposure/reports",
        json={
            "name": "n" * 120,
            "stops": [
                {
                    "label": f"Stop {index}",
                    "duration_minutes": 1440,
                    "coordinates": {"latitude": 90, "longitude": 180},
                }
                for index in range(7)
            ],
        },
    )

    assert response.status_code == 200


def test_rejects_unsupported_fields() -> None:
    response = client.post(
        "/v1/exposure/reports",
        json={
            "stops": [{"label": "Home", "duration_minutes": 10}],
            "unexpected": True,
        },
    )

    assert_validation_error(response, "unexpected")


def assert_validation_error(response: Response, *location: object) -> None:
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed."
    assert any(
        detail["location"][-len(location) :] == list(location)
        for detail in body["error"]["details"]
    )
