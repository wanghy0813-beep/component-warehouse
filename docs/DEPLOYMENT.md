# Deployment

## Unified Account SSO

The WXY LAB production deployment uses unified Account SSO only. Password login,
SMS login, registration, password reset, and local account login are retired in
Component Warehouse.

1. Copy `.env.example` to `.env`.
2. Set the Account V1 service values and SSO redirect URI.
3. Set public URLs for QR codes and team invitations.
4. Start the service with Docker Compose, or prepare a direct-host preview.

```bash
cp .env.example .env
docker compose up -d --build
```

```env
AUTH_MODE=account-v1
ACCOUNT_BASE_URL=https://wxylab.ltd/api/wxylab/account/v1
ACCOUNT_SERVICE_CLIENT_ID=componentwarehouse-service
ACCOUNT_WEB_CLIENT_ID=componentwarehouse-web
ACCOUNT_CLIENT_SECRET=replace-with-secret
ACCOUNT_SSO_REDIRECT_URI=https://wxylab.ltd/component-warehouse/personal/auth/callback
```

For a private self-hosted development deployment, local password mode must be
enabled deliberately and is not used by the WXY LAB production service.

## Runtime Options

### Docker Compose

Docker Compose remains the compatibility and rollback runtime. It serves the
backend container and a frontend nginx container on `127.0.0.1:8080` / host
port `8080`, while the public nginx configuration proxies
`/component-warehouse/` to that port.

```bash
docker compose up -d --build
curl -fsS http://127.0.0.1:8080/component-warehouse/health
```

### Direct-Host Preview

Use the direct-host deployment script to run the same app without stopping the
Docker runtime. This builds the frontend into `/var/www/component-warehouse`,
runs the backend with systemd on `127.0.0.1:18080`, and exposes a local preview
nginx server on `127.0.0.1:18081`.

```bash
scripts/deploy_direct_host.sh
curl -fsS http://127.0.0.1:18080/health
curl -fsS http://127.0.0.1:18081/component-warehouse/health
curl -fsS http://127.0.0.1:8080/component-warehouse/health
```

The Docker service stays online on `8080`, so the public
`https://wxylab.ltd/component-warehouse/` route is unchanged during preview.

The script writes:

- `/etc/component-warehouse/backend.env`
- `/etc/systemd/system/component-warehouse-backend.service`
- `/etc/nginx/sites-available/component-warehouse-direct-8080`
- `/etc/nginx/sites-available/component-warehouse-direct-preview`
- `/var/www/component-warehouse/{personal,team,downloads}`

The generated backend env keeps `.env` values and overrides direct-host paths:

```env
DATABASE_URL=sqlite:////opt/ComponentWarehouse/data/component_warehouse.db
TEAM_MEDIA_ROOT=/opt/ComponentWarehouse/data/contest-media
CUSTOM_LABEL_STORAGE_ROOT=/opt/ComponentWarehouse/data/custom-labels
TEAM_SECRET_FILE=/opt/ComponentWarehouse/data/.contest-invite-secret
```

### Switch Direct-Host To Public Port

After the preview passes checks, switch the public runtime explicitly:

```bash
scripts/switch_to_direct_host.sh
curl -fsS http://127.0.0.1:8080/component-warehouse/health
curl -kfsS https://wxylab.ltd/component-warehouse/health
```

This stops only the Component Warehouse Docker frontend/backend services,
enables the direct-host nginx server on `127.0.0.1:8080`, reloads nginx, and
keeps the public route shape unchanged.

### Roll Back To Docker

To return the public runtime to Docker:

```bash
scripts/rollback_docker.sh
curl -fsS http://127.0.0.1:8080/component-warehouse/health
curl -kfsS https://wxylab.ltd/component-warehouse/health
```

Rollback disables the direct-host `8080` nginx binding, stops the direct backend
service, reloads nginx, and starts the Docker Compose backend/frontend again.

## Branding

The default deployment uses the bundled project logo. Set the logo flags to `0`
only when building a generic, unbranded distribution.

```env
APP_BRAND_NAME=Component Warehouse
VITE_BRAND_NAME=Component Warehouse
APP_SHOW_BRAND_LOGO=1
VITE_BRAND_SHOW_LOGO=1
```

Private deployments can set their own brand values and serve their own assets. Override the WXY LAB filing defaults when deploying under another domain.

Footer filing records are injected at frontend build time by Vite. Put private
filing numbers in `.env` before rebuilding the frontend image:

```env
VITE_COPYRIGHT_TEXT=© 2026 WXY LAB
VITE_ICP_RECORD_TEXT=ICP 备案号：冀ICP备2026009111号-1
VITE_ICP_RECORD_URL=https://beian.miit.gov.cn/
VITE_PUBLIC_SECURITY_RECORD_TEXT=冀公网安备13010402003414号
VITE_PUBLIC_SECURITY_RECORD_URL=https://beian.mps.gov.cn/#/query/webSearch
```

## Health Check

```bash
docker compose ps
docker compose logs --tail=200 backend
curl -fsS http://127.0.0.1:${WEB_PORT:-8080}/component-warehouse/health
systemctl status component-warehouse-backend
curl -fsS http://127.0.0.1:18081/component-warehouse/health
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
