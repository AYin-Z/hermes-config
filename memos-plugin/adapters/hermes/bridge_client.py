"""Python client for memos-core-bridge (hermes-agent variant).

Supports three connection modes:
  1. HTTP (REST API) — connects to MemOS Full Server REST API, preferred.
  2. TCP (daemon mode) — connects to a running bridge daemon.
  3. stdio (subprocess) — spawns a short-lived bridge child process, fallback.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import subprocess
import threading
import time

from typing import Any

from config import OWNER, _get_plugin_root, find_bridge_script, get_bridge_config, get_daemon_port


logger = logging.getLogger(__name__)


class _HttpTransport:
    """Use MemOS Full Server REST API instead of local TCP daemon."""

    def __init__(self, base_url: str = "http://localhost:8000",
                 agent_id: str = "hermes",
                 workspace_id: str = "default") -> None:
        self._base_url = base_url.rstrip("/")
        self._agent_id = agent_id
        self._workspace_id = workspace_id
        import requests as _requests
        self._requests = _requests

    def send(self, data: str) -> str:
        req = json.loads(data)
        method = req["method"]
        params = req.get("params", {})
        owner = params.get("owner", "hermes")

        try:
            if method == "search":
                t0 = time.time()
                body = {
                    "user_id": owner,
                    "agent_id": self._agent_id,
                    "workspace_id": self._workspace_id,
                    "session_id": params.get("sessionId", "default"),
                    "query": params.get("query", ""),
                    "top_k": params.get("maxResults", 6),
                    "include_preference": True,
                    "include_skill_memory": True,
                    "search_tool_memory": True,
                }
                r = self._requests.post(
                    f"{self._base_url}/product/search", json=body, timeout=30
                )
                search_data = r.json()
                # Transform MemOS response to the format _do_recall expects
                hits = []
                if search_data.get("code") == 200:
                    data = search_data.get("data", {})
                    for mem_type in ["text_mem", "pref_mem", "skill_mem", "tool_mem"]:
                        items = data.get(mem_type, [])
                        if isinstance(items, list):
                            for group in items:
                                if isinstance(group, dict):
                                    for mem in group.get("memories", []):
                                        if isinstance(mem, dict):
                                            meta = mem.get("metadata") or {}
                                            hits.append({
                                                "id": mem.get("id"),
                                                "content": mem.get("memory") or mem.get("content", ""),
                                                "summary": mem.get("memory") or mem.get("content", ""),
                                                "original_excerpt": mem.get("memory"),
                                                "role": meta.get("role", ""),
                                                "createdAt": meta.get("created_at") or meta.get("timestamp", ""),
                                                "source": {"role": meta.get("role", ""), "ts": meta.get("created_at")},
                                            })
                took_ms = round((time.time() - t0) * 1000)
                logger.info(
                    "[memtensor] search | query=%r | hits=%d | took=%dms",
                    body["query"][:80], len(hits), took_ms,
                )
                return json.dumps({"result": {"hits": hits}})

            elif method == "ingest":
                t0 = time.time()
                # Convert messages [{role, content}] → [{type: "text", text: ...}, ...]
                msgs = params.get("messages", [])
                structured = []
                for m in msgs:
                    if isinstance(m, dict):
                        structured.append({
                            "chat_time": m.get("chat_time", ""),
                            "role": m.get("role", "user"),
                            "content": m.get("content", ""),
                        })
                    elif isinstance(m, str):
                        structured.append({
                            "role": "user",
                            "content": m,
                        })
                body = {
                    "user_id": owner,
                    "agent_id": self._agent_id,
                    "workspace_id": self._workspace_id,
                    "session_id": params.get("sessionId", "default"),
                    "messages": structured,
                    "async_mode": "async",
                }
                turn_id = params.get("turnId", "")
                if turn_id:
                    body["idempotency_key"] = f"{body['session_id']}:{turn_id}"
                r = self._requests.post(
                    f"{self._base_url}/product/add", json=body, timeout=120
                )
                took_ms = round((time.time() - t0) * 1000)
                logger.info(
                    "[memtensor] ingest | session_id=%s | msgs=%d | idempotency=%s | took=%dms",
                    body["session_id"], len(structured),
                    body.get("idempotency_key", "none"), took_ms,
                )
                return json.dumps({"result": r.json()})

            elif method == "recent":
                t0 = time.time()
                body = {
                    "user_id": owner,
                    "agent_id": self._agent_id,
                    "workspace_id": self._workspace_id,
                    "memory_type": "text_mem",
                }
                r = self._requests.post(
                    f"{self._base_url}/product/get_all", json=body, timeout=30
                )
                resp_data = r.json()
                took_ms = round((time.time() - t0) * 1000)
                items = 0
                if isinstance(resp_data, dict):
                    data = resp_data.get("data") or {}
                    if isinstance(data, dict):
                        items = len(data.get("memories", []))
                logger.info(
                    "[memtensor] recent | user_id=%s | items=%d | took=%dms",
                    owner, items, took_ms,
                )
                return json.dumps({"result": resp_data})

            elif method == "build_prompt":
                t0 = time.time()
                # MemOS doesn't have a separate build_prompt endpoint.
                # Simulate: search + format results as a prompt string.
                body = {
                    "user_id": owner,
                    "agent_id": self._agent_id,
                    "workspace_id": self._workspace_id,
                    "session_id": params.get("sessionId", "default"),
                    "query": params.get("query", ""),
                    "top_k": params.get("maxResults", 6),
                    "include_preference": True,
                    "include_skill_memory": True,
                    "search_tool_memory": True,
                }
                r = self._requests.post(
                    f"{self._base_url}/product/search", json=body, timeout=30
                )
                search_data = r.json()
                # Format results into a prompt string
                parts = []
                if search_data.get("code") == 200:
                    data = search_data.get("data", {})
                    for mem_type in ["text_mem", "pref_mem", "para_mem", "act_mem", "skill_mem", "tool_mem"]:
                        items = data.get(mem_type, [])
                        if isinstance(items, list):
                            for item in items:
                                if isinstance(item, dict):
                                    memories = item.get("memories", [])
                                    for mem in memories:
                                        content = mem.get("memory") or mem.get("content") or mem.get("text") or str(mem)
                                        if content:
                                            parts.append(content)
                prompt = "\n---\n".join(parts) if parts else "(No relevant memories found)"
                took_ms = round((time.time() - t0) * 1000)
                logger.info(
                    "[memtensor] build_prompt | query=%r | parts=%d | took=%dms",
                    body["query"][:80], len(parts), took_ms,
                )
                return json.dumps({"result": {"prompt": prompt, "memories": search_data.get("data", {})}})

            elif method == "flush":
                t0 = time.time()
                # REST is immediate, no-op
                return json.dumps({"result": {"status": "ok"}})

            elif method == "ping":
                t0 = time.time()
                r = self._requests.get(f"{self._base_url}/health", timeout=10)
                data = r.json()
                # Health returns {"status": "healthy", ...}
                ok = data.get("status") == "healthy"
                took_ms = round((time.time() - t0) * 1000)
                logger.info(
                    "[memtensor] ping | ok=%s | took=%dms", ok, took_ms,
                )
                return json.dumps({"result": {"pong": ok, "status": "ok" if ok else "error"}})

            else:
                return json.dumps({"result": {}})

        except Exception as e:
            logger.warning("HTTP transport error for method=%s: %s", method, e)
            return json.dumps({"error": str(e)})

    def close(self) -> None:
        pass


class _TcpTransport:
    def __init__(self, port: int, timeout: float = 120.0) -> None:
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._connect()

    def _connect(self) -> None:
        self._sock = socket.create_connection(("127.0.0.1", self._port), timeout=self._timeout)
        self._sock.settimeout(self._timeout)

    def send(self, data: str) -> str:
        assert self._sock is not None
        self._sock.sendall((data + "\n").encode())
        while b"\n" not in self._buffer:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise RuntimeError("Daemon closed connection")
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return line.decode("utf-8")

    def close(self) -> None:
        if self._sock:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None


class _StdioTransport:
    def __init__(self) -> None:
        bridge_cmd = find_bridge_script()
        env = {**os.environ}
        env["MEMOS_BRIDGE_CONFIG"] = json.dumps(get_bridge_config())

        logger.info("Starting bridge subprocess: %s", " ".join(bridge_cmd))
        self._proc = subprocess.Popen(
            bridge_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(_get_plugin_root()),
        )
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        assert self._proc.stderr is not None
        for raw_line in self._proc.stderr:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                logger.debug("[bridge] %s", line)

    def send(self, data: str) -> str:
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        self._proc.stdin.write((data + "\n").encode())
        self._proc.stdin.flush()
        line = self._proc.stdout.readline().decode("utf-8").strip()
        if not line:
            raise RuntimeError("Bridge process closed stdout unexpectedly")
        return line

    def close(self) -> None:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()


class MemosCoreBridge:
    """Communicate with the memos-core bridge. Auto-selects HTTP, TCP, or stdio."""

    def __init__(self, *, force_stdio: bool = False,
                 agent_id: str = "hermes",
                 workspace_id: str = "default") -> None:
        self._id = 0
        self._lock = threading.Lock()
        self._agent_id = agent_id
        self._workspace_id = workspace_id
        self._transport: _HttpTransport | _TcpTransport | _StdioTransport

        # Prefer HTTP (MemOS Full Server) if MEMOS_API_URL is set
        http_url = os.environ.get("MEMOS_API_URL", "")
        if http_url:
            logger.info("Connecting to MemOS REST API at %s", http_url)
            self._transport = _HttpTransport(http_url, agent_id=agent_id, workspace_id=workspace_id)
            result = self.call("ping")
            if result.get("status") == "ok":
                logger.info("MemOS transport selected: http (rest_api) → %s", http_url)
                return
            else:
                self._transport.close()
                logger.warning("MemOS REST API ping failed at %s, falling back", http_url)

        if not force_stdio:
            port = get_daemon_port()
            try:
                t = _TcpTransport(port, timeout=120.0)
                self._transport = t
                self._id = 0
                result = self.call("ping")
                if result.get("pong"):
                    logger.info("MemOS transport selected: tcp (daemon) → port %d", port)
                    return
                else:
                    t.close()
            except Exception as e:
                logger.debug("Daemon not available on port %d: %s", port, e)

        logger.info("MemOS transport selected: stdio (subprocess)")
        self._transport = _StdioTransport()

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            self._id += 1
            req = json.dumps({"id": self._id, "method": method, "params": params or {}})
            line = self._transport.send(req)
            resp = json.loads(line)
            if "error" in resp:
                raise RuntimeError(f"Bridge error: {resp['error']}")
            return resp.get("result", {})

    def search(
        self, query: str, max_results: int = 6, min_score: float = 0.45, owner: str = OWNER
    ) -> dict:
        return self.call(
            "search",
            {
                "query": query,
                "maxResults": max_results,
                "minScore": min_score,
                "owner": owner,
            },
        )

    def ingest(self, messages: list[dict], session_id: str = "default",
               turn_id: str = "", owner: str = OWNER) -> None:
        params: dict[str, Any] = {"messages": messages, "sessionId": session_id, "owner": owner}
        if turn_id:
            params["turnId"] = turn_id
        self.call("ingest", params)

    def build_prompt(self, query: str, max_results: int = 6, owner: str = OWNER) -> dict:
        return self.call(
            "build_prompt", {"query": query, "maxResults": max_results, "owner": owner}
        )

    def flush(self) -> None:
        self.call("flush")

    def ping(self) -> bool:
        try:
            result = self.call("ping")
            return result.get("pong", False) or result.get("status") == "ok"
        except Exception:
            return False

    def recent(self, limit: int = 20, owner: str = OWNER) -> dict:
        return self.call("recent", {"limit": limit, "owner": owner})

    def shutdown(self) -> None:
        self._transport.close()
