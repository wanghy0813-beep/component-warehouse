import importlib.util
import json
import stat
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


CLIENT_PATH = Path(__file__).parents[2] / "skills/query-component-warehouse/scripts/cw_client.py"
SPEC = importlib.util.spec_from_file_location("cw_skill_client", CLIENT_PATH)
client_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(client_module)


class MockHandler(BaseHTTPRequestHandler):
    requests = []

    def _reply(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        self.__class__.requests.append((self.command, self.path, self.headers.get("Authorization"), body))
        if self.headers.get("Authorization") != "Bearer cw_codex_test-secret":
            status, payload = 401, {"detail": "bad token"}
        elif self.path.endswith("/v1/session"):
            status, payload = 200, {"owner_user_id": 1, "scopes": ["inventory:read"], "expires_at": "2027-07-18T00:00:00Z"}
        elif self.path.endswith("/v1/categories"):
            status, payload = 200, {"items": [{"id": 2, "name": "设备", "code_prefix": "EQP"}], "count": 1}
        elif "/components/search" in self.path:
            status, payload = 200, {"items": [{"warehouse_code": "RES-00000001", "available_quantity": 8, "average_unit_price": 0.125, "price_currency": "CNY"}]}
        elif self.path.endswith("/components/match"):
            status, payload = 200, {"items": [{"classification": "exact", "auto_selected": True}]}
        elif self.path.endswith("/v1/operations"):
            status, payload = 200, {"id": "op-1", "status": "pending_approval", "approval_url": "/hardware/integrations/codex/operations/op-1"}
        elif self.path.endswith("/undo"):
            status, payload = 200, {"id": "undo-1", "status": "pending_approval", "approval_url": "/hardware/integrations/codex/operations/undo-1"}
        else:
            status, payload = 200, {"status": "succeeded"}
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    do_GET = _reply
    do_POST = _reply

    def log_message(self, *_args):
        return


@pytest.fixture()
def mock_service(tmp_path):
    MockHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = tmp_path / "codex.json"
    client_module._write_config(f"http://127.0.0.1:{server.server_port}", "cw_codex_test-secret", config)
    try:
        yield config
    finally:
        server.shutdown()
        thread.join(timeout=3)


def parse(*arguments):
    return client_module._build_parser().parse_args(arguments)


def test_client_search_match_propose_status_and_undo(mock_service, tmp_path):
    config_flag = ("--config", str(mock_service))
    search = client_module.run(parse(*config_flag, "search", "10k", "--stock", "available"))
    assert search["items"][0]["warehouse_code"] == "RES-00000001"
    assert search["items"][0]["average_unit_price"] == 0.125
    assert search["items"][0]["price_currency"] == "CNY"

    categories = client_module.run(parse(*config_flag, "categories"))
    assert categories["items"] == [{"id": 2, "name": "设备", "code_prefix": "EQP"}]

    match_file = tmp_path / "match.json"
    match_file.write_text(json.dumps([{"designator": "R1", "quantity": 2, "value": "10k", "footprint": "0603"}]))
    match = client_module.run(parse(*config_flag, "match", str(match_file)))
    assert match["items"][0] == {"classification": "exact", "auto_selected": True}

    operation_file = tmp_path / "operation.json"
    operation_file.write_text(json.dumps([{"action": "stock.adjust", "target_id": "RES-00000001", "payload": {"delta": -1}}]))
    proposal = client_module.run(parse(*config_flag, "propose", str(operation_file), "--reason", "consume one"))
    assert proposal["approval_required"] is True
    assert proposal["approval_url"].endswith("/hardware/integrations/codex/operations/op-1")
    request_body = next(row[3] for row in MockHandler.requests if row[1].endswith("/v1/operations"))
    assert request_body["idempotency_key"].startswith("codex-")

    assert client_module.run(parse(*config_flag, "status", "op-1"))["status"] == "succeeded"
    undo = client_module.run(parse(*config_flag, "undo", "op-1"))
    assert undo["approval_required"] is True
    assert undo["status"] == "pending_approval"
    assert all(row[2] == "Bearer cw_codex_test-secret" for row in MockHandler.requests)


def test_configuration_uses_hidden_token_and_enforces_mode(mock_service, monkeypatch, tmp_path):
    destination = tmp_path / "nested" / "codex.json"
    monkeypatch.setattr(client_module.getpass, "getpass", lambda _prompt: "cw_codex_test-secret")
    root = client_module._read_config(mock_service)["service_url"]
    result = client_module.run(parse("--config", str(destination), "configure", "--url", root))
    assert result["configured"] is True
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert "cw_codex_test-secret" not in json.dumps(result)

    destination.chmod(0o644)
    with pytest.raises(client_module.ClientError, match="0600"):
        client_module._read_config(destination)


def test_windows_config_uses_current_user_acl_instead_of_unix_mode(monkeypatch, tmp_path):
    destination = tmp_path / "component-warehouse" / "codex.json"
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[0] == "whoami.exe":
            return subprocess.CompletedProcess(command, 0, '"DESKTOP\\HaoyuWang","S-1-5-21-123"\n', "")
        return subprocess.CompletedProcess(command, 0, "processed 1 file", "")

    monkeypatch.setattr(client_module, "_is_windows", lambda: True)
    monkeypatch.setattr(client_module.subprocess, "run", fake_run)
    client_module._write_config("https://warehouse.example.test", "cw_codex_test-secret", destination)

    assert client_module._read_config(destination) == {
        "service_url": "https://warehouse.example.test",
        "token": "cw_codex_test-secret",
    }
    acl_commands = [command for command, _kwargs in calls if command[0] == "icacls.exe"]
    assert ["/inheritance:r", "/grant:r"] == [acl_commands[0][2], acl_commands[0][3]]
    assert any(command[-1] == "*S-1-5-21-123:(OI)(CI)(F)" for command in acl_commands)
    assert any(command[-1] == "*S-1-5-21-123:(F)" for command in acl_commands)


def test_windows_config_fails_closed_when_acl_cannot_be_applied(monkeypatch, tmp_path):
    destination = tmp_path / "codex.json"
    destination.write_text('{"service_url":"https://example.test","token":"cw_codex_test"}')
    monkeypatch.setattr(client_module, "_is_windows", lambda: True)
    monkeypatch.setattr(client_module, "_windows_user_sid", lambda: "S-1-5-21-123")

    def fail_acl(*_args, **_kwargs):
        raise subprocess.CalledProcessError(5, "icacls.exe")

    monkeypatch.setattr(client_module.subprocess, "run", fail_acl)
    with pytest.raises(client_module.ClientError, match="Windows 配置 ACL"):
        client_module._read_config(destination)


def test_missing_windows_config_keeps_configuration_hint(monkeypatch, tmp_path):
    monkeypatch.setattr(client_module, "_is_windows", lambda: True)
    with pytest.raises(client_module.ClientError, match="尚未配置"):
        client_module._read_config(tmp_path / "missing" / "codex.json")


def test_plain_http_is_allowed_only_for_loopback():
    assert client_module._service_root("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
    assert client_module._service_root("http://localhost:8000") == "http://localhost:8000"
    with pytest.raises(client_module.ClientError, match="HTTPS"):
        client_module._service_root("http://warehouse.example.test")
