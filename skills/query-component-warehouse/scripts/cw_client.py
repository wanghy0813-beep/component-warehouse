#!/usr/bin/env python3
"""Deterministic stdlib client for the Component Warehouse Codex API."""

from __future__ import annotations

import argparse
import csv
import getpass
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path(os.environ.get("CW_CODEX_CONFIG", "~/.config/component-warehouse/codex.json")).expanduser()
USER_AGENT = "query-component-warehouse-skill/1.0"


class ClientError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _service_root(value: str) -> str:
    url = value.strip().rstrip("/")
    if url.endswith("/api"):
        url = url[:-4]
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ClientError("服务地址必须是完整的 http:// 或 https:// URL")
    if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ClientError("为避免泄露令牌，非本机服务必须使用 HTTPS")
    return url


def _api_url(root: str, path: str) -> str:
    return f"{root}/api/integrations/codex/{path.lstrip('/')}"


def _is_windows() -> bool:
    return sys.platform == "win32"


def _windows_user_sid() -> str:
    try:
        result = subprocess.run(
            ["whoami.exe", "/user", "/fo", "csv", "/nh"],
            check=True,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ClientError("无法读取当前 Windows 用户 SID，不能安全保存 Codex 令牌") from exc
    for row in csv.reader(result.stdout.splitlines()):
        for value in row:
            candidate = value.strip()
            if candidate.startswith("S-"):
                return candidate
    raise ClientError("无法识别当前 Windows 用户 SID，不能安全保存 Codex 令牌")


def _secure_windows_acl(path: Path, *, directory: bool = False) -> None:
    sid = _windows_user_sid()
    grant = f"*{sid}:(OI)(CI)(F)" if directory else f"*{sid}:(F)"
    try:
        subprocess.run(
            ["icacls.exe", str(path), "/inheritance:r", "/grant:r", grant],
            check=True,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ClientError(f"无法收紧 Windows 配置 ACL：{path}") from exc


def _secure_config_permissions(path: Path) -> None:
    if _is_windows():
        _secure_windows_acl(path.parent, directory=True)
        _secure_windows_acl(path)
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ClientError(f"配置权限不安全：{path} 必须为 0600")


def _read_config(path: Path = DEFAULT_CONFIG) -> dict[str, str]:
    try:
        if not path.is_file():
            raise FileNotFoundError(path)
        _secure_config_permissions(path)
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ClientError("尚未配置。先运行 cw_client.py configure --url <服务地址>") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ClientError(f"配置文件不可读：{path}") from exc
    root = _service_root(str(data.get("service_url") or ""))
    token = str(data.get("token") or "")
    if not token.startswith("cw_codex_"):
        raise ClientError("配置中的 Codex 令牌格式无效")
    return {"service_url": root, "token": token}


def _write_config(service_url: str, token: str, path: Path = DEFAULT_CONFIG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if _is_windows():
        _secure_windows_acl(path.parent, directory=True)
    else:
        os.chmod(path.parent, 0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".codex-", suffix=".json", dir=path.parent)
    try:
        if not _is_windows():
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump({"service_url": service_url, "token": token}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, path)
        if _is_windows():
            _secure_windows_acl(path)
        else:
            os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _request(
    config: dict[str, str],
    method: str,
    path: str,
    *,
    query: dict[str, Any] | None = None,
    payload: Any = None,
) -> Any:
    url = _api_url(config["service_url"], path)
    if query:
        clean = {key: value for key, value in query.items() if value is not None and value != ""}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    body = _json_bytes(payload) if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {config['token']}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = raw.decode("utf-8", errors="replace")[:1000]
        message = detail.get("detail") if isinstance(detail, dict) else str(detail)
        raise ClientError(message or f"HTTP {exc.code}", status=exc.code, detail=detail) from exc
    except urllib.error.URLError as exc:
        raise ClientError(f"无法连接 Component Warehouse：{exc.reason}") from exc
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError("服务返回了无效 JSON") from exc
    if isinstance(result, dict) and result.get("approval_url"):
        result["approval_url"] = urllib.parse.urljoin(config["service_url"] + "/", result["approval_url"].lstrip("/"))
    return result


def _load_input(path: str) -> Any:
    try:
        raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        return json.loads(raw)
    except FileNotFoundError as exc:
        raise ClientError(f"输入文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ClientError(f"输入不是有效 JSON：第 {exc.lineno} 行第 {exc.colno} 列") from exc


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _configure(args: argparse.Namespace) -> Any:
    root = _service_root(args.url)
    token = getpass.getpass("Codex 只读令牌（输入不会显示）：").strip()
    if not token.startswith("cw_codex_"):
        raise ClientError("令牌必须以 cw_codex_ 开头")
    config = {"service_url": root, "token": token}
    session = _request(config, "GET", "v1/session")
    _write_config(root, token, Path(args.config).expanduser())
    return {
        "configured": True,
        "config_path": str(Path(args.config).expanduser()),
        "service_url": root,
        "owner_user_id": session.get("owner_user_id"),
        "scopes": session.get("scopes"),
        "expires_at": session.get("expires_at"),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="查询 Component Warehouse 个人库并生成网页审批单")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    configure = sub.add_parser("configure", help="通过隐藏输入保存令牌并验证连接")
    configure.add_argument("--url", required=True, help="Component Warehouse 服务根地址")

    search = sub.add_parser("search", help="搜索个人元器件库存")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--category")
    search.add_argument("--package")
    search.add_argument("--stock", choices=["available", "shortage", "all"])
    search.add_argument("--limit", type=int, default=30)

    get = sub.add_parser("get", help="按稳定仓库编号读取器件详情")
    get.add_argument("warehouse_code")

    match = sub.add_parser("match", help="批量匹配结构化板卡/BOM 需求 JSON")
    match.add_argument("input", help="JSON 文件路径，或 - 从标准输入读取")
    match.add_argument("--top-n", type=int, default=5)

    sub.add_parser("projects", help="列出个人项目及 BOM/缺料上下文")
    project = sub.add_parser("project", help="读取一个个人项目")
    project.add_argument("project_id")
    sub.add_parser("risks", help="读取个人库开放风险")
    sub.add_parser("purchases", help="读取个人采购上下文")

    propose = sub.add_parser("propose", help="提交写操作草案，只生成网页审批单")
    propose.add_argument("input", help="操作 JSON 文件路径，或 - 从标准输入读取")
    propose.add_argument("--reason")
    propose.add_argument("--idempotency-key")

    status_cmd = sub.add_parser("status", help="查询审批、执行或撤销状态")
    status_cmd.add_argument("operation_id")
    undo = sub.add_parser("undo", help="为成功操作生成撤销审批单")
    undo.add_argument("operation_id")
    return parser


def run(args: argparse.Namespace) -> Any:
    if args.command == "configure":
        return _configure(args)
    config = _read_config(Path(args.config).expanduser())
    if args.command == "search":
        return _request(
            config,
            "GET",
            "v1/components/search",
            query={"q": args.query, "category": args.category, "package": args.package, "stock": args.stock, "limit": args.limit},
        )
    if args.command == "get":
        return _request(config, "GET", f"v1/components/{urllib.parse.quote(args.warehouse_code, safe='')}")
    if args.command == "match":
        payload = _load_input(args.input)
        if isinstance(payload, list):
            payload = {"items": payload}
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ClientError("match 输入必须是数组，或包含 items 数组的对象")
        payload["top_n"] = args.top_n
        return _request(config, "POST", "v1/components/match", payload=payload)
    if args.command == "projects":
        return _request(config, "GET", "v1/projects")
    if args.command == "project":
        return _request(config, "GET", f"v1/projects/{urllib.parse.quote(args.project_id, safe='')}")
    if args.command == "risks":
        return _request(config, "GET", "v1/risks")
    if args.command == "purchases":
        return _request(config, "GET", "v1/purchases")
    if args.command == "propose":
        payload = _load_input(args.input)
        if isinstance(payload, list):
            payload = {"actions": payload}
        if not isinstance(payload, dict) or not isinstance(payload.get("actions"), list):
            raise ClientError("propose 输入必须是动作数组，或包含 actions 数组的对象")
        if args.reason:
            payload["reason"] = args.reason
        if args.idempotency_key:
            payload["idempotency_key"] = args.idempotency_key
        if not payload.get("idempotency_key"):
            payload["idempotency_key"] = "codex-" + hashlib.sha256(_json_bytes(payload.get("actions"))).hexdigest()[:24]
        result = _request(config, "POST", "v1/operations", payload=payload)
        result["approval_required"] = True
        return result
    if args.command == "status":
        return _request(config, "GET", f"v1/operations/{urllib.parse.quote(args.operation_id, safe='')}")
    if args.command == "undo":
        result = _request(config, "POST", f"v1/operations/{urllib.parse.quote(args.operation_id, safe='')}/undo")
        result["approval_required"] = True
        return result
    raise ClientError(f"未知命令：{args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        _print(run(args))
        return 0
    except ClientError as exc:
        _print({"ok": False, "error": str(exc), "status": exc.status, "detail": exc.detail})
        return 1
    except KeyboardInterrupt:
        _print({"ok": False, "error": "已取消"})
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
