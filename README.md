# Personal Air Exposure Companion

Personal Air Exposure Companion is planned as a mobile app that helps a person
understand estimated PM2.5 exposure during everyday routines. The MVP is
intentionally small:

- React Native + Expo + TypeScript mobile app
- Python + FastAPI + Pydantic backend
- One air-quality provider hidden behind a provider adapter
- Transparent duration-weighted PM2.5 estimates
- Manual routine entry as a fallback
- Foreground location only

The repository contains the first backend contract and documentation. The
application folders below describe the implementation layout; this is not a
deployed system.

## Proposed repository structure

```text
.
├── mobile/                         # Expo React Native TypeScript app
│   ├── src/
│   │   ├── components/
│   │   ├── screens/
│   │   ├── services/               # Backend client and location adapter
│   │   ├── state/
│   │   ├── types/
│   │   └── utils/
│   ├── app.json
│   ├── package.json
│   └── tsconfig.json
├── backend/                        # FastAPI service
│   ├── app/
│   │   ├── api/
│   │   ├── models/                 # Pydantic request/response models
│   │   ├── providers/              # Air-quality provider adapter
│   │   ├── services/               # Exposure calculation and orchestration
│   │   └── main.py
│   ├── tests/
│   ├── pyproject.toml
│   └── .env.example
├── docs/
│   └── architecture.md
├── .env.example                    # Optional shared documentation only
└── .gitignore
```

Mobile and backend dependencies, tooling, and tests remain separate. The
backend is the only place that communicates with the air-quality provider and
holds provider credentials.

## Local setup

No deployment is assumed or configured. The backend can be run locally on
Windows with PowerShell:

### Backend

```powershell
Set-Location .\backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`. Check that the backend is
running with:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected response:

```text
status
------
ok
```

If PowerShell blocks script activation for the current user, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate the environment again with
`.\.venv\Scripts\Activate.ps1`.

### Mobile

```powershell
Set-Location .\mobile
npm install
npx expo start
```

The mobile app should call the local backend URL configured for the active
Expo device or simulator. Do not put provider credentials in the mobile app.

## Environment variables

Names only; values must be supplied locally and must never be committed:

- `AIR_QUALITY_API_KEY`
- `AIR_QUALITY_BASE_URL`
- `AIR_QUALITY_PROVIDER`
- `BACKEND_HOST`
- `BACKEND_PORT`
- `EXPO_PUBLIC_API_BASE_URL`
- `LOG_LEVEL`

Only placeholder variable names belong in `.env.example`. A real `.env` file
is ignored by Git.

## Test and quality commands

These are the intended commands once implementation exists:

```powershell
Set-Location .\backend
python -m pytest
```

The backend test suite includes the health endpoint test and API contract
validation tests. Run the command above from the `backend` directory and use
the actual test output when reporting results.

## Privacy and scope

The MVP should collect only the information required to estimate exposure for
the current session. Foreground location is requested only while the user is
using the relevant feature. Manual routine entry must work when location is
denied or unavailable. The MVP does not include background tracking,
authentication, a database, maps, or AI.

See [docs/architecture.md](docs/architecture.md) for the detailed flow,
ownership boundaries, data handling, and approval checklist.
