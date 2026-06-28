# Component Warehouse

**Current release:** `v1.0.0`

Component Warehouse is a simple component inventory and project BOM management system with two web entries:

- Personal inventory: `/component-warehouse/personal/`
- Team inventory: `/component-warehouse/team/`

The open-source profile defaults to local username/password accounts, generic branding, and no EDA/AD sync surface.

## Features

- Component inventory, categories, stock batches, labels, and QR scan pages.
- Project BOM import, matching, soldering progress, shortage review, and substitute suggestions.
- Team libraries, invitations, members, shared components, projects, purchases, risks, and logs.
- Optional AI-assisted component cleanup and BOM analysis through an OpenAI-compatible endpoint.
- Optional external Account V1 authentication for private deployments.

## Versioning

Public releases use semantic versioning. `v1.0.0` is the initial source-available public release and defaults to local username/password authentication with generic branding.

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
PUBLIC_PERSONAL_BASE_URL=https://example.com/component-warehouse/personal
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
