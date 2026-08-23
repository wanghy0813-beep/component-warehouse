---
name: query-component-warehouse
description: Query the user's personal WXY LAB Hardware workspace while analyzing circuit boards, schematics, BOMs, component selection, shortages, substitutions, projects, purchases, or stock availability. Use automatically when an electronics task benefits from checking which components the user already owns. Also use it to prepare workspace changes, but only as browser-approved operation proposals.
---

# Query WXY LAB Hardware

Use the deterministic client in `scripts/cw_client.py`. Treat the service as the source of truth for current personal inventory, stable warehouse codes, reservations, projects, purchasing, and risks.

## Safety boundaries

- Query only the token owner's personal library. The token can read inventory and create inert operation proposals; it cannot approve or execute them. Never infer access to team or another user's data.
- Never display, echo, log, pass as a command argument, or include the `cw_codex_` token in an answer.
- Keep board photos, schematics, design archives, and local BOM files local. Extract structured requirements first; send only those fields to `match`.
- Never claim a write happened when only a proposal exists. The client cannot approve operations.
- For any write, present the returned approval URL and risk summary. The user must approve it in the authenticated WXY LAB Hardware page.
- Treat deletion as recoverable archive. Never propose permanent purge, account/admin changes, or database maintenance.

## Query workflow

1. Identify the requested parts locally from the image, schematic, notes, or BOM.
   Stop for missing design constraints before selecting a family-level part. For example, ask for the exact MCU variant/package and required peripherals before treating `STM32` as an MPN, and derive decoupling quantities from the exact datasheet rather than guessing.
   Exclude net names, IC pin names, power rails, test points, and functional annotations from component requirements. Tokens such as `RFREQ`, `RIPROPI`, `BEC`, `VCC`, `GND`, `SW`, `FB`, `COMP`, and `BOOT` are not components unless a real reference designator plus value/model/package identifies a populated part. Do not search every OCR label independently.
2. Normalize each requirement to the supported structured fields: `reference`/`designator`, `quantity`, `manufacturer_part`, `manufacturer`, `supplier_part`, `supplier`, `parameters`/`value`, `footprint`, and `category`.
3. Use `match` for more than one requirement. Use `search` for exploratory selection and `get` for the stable warehouse code selected from results.
4. Distinguish results exactly:
   - `exact`: one uniquely high-confidence match; it may be selected automatically.
   - `candidate`: alternatives requiring manual electrical, package, and pinout review.
   - `shortage`: the part matches but available stock is insufficient.
   - `missing`: no safe personal-library match.
   - `ignored_input: true`: a net, power rail, test point, or IC pin label was safely ignored; do not report it as a missing part or recommend purchasing it.
5. Prefer `available_quantity`, not raw `quantity`, because project reservations reduce usable stock.
6. Include `average_unit_price` and `price_currency` when reporting each queried or matched component. Treat a null average as “未计价”; never display it as zero or infer a price from supplier quotes.
7. State the stable `warehouse_code` for recommended in-stock parts. Never silently substitute a candidate.

Package similarity alone is never evidence of electrical compatibility. A non-exact candidate is valid only when the service confirms the same passive type, normalized value, and package, or the same connector type, pin count, and mechanical package. Treat a diode subtype, IC family, module, switch, fuse, sensor, or power part with no exact model/supplier match as `missing`; never promote a same-package part.

For project-level questions, start with `project-dashboard` when the user asks about all projects, status, parallel work, costs, or anomalies. The project API is the clean `project-workspace-v2` aggregate: use `project`, `project-versions`, and `project-costs` for a selected project, then query `risks` and `purchases` when shortages or sourcing matter. A `project` result includes the ordered lifecycle nodes and exact status audit history; distinguish auto-backfilled creation stages from later manual changes. Ask the user to choose a stable `project_code` if more than one project could be meant. Always report the project code, PCB version code, CNY cost definition, and unpriced count. Project V2 reports per-board BOM availability and shortage directly; do not rematch its BOM to infer availability. Use only purchase lines marked with a positive `in_transit_quantity` as placed, outstanding coverage, and never add purchases to comprehensive cost.

If no live connection or result is available, say so. Never substitute an old result, inspect the service database directly, or infer the current project from the most recently updated record.

## Client commands

Run commands from this skill directory:

```bash
python3 scripts/cw_client.py search "STM32" --stock available
python3 scripts/cw_client.py get ICS-00000001
python3 scripts/cw_client.py categories
python3 scripts/cw_client.py match /path/to/structured-bom.json
python3 scripts/cw_client.py projects
python3 scripts/cw_client.py project-dashboard
python3 scripts/cw_client.py project PRJ-12345678
python3 scripts/cw_client.py project-versions PRJ-12345678
python3 scripts/cw_client.py project-costs PRJ-12345678
python3 scripts/cw_client.py risks
python3 scripts/cw_client.py purchases
python3 scripts/cw_client.py propose /path/to/operation.json --reason "Create project and reserve approved BOM"
python3 scripts/cw_client.py status OPERATION_ID
python3 scripts/cw_client.py undo OPERATION_ID
```

All commands emit JSON and use only the Python standard library. Use `-` instead of a path to read structured JSON from standard input.

If configuration is missing, ask the user for the WXY LAB Hardware service root, then run:

```bash
python3 scripts/cw_client.py configure --url https://example.com/hardware
```

The command reads the token through hidden input and writes `~/.config/component-warehouse/codex.json`. It enforces mode `0600` on Unix-like systems; on Windows it removes inherited ACLs and grants access only to the current Windows user. Do not collect the token in chat.

## Write proposal workflow

Read `references/api.md` before composing a write proposal.

1. Create a JSON document with one to 100 atomic actions, a clear reason, and optionally an idempotency key.
   Actions execute in listed order. For a project and its BOM in the same proposal, give `workspace.project.create` an explicit `project_code`, place it first, and reuse that code in later `workspace.bom.upsert` actions. Project creation may include the real `start_date`, current `status`, and a complete `lifecycle_dates` mapping for every reached primary stage. Without exact dates, generated nodes are estimates and must never be described as actual history. Project status, PCB versions, expenses, and version BOM changes must also use `workspace.*` proposals; project codes are immutable after creation. Binary BOM, receipt, and manufacturing files stay in the web UI.
2. Use only supported action names and stable warehouse/project identifiers.
3. Run `propose`. Confirm that the result says `pending_approval` and `approval_required`.
4. Give the user the approval URL and summarize before/after changes and high-risk actions.
5. Poll with `status` only when the user asks or when continuing an approval workflow.
6. For a successful operation within 30 days, `undo` creates another approval proposal. It does not execute the reversal.

Treat `rejected`, `expired`, `stale`, `failed`, `succeeded`, and `undone` as terminal statuses. Poll no faster than every five seconds and never beyond `approval_expires_at`. When a proposal is rejected, expires, becomes stale, or fails, report that no partial write should be assumed and run `propose` again against current state. The service preserves the old audit record while creating a new approval ID. A rejected, expired, stale, or failed undo proposal can likewise be requested again during the original 30-day window.

Undo preserves history: workspace create actions reverse to archived records, and inventory reversals append opposite ledger movements. Do not describe undo as deleting the original project, BOM, loss, receipt, or audit entry.
