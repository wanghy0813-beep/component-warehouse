from __future__ import annotations

import os
import sys
from pathlib import Path


def configure_desktop_environment() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA", "").strip()
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is unavailable")
    data_root = Path(local_app_data) / "WXY LAB Hardware"
    data_root.mkdir(parents=True, exist_ok=True)
    session_key = os.getenv("DESKTOP_SESSION_KEY", "").strip()
    if len(session_key) < 32:
        raise RuntimeError("DESKTOP_SESSION_KEY is missing")
    defaults = {
        "DESKTOP_MODE": "1",
        "DESKTOP_DATA_ROOT": str(data_root),
        "DATABASE_URL": f"sqlite:///{(data_root / 'component_warehouse.db').as_posix()}",
        "AUTH_MODE": "none",
        "NO_AUTH_USER_ID": "1",
        "NO_AUTH_ADMIN": "1",
        "NO_AUTH_PHONE": "desktop-local",
        "NO_AUTH_NICKNAME": "离线账号",
        "SYNC_ENABLED": "1",
        "CUSTOM_LABEL_STORAGE_ROOT": str(data_root / "custom-labels"),
        "EDA_STORAGE_ROOT": str(data_root / "eda-library"),
        "PROJECT_V2_FILE_ROOT": str(data_root / "project-v2-files"),
        "TEAM_MEDIA_ROOT": str(data_root / "contest-media"),
        "TEAM_SECRET_FILE": str(data_root / ".contest-invite-secret"),
        "CORS_ORIGINS": "tauri://localhost,http://tauri.localhost,https://tauri.localhost",
        "ALLOWED_HOSTS": "127.0.0.1,localhost",
        "AI_AUTO_REFRESH_ENABLED": "0",
        "ENABLE_API_DOCS": "0",
        "RETIRE_LEGACY_PERSONAL_PROJECT_API": "1",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    return data_root


def main() -> None:
    configure_desktop_environment()
    import uvicorn
    from app.main import app

    port = int(os.getenv("DESKTOP_API_PORT", "18764"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"desktop sidecar failed: {error}", file=sys.stderr)
        raise
