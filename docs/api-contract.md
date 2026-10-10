# API contract

This is the first FastAPI contract for the MVP. It validates routine input and
returns a typed exposure report. The report endpoint uses Open-Meteo's public
Air Quality API for modelled hourly PM2.5 data when every routine stop has
coordinates.

## Health

```text
GET /health
```

Response:

```json
{"status": "ok"}
```

## Mobile exposure intake (temporary mock)

```text
POST /api/v1/exposure
Content-Type: application/json
```

This endpoint accepts only the minimum identifier needed to associate a request
with an app user. It does not require passwords, contact details, or API keys.
It currently validates and acknowledges the request only: it does not call an
air-quality provider or calculate an exposure estimate.

### Request

```json
{
  "user": {
    "user_id": "demo-user-001",
    "name": "Demo User"
  },
  "places": [
    {
      "name": "Home",
      "latitude": 26.4499,
      "longitude": 80.3319,
      "duration_minutes": 720
    },
    {
      "name": "College",
      "latitude": 26.476,
      "longitude": 80.3463,
      "duration_minutes": 360
    }
  ]
}
```

`user.user_id` and each place `name` are required and cannot be blank.
`user.name` is optional. Coordinates are required per place: latitude is in
`[-90, 90]` and longitude is in `[-180, 180]`. `duration_minutes` is greater
than zero and no greater than 1440. A request must contain 1–20 places and its
body must not exceed 32 KiB; larger bodies receive HTTP `413`.

### Temporary mock response

```json
{
  "status": "mock",
  "mock": true,
  "user_id": "demo-user-001",
  "places_received": 2,
  "total_requested_duration_minutes": 1080.0,
  "message": "Mock response only: no air-quality provider was queried and no exposure estimate was calculated.",
  "warnings": [
    "PM2.5 readings, coverage, and exposure estimates are not available yet."
  ]
}
```

The total duration is an input summary only, not an exposure calculation.

## Create an exposure report

```text
POST /v1/exposure/reports
Content-Type: application/json
```

### Request

```json
{
  "name": "Morning commute",
  "stops": [
    {
      "label": "Home",
      "duration_minutes": 30,
      "coordinates": {
        "latitude": 28.6139,
        "longitude": 77.209
      }
    },
    {
      "label": "Office",
      "duration_minutes": 480,
      "coordinates": {
        "latitude": 28.62,
        "longitude": 77.21
      }
    }
  ],
  "start_time": "2026-10-10T08:00:00Z"
}
```

`latitude` must be between `-90` and `90`; `longitude` must be between `-180`
and `180`. Each duration must be positive and no greater than 1440 minutes.
The request contains 1 to 20 stops, with labels and routine names limited to
120 characters. `start_time` is optional and must include a timezone; when
omitted, the backend evaluates the routine from the current UTC time.

### Response while provider data is unavailable

```json
{
  "status": "unavailable",
  "pm25_value": null,
  "pm25_unit": "µg/m³",
  "provenance": {
    "timestamp": null,
    "source": null,
    "data_type": "unknown"
  },
  "coverage": {
    "usable_duration_minutes": 0.0,
    "total_requested_duration_minutes": 510.0,
    "ratio": 0.0,
    "percentage": 0.0
  },
  "message": "Open-Meteo PM2.5 data is temporarily unavailable.",
  "error_code": "PROVIDER_ERROR"
}
```

`pm25_value` is a duration-weighted concentration in `µg/m³` when available.
The calculation uses only normalized PM2.5 concentration readings; AQI values
are not interchangeable with PM2.5 concentrations. Missing readings are
excluded from the weighted mean, not treated as zero. The calculation reports
requested duration, usable duration, coverage ratio, and coverage percentage.
`provenance.timestamp` is the routine evaluation end time, `source` identifies
Open-Meteo and CAMS ENSEMBLE modelled data, and `data_type` is `estimate`.
Open-Meteo data is modelled grid data, not a ground-monitor reading or an
exact street-level measurement. `coverage` reports usable duration and
requested duration in minutes, plus the same coverage as a ratio and
percentage.
`provenance.sources` and `provenance.data_types` list the source-aware
provenance used across segments. OpenAQ ground-monitor readings are marked
`observation`; Open-Meteo modelled values are marked `estimate`. Mixed-source
reports use `data_type: "unknown"` and list both values rather than silently
claiming one type.

The `status` is one of `available`, `unavailable`, or `error`. An unavailable
or error response is explicit and does not fabricate a reading. Stops without
coordinates remain unavailable because the provider cannot be queried for
them. Missing hourly values are not treated as zero.

OpenAQ fallback first discovers a nearby station, then selects a sensor whose
parameter is PM2.5 and whose units are `µg/m³`. Measurements are accepted
only when their timestamps overlap the requested interval and are fresh
enough for the evaluation. If those checks fail, the segment remains
unavailable.

Open-Meteo attribution: this project uses the Open-Meteo Air Quality API and
must attribute the CAMS ENSEMBLE data provider. See the
[Open-Meteo Air Quality API documentation](https://open-meteo.com/en/docs/air-quality-api).

To manually test the live endpoint after starting the backend:

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/exposure/reports `
  -ContentType "application/json" `
  -Body '{"name":"Morning commute","start_time":"2026-10-10T08:00:00Z","stops":[{"label":"Home","duration_minutes":60,"coordinates":{"latitude":28.6139,"longitude":77.2090}}]}'
```

### Validation errors

Invalid JSON payloads return HTTP `422` with a stable envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed.",
    "details": [
      {
        "location": ["body", "stops", 0, "duration_minutes"],
        "message": "Input should be greater than 0",
        "type": "greater_than"
      }
    ]
  }
}
```

Unknown fields are rejected. Locations identify the request body and, for
indexed stops, the precise field that failed validation.

## OpenAPI schema

The generated schema is checked in at
[backend/openapi.json](../backend/openapi.json). Regenerate it from the
FastAPI app with:

```text
cd backend
python scripts/generate_openapi.py
```
