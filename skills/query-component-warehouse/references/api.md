# Component Warehouse Codex API reference

The client adds `/api/integrations/codex/` to the configured service root and authenticates machine endpoints with the read-only bearer token.

## Read endpoints

| Client command | Endpoint | Notes |
|---|---|---|
| session (configuration check) | `GET v1/session` | Owner, scope, expiry, service version |
| `search` | `GET v1/components/search` | Name, model, spec, package, LCSC number, stock filters |
| `get` | `GET v1/components/{warehouse_code}` | Full personal component, lots, suppliers, movements |
| `match` | `POST v1/components/match` | Maximum 200 requirements |
| `projects` | `GET v1/projects` | Active personal projects and reservation-aware BOM context |
| `project` | `GET v1/projects/{id_or_code}` | One personal project; prefer the stable project code |
| `risks` | `GET v1/risks` | Dynamic and manual personal risks with stable codes |
| `purchases` | `GET v1/purchases` | Personal orders, stable codes, outstanding and reliable in-transit quantities |

`match` accepts an array or `{ "items": [...] }`. Each item supports:

```json
{
  "reference": "R1,R2",
  "designator": "R1",
  "quantity": 2,
  "manufacturer_part": "RC0603FR-0710KL",
  "manufacturer": "Yageo",
  "supplier_part": "C25804",
  "supplier": "LCSC",
  "parameters": "10k ohm 1%",
  "value": "10k",
  "footprint": "0603",
  "category": "电阻"
}
```

Only a unique high-confidence result with sufficient unreserved stock is auto-selected. `available_quantity` already subtracts project reservations. `candidate`, `missing`, and `shortage` are never auto-selected. Put a complete manufacturer part number in `manufacturer_part`; place a family name such as `STM32G0` in `parameters` and treat the result as exploratory.

The matcher never emits a candidate from package similarity alone. Without an exact warehouse, supplier, or normalized manufacturer part number, it only admits a passive with the same type, normalized value, and package, or a connector with the same connector role, pin count, and mechanical package. Net labels and pin names are not BOM items; omit isolated labels such as `RFREQ`, `RIPROPI`, `BEC`, `VCC`, `GND`, `SW`, `FB`, `COMP`, and `BOOT` unless a populated component reference and electrical identity are also known.

If a known isolated label still reaches the API, the response keeps `classification: "missing"` for compatibility but sets `ignored_input: true`, provides `ignored_reason`, and omits `missing_suggestion`. Do not present ignored inputs as shortages or purchasing needs.

For an existing project, do not run `match` against its BOM to calculate shortages because that would count the project's own reservation as unavailable. Read `project PROJECT_CODE` and use each BOM row's `physical_shortage_quantity`, `reservation_shortage_quantity`, `reserved_by_other_projects_quantity`, `available_for_project_quantity`, and `shortage_quantity`. Never guess the current project from recency; ask for the project code when it is ambiguous.

For purchasing advice, count only `in_transit_quantity`; it is zero for planned, cancelled, or fully received lines. Join contexts by `warehouse_code` and `project_code`, not by display names.

## Operation proposal

`propose` sends `POST v1/operations`. It accepts an action array or:

```json
{
  "idempotency_key": "board-rev-a-20260718",
  "reason": "Create approved board project and reserve its BOM",
  "actions": [
    {
      "action": "project.create",
      "payload": {"name": "Board Rev A", "description": "Approved design"}
    }
  ]
}
```

Supported actions:

- `component.create`, `component.update`, `component.archive`, `component.restore`
- `stock.adjust` with integer `delta`; use `manual_consume`, `loss`, `manual_receipt`, or `codex_adjustment` as `movement_type`
- `project.create`, `project.update`, `project.archive`, `project.restore`
- `bom.upsert`, `bom.archive`, `bom.restore`
- `purchase.create`, `purchase.update`, `purchase.cancel`, `purchase.receive`

For `component.*` and `stock.adjust`, use the stable warehouse code as `target_id`. For `project.*`, use the project code or numeric ID. For an added BOM row, omit `target_id` and supply `project_id`/`project_code`, `warehouse_code`, `required_quantity`, `status`, and optional `remark`. For existing BOM rows use the numeric BOM row ID.

Actions execute in array order. To create a project and add its BOM atomically, explicitly set a unique `project_code` on `project.create`, put that action before dependent actions, and reuse the same code in each `bom.upsert` or `purchase.create` payload.

`purchase.create` requires a `lines` array. Each line requires `warehouse_code`, `ordered_quantity`, and optionally description, price, URL, and note. `purchase.receive` targets a purchase line ID and supplies a positive `quantity`.

The proposal response includes the operation ID, a ten-minute `approval_url`, normalized preview, and risk level. Approval and rejection endpoints are intentionally absent from the client. Terminal statuses are `rejected`, `expired`, `stale`, `failed`, `succeeded`, and `undone`; `pending_approval` is the only approvable status. Repeating `propose` after a non-success terminal status creates a new approval while retaining the old audit record.

`undo` calls `POST v1/operations/{id}/undo` and creates a second ten-minute approval proposal while the original is within its 30-day undo window. If that undo proposal reaches a non-success terminal state, request it again. Undo of creates archives the project/component/BOM rather than erasing it. Undo of stock changes and purchase receipts appends an opposite inventory movement while preserving the original movement and receipt history.
