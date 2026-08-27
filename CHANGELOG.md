# WXY LAB Hardware Changelog

## 2026-08-27 · ChatGPT integration

- Published the renamed OAuth MCP connector at `https://wxylab.ltd/hardware/mcp`, retained the former `/component-warehouse/mcp` resource for compatibility, moved the live MCP service into the regular direct-host deployment, and updated its published name to `WXY LAB Hardware`.
- Added MCP workspace catalog and cursor-paged dataset tools so the connector can read the authenticated user's complete personal business workspace under the existing read-only and browser-approved-write boundary.
- Renamed the installed ChatGPT/Codex integration to `WXY LAB Hardware` across its Skill metadata and web management surfaces.
- Expanded the existing personal access token from inventory-oriented queries to a catalogued, cursor-paginated read API covering all 57 personal business datasets, including offline-workspace data and personal import history.
- Kept the trust boundary unchanged: team and other-user data, credentials and tokens, audit logs, AI caches, sync internals, binary contents, and server paths remain excluded; every write still requires browser approval.

## 2026-08-24 · v1.4.0

- Added the `cwbackup/v2` ZIP64 disaster-recovery format with an online-consistent SQLite snapshot, database-referenced files only, per-file SHA256, scope/version/server/cursor metadata, staged restore, pre-restore backup, integrity checks, directory switching, and automatic rollback.
- Retained legacy database-only restore with an explicit attachment warning, added tiered v2 retention, and added preview-plus-confirmation cleanup for old recursive backups while preserving recent and v1.4 checkpoints.
- Added account-isolated cursor sync models and APIs for device registration, personal bootstrap, idempotent push/pull, field-time merge, tombstones, conflict resolution, and 4 MiB resumable SHA256 blob transfer.
- Made stock changes semantic events: concurrent deltas merge without row overwrite; absolute adjustments, insufficient stock, concurrent lot edits, and delete/modify cases freeze the whole business transaction for manual resolution.
- Added a thin Tauri 2 Windows x64 application that reuses the personal Vue UI and a PyInstaller FastAPI sidecar, stores local SQLite/files under `%LOCALAPPDATA%`, binds only to loopback with a per-launch session key, and stores rotating refresh tokens in Windows Credential Manager.
- Added first-login automatic personal-data download through the Device Authorization Grant, automatic sync on startup/network recovery/every five minutes, visible local/sync/conflict states, and a native conflict center. AI, Codex, account security, team workspace, and server backup administration remain online-only.
- Added a Windows runner build driven by `build.ps1` for the sidecar, fixed WebView2 runtime, NSIS installer, SBOMs, and SHA256. The existing FastAPI systemd and Nginx deployment shape is unchanged.

## 2026-08-18 · v1.3.0

- Replaced the personal project module with an independent Project V2 aggregate and a single `/projects` workspace; removed the legacy dashboard, numeric-ID detail page, public project page, and their frontend components.
- Added responsive status, weekly-cost, and expense-composition visualizations; a stable overflow-safe project table; and inline overview, PCB version, BOM/assembly, cost, file, and risk workspaces.
- Added version BOM import, per-version physical boards and solder points, inventory-backed solder/loss actions, immutable material-cost events, direct expenses, unpriced backfill, project files, and risk records.
- Added the one-shot `v1.3.0-personal-project-v2-reset` migration with a pre-reset SQLite backup. It removes all existing personal projects without reversing inventory and detaches durable stock and purchase audit records.
- Moved ChatGPT project queries and browser-approved project writes to `project-workspace-v2` and immutable project codes. Team projects remain on their existing model and routes.

## 2026-08-16 · v1.2.3

- Reworked the shared material palette around WCAG-friendly ink, muted text, petrol-blue actions, white ceramic surfaces, and stronger borders instead of low-contrast gray-on-gray combinations.
- Fixed the shared surface cascade so intentional dark project headers and sidebars can no longer be overwritten by the generic light panel background.
- Replaced dark or bleaching loading states with a stable light pre-paint canvas, accessible boot indicator, high-contrast teal spinner, and first-load-only project-dashboard mask.
- Added UI contracts for text and accent contrast ratios, zero-specificity shared surfaces, light loading masks, initial HTML background, and personal/team boot states.

## 2026-08-15 · v1.2.2

- Rebuilt the inventory home around four primary decisions, a compact context strip, ranked category structure, and collapsed exception lists so the page stays calm as the catalog grows.
- Replaced the warm visual layer across personal and team surfaces with a mineral, ceramic, and oxidized-metal material system using static CSS highlights instead of costly blur or animated texture effects.
- Standardized project-detail workspace spacing, navigation, lifecycle cards, cost panels, status board, charts, and tables around one responsive rhythm with explicit truncation and horizontal overflow guards.
- Added deferred below-fold rendering and source-level UI contracts for information limits, card spacing, material performance, table truncation, and narrow-screen safety.

## 2026-08-15 · v1.2.1

- Unified personal and team pages around a warm cream, coral, gold, and sage visual system with shared Element Plus surfaces and responsive overflow safeguards.
- Expanded the project dashboard with status composition, weekly cost trend, stacked project cost comparison, a warmer status board, and a horizontally safe detail table.
- Repaired AI task health handling by scanning the full component catalog, recovering interrupted work, preserving failed audit rows on retry, and superseding obsolete historical failures.
- Extended health diagnostics with provider, worker, failed, and stuck-task dimensions so historical queue failures can no longer silently degrade the service.

## 2026-08-15 · v1.2.0

- Rebuilt the personal `/projects` entry as a lightweight dashboard with status cards, weekly cost trend, status distribution, drag-to-transition board, filters, and paginated project summaries.
- Added globally unique uppercase project codes with historical aliases, manual lifecycle transitions, Shanghai-date/ISO-week periods, archive/restore, and append-only status history.
- Added independent PCB V1/V2 version chains, version-scoped BOMs, boards, import batches, fabrication sub-revisions, and explicit versioned APIs while retaining current-version compatibility routes.
- Added immutable material-cost snapshots for solder/loss/reversal actions, explicit unpriced-item backfill, a CNY expense ledger with web receipt uploads, and separate purchase plan/commit totals.
- Extended the browser-approval-only ChatGPT integration and `query-component-warehouse` Skill with project dashboard, version, cost, status, code, and expense operations.
- Added repeatable startup migration `v1.2.0-project-lifecycle-costs` with a pre-migration SQLite backup and no migration-time inventory or material-cost movements.

## 2026-08-12 · v1.1.0

- Added a shared personal/team Gerber assembly workbench with safe ZIP upload, deterministic JLC/EasyEDA, KiCad, and Altium BOM/CPL mapping, sanitized PyGerber SVG layers, and a persistent restart-safe parser queue.
- Added manufacturing revisions with preview-before-commit, explicit AI-assisted mapping confirmation, version comparison/conflict handling, archive/reactivation, calibration, and manual placement reset.
- Added interactive top/bottom board views with pan/zoom, layer controls, bidirectional reference selection, unpositioned trays, multi-board instances, mobile controls, and keyboard modes.
- Added idempotent, optimistic-concurrency assembly actions with atomic inventory rollback, cumulative loss events, solder-to-loss reclassification, per-operation undo, and team inventory-source audit.
- Added opt-in minimized public assembly maps. Source archives, download paths, stock, storage locations, people, teams, and notes remain private.
- Added append-only SQLite migration `v1.1.0-project-assembly`, automatic pre-migration backups, redistributable synthetic fabrication fixtures, and security/permissions/inventory tests.

## 2026-06-28 · v1.0.0

- Added local username/password authentication as the default public deployment mode.
- Added configurable branding for generic deployments without a bundled private logo.
- Removed filing-number footer text and private deployment metadata from public documentation and examples.
- Documented Docker deployment, local account setup, optional external account integration, backups, and non-commercial license terms.
- Disabled EDA/AD sync surfaces by default for the public profile; private deployments can still enable the compatibility mode explicitly.
