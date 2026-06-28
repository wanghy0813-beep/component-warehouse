# Deployment

## Local Password Mode

The open-source default uses local username/password accounts.

1. Copy `.env.example` to `.env`.
2. Set strong values for `LOCAL_AUTH_SECRET` and `TEAM_INVITE_SECRET`.
3. Set public URLs for QR codes and team invitations.
4. Start the service with Docker Compose.

```bash
cp .env.example .env
docker compose up -d --build
```

The first locally registered user becomes an administrator. To close registration after bootstrap:

```env
LOCAL_AUTH_ALLOW_REGISTRATION=0
```

## Optional External Account Mode

If you already have a compatible Account V1 service, switch modes:

```env
AUTH_MODE=account-v1
ACCOUNT_BASE_URL=https://account.example.com/api/account/v1
ACCOUNT_SERVICE_CLIENT_ID=componentwarehouse-service
ACCOUNT_WEB_CLIENT_ID=componentwarehouse-web
ACCOUNT_CLIENT_SECRET=replace-with-secret
```

## Branding

The public profile uses generic branding and no bundled logo by default.

```env
APP_BRAND_NAME=Component Warehouse
VITE_BRAND_NAME=Component Warehouse
APP_SHOW_BRAND_LOGO=0
VITE_BRAND_SHOW_LOGO=0
```

Private deployments can set their own brand values and serve their own assets, but do not commit private brand files or filing numbers to a public repository.

## Health Check

```bash
docker compose ps
docker compose logs --tail=200 backend
curl -fsS http://127.0.0.1:${WEB_PORT:-8080}/component-warehouse/health
```

Check these pages:

- `/component-warehouse/personal/`
- `/component-warehouse/team/`
- `/component-warehouse/personal/components`
- `/component-warehouse/personal/projects`

## Backups

- Back up `data/component_warehouse.db`.
- Back up uploaded files under `data/`.
- Do not commit `data/`, `.env`, logs, API keys, tokens, or generated backups.
