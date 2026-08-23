# WXY LAB Hardware Windows

This directory is intentionally a thin native shell. It does not duplicate the
business UI: Tauri loads `frontend/dist/desktop`, and the packaged FastAPI
sidecar runs the same personal APIs against local SQLite.

Responsibilities kept in the shell are limited to lifecycle and trust-boundary
work: single instance, sidecar startup/health/exit, a per-launch loopback session
key, Device Authorization Grant, Windows Credential Manager refresh-token
storage, automatic bootstrap download, and the five-minute sync trigger.

Build from the repository root on Windows x64:

```powershell
.\build.ps1 -WebView2FixedRuntimePath C:\build\WebView2.FixedVersionRuntime.x64
```

The fixed WebView2 runtime makes installation independent of network access.
PyInstaller output must be produced on Windows; it is not a cross-compiled
Linux artifact.
