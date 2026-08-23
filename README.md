# WXY LAB Hardware

**Current release:** `v1.4.0`

WXY LAB Hardware（WXY LAB 个人硬件研发工作台）是一套覆盖元器件库存、PCB 版本、装配、成本和项目全流程的个人研发平台：

- Personal hardware workspace: `/hardware/`
- Team workspace (temporarily paused; data and APIs retained): `/component-warehouse/team/`

The open-source profile defaults to local username/password accounts, generic branding, and no EDA/AD sync surface.

## Features

- Component inventory, categories, stock batches, labels, and QR scan pages.
- Personal project dashboard, lifecycle/status history, PCB V1/V2 chains, project BOM import, soldering progress, and cost tracking.
- Gerber ZIP + BOM + pick-and-place parsing, versioned board previews, interactive top/bottom assembly maps, calibration, cumulative loss tracking, and transaction-safe undo.
- Retained team libraries, members, projects and APIs; the team UI is temporarily paused while personal-workspace development continues.
- Optional AI-assisted component cleanup and BOM analysis through an OpenAI-compatible endpoint.
- Optional external Account V1 authentication for private deployments.
- ZIP64 `cwbackup/v2` disaster-recovery packages with referenced attachments, hashes, staged restore, and rollback.
- A thin Tauri 2 Windows x64 shell that reuses the personal Vue UI and a packaged FastAPI/SQLite sidecar for full offline work.
- Cursor-based, field-aware desktop synchronization with idempotent inventory events, resumable attachments, tombstones, and a conflict center.

## Versioning

The root `VERSION` file is the release source of truth for the API, web build, desktop build, and documentation. `v1.4.0` adds complete recovery, Windows offline operation, and account-scoped two-way sync without changing the existing server runtime topology.

## Development

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. pytest -q

cd ../frontend
npm ci
npm run check:copy
npm run build
```

## Deploy

Copy the example environment file and change every placeholder secret:

```bash
cp .env.example .env
```

For the default open-source local-account mode, set at least:

```env
AUTH_MODE=local-password
LOCAL_AUTH_SECRET=replace-with-a-long-random-secret
TEAM_INVITE_SECRET=replace-with-strong-random-secret
PUBLIC_PERSONAL_BASE_URL=https://example.com/hardware
PUBLIC_TEAM_BASE_URL=https://example.com/component-warehouse/team
```

Then start the service:

```bash
docker compose up -d --build
```

The first locally registered account becomes an administrator. After creating the first account, set `LOCAL_AUTH_ALLOW_REGISTRATION=0` if you do not want open registration.

## Private Profile

Private deployments can keep the full feature set by overriding environment variables:

```env
AUTH_MODE=account-v1
ACCOUNT_BASE_URL=https://account.example.com/api/account/v1
ACCOUNT_SERVICE_CLIENT_ID=componentwarehouse-service
ACCOUNT_WEB_CLIENT_ID=componentwarehouse-web
ACCOUNT_CLIENT_SECRET=replace-with-secret
FEATURE_EDA_ENABLED=1
VITE_FEATURE_EDA_ENABLED=1
APP_BRAND_NAME=Your Brand
VITE_BRAND_NAME=Your Brand
VITE_BRAND_SHOW_LOGO=1
APP_SHOW_BRAND_LOGO=1
```

Keep private `.env`, databases, uploaded files, logs, API keys, and custom brand assets out of Git.

## License

This repository is source-available under the PolyForm Noncommercial License 1.0.0 for non-commercial use, learning, modification, and evaluation only.

Commercial use, resale, paid hosting, SaaS use, or use inside a revenue-generating product or workflow requires prior written permission from WXY LAB. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
