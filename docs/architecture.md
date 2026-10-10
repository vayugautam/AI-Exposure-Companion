# MVP architecture

## Scope

The MVP estimates personal PM2.5 exposure for a user-provided routine. It
combines air-quality readings with the duration spent in each routine segment.
The estimate is intentionally transparent: the app shows the segments,
durations, readings, and calculation inputs rather than presenting a hidden
score.

Out of scope: background location, authentication, persistent storage,
interactive maps, AI features, and deployment configuration.

## User flow

1. The user opens the Expo app and starts an exposure estimate.
2. The app requests foreground location only for the active interaction.
3. The user reviews or edits routine segments, including place/activity and
   duration.
4. If location is unavailable or denied, the user enters locations manually.
5. The app sends a typed routine request to the FastAPI backend.
6. The backend obtains air-quality data through the provider adapter.
7. The backend calculates a duration-weighted PM2.5 estimate.
8. The app displays the estimate, source readings, durations, units, timestamp,
   and any unavailable-data warnings.
9. The user can revise the routine and recalculate.

## Member ownership

Ownership is by responsibility, not by a deployment claim:

| Area | Primary owner | Responsibility |
| --- | --- | --- |
| Mobile | Mobile member | Expo screens, foreground location permission UX, manual entry, API client, result presentation |
| Backend | Backend member | FastAPI routes, Pydantic contracts, provider adapter, validation, calculation service |
| Data contract | Mobile and backend members | Versioned request/response shape, units, error states, compatibility |
| Privacy and QA | Whole team, with one reviewer | Permission behavior, data minimization, test coverage, release checklist |
| Documentation | Whole team | Keep this architecture and README aligned with implementation |

The team must assign names to these roles before implementation begins.

## Minimal data flow

```text
Foreground location or manual routine entry
        |
        v
Mobile validation and typed request
        |
        v
FastAPI endpoint
        |
        v
Open-Meteo adapter ---> Hourly modelled PM2.5 (`pm2_5`) data
        |
        v
Normalized PM2.5 readings
        |
        v
Duration-weighted calculation service
        |
        v
Typed estimate response ---> Mobile result screen
```

The provider adapter is the only backend boundary that knows the provider's
request and response format. The Open-Meteo adapter requests UTC hourly
`pm2_5` values and normalizes timestamps and concentrations. The OpenAQ
adapter discovers a nearby location, selects a PM2.5 sensor, and retrieves
time-bounded measurements using the server-side `OPENAQ_API_KEY`.

Open-Meteo is queried first. OpenAQ is used only when Open-Meteo has no usable
value for a complete routine segment. A fallback reading must have a nearby
station, PM2.5 parameter, `µg/m³` units, an overlapping timestamp, and an
acceptable freshness window. Values from both sources are never silently
combined within one segment.

The calculation service consumes normalized readings, so changing providers
does not change the mobile contract or calculation logic.

## Calculation behavior

For routine segments with duration `d_i` and normalized PM2.5 reading `p_i`,
the MVP estimate is:

```text
estimated PM2.5 = sum(p_i * d_i) / sum(d_i)
```

The calculation service excludes segments whose PM2.5 reading is missing from
both sums except that their durations remain in total requested duration.
It reports usable duration and coverage ratio/percentage. If no segment has a
usable normalized PM2.5 concentration, the result is explicitly unavailable.
AQI values must not be passed as PM2.5 concentrations in `µg/m³`.

The response must include the segment durations, readings, total duration,
units, source timestamp, and a clear indication when a reading is missing or
estimated. The backend must reject invalid durations and must not silently
substitute fabricated readings.

Open-Meteo values are modelled CAMS ENSEMBLE grid data. They are not
ground-monitor observations or exact street-level measurements. The
application must attribute both Open-Meteo and the CAMS ENSEMBLE data provider.
OpenAQ values are reported ground-monitor measurements and are marked as
observations. When a report uses more than one source across its segments,
the response lists all sources and marks the combined data type as `unknown`
instead of implying that all values have the same provenance.

## Privacy behavior

- Ask for foreground location only when the user starts the relevant flow.
- Explain why location is needed before requesting permission.
- Keep manual routine entry available when permission is denied.
- Send only the routine data needed for the current estimate.
- Do not store location, routines, or readings in a database in the MVP.
- Do not add authentication, background tracking, maps, or third-party
  analytics without an explicit approved decision.
- Keep provider credentials on the backend; never expose them to Expo.
- Log operational errors without logging precise location or other unnecessary
  personal data.
- Treat `.env` files, credentials, and local databases as ignored files.

## Local setup

Work from two independent directories:

```text
backend/   # Python environment and FastAPI process
mobile/    # Node.js dependencies and Expo process
```

Backend setup:

```text
cd backend
python -m venv .venv
python -m pip install -e ".[dev]"
copy .env.example .env       # Windows
uvicorn app.main:app --reload
```

Mobile setup:

```text
cd mobile
npm install
npx expo start
```

The repository contains the first backend contract and package metadata. No
deployment is configured or claimed.

## Environment variables

Variable names only:

- `AIR_QUALITY_API_KEY`
- `AIR_QUALITY_BASE_URL`
- `AIR_QUALITY_PROVIDER`
- `BACKEND_HOST`
- `BACKEND_PORT`
- `EXPO_PUBLIC_API_BASE_URL`
- `LOG_LEVEL`

No API key, credential, or real endpoint value is included in this repository.

## Planned test commands

Backend:

```text
cd backend
python -m pytest
python -m ruff check .
python -m mypy app
```

Mobile:

```text
cd mobile
npm test
npx tsc --noEmit
```

Important test cases include calculation transparency, invalid and zero
durations, provider errors, missing readings, manual-entry fallback, denied
location permission, and ensuring provider credentials never reach the mobile
bundle.

## Team approval checklist

- [ ] Assign named owners for mobile, backend, data contract, privacy, and QA.
- [ ] Approve the single air-quality provider and its normalized PM2.5 fields.
- [ ] Approve the request/response contract, units, timestamp policy, and
      missing-data behavior.
- [ ] Approve the minimum and maximum routine segment duration and total
      duration limits.
- [ ] Approve the foreground location permission copy and manual fallback UX.
- [ ] Approve local development URLs and the supported simulator/device matrix.
- [ ] Approve the logging and retention policy before any persistence is added.
