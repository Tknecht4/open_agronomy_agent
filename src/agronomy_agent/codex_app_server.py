"""Portable Codex App Server transport for benchmark generation and judging.

The transport deliberately exposes only text generation.  Every turn is
ephemeral, read-only, network-disabled, and approval-free.  It records enough
protocol identity to make a result auditable without persisting credentials.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import queue
import subprocess
import tempfile
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Sequence


DEFAULT_CODEX_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "high"
DEFAULT_APP_SERVER_COMMAND = (
    "codex",
    "app-server",
    "--stdio",
    "--strict-config",
    "--disable",
    "browser_use",
    "--disable",
    "computer_use",
    "--disable",
    "image_generation",
    "--disable",
    "apps",
    "--disable",
    "in_app_browser",
    "--disable",
    "standalone_web_search",
    "-c",
    "mcp_servers={}",
)
TEXT_ONLY_BENCHMARK_CONTROL = (
    "TEXT-ONLY BENCHMARK TRANSPORT. Do not call, request, or simulate any tool, MCP server, "
    "shell command, browser, application, file operation, or network action. All tools are "
    "unavailable for this turn. Answer the supplied text directly and return only the requested "
    "answer or structured output."
)


class CodexAppServerError(RuntimeError):
    """Raised when the App Server protocol or a model turn fails closed."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AppServerResult:
    text: str
    receipt: dict[str, Any]


class CodexAppServerClient:
    """Small synchronous JSONL client for one local ``codex app-server`` process."""

    def __init__(
        self,
        *,
        command: Sequence[str] = DEFAULT_APP_SERVER_COMMAND,
        cwd: str | Path = "/private/tmp",
        timeout_seconds: float = 360.0,
        expected_model: str = DEFAULT_CODEX_MODEL,
        expected_reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        verify_catalog: bool = True,
        fail_on_reroute: bool = True,
        collect_protocol_identity: bool = True,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.command = tuple(str(value) for value in command)
        self.cwd = str(Path(cwd).resolve())
        self.timeout_seconds = float(timeout_seconds)
        self.expected_model = expected_model.strip()
        self.expected_reasoning_effort = expected_reasoning_effort.strip()
        self.verify_catalog = bool(verify_catalog)
        self.fail_on_reroute = bool(fail_on_reroute)
        self.collect_protocol_identity = bool(collect_protocol_identity)
        self._next_id = 0
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._pending_notifications: list[dict[str, Any]] = []
        self._closed = False
        self._process = subprocess.Popen(
            list(self.command),
            cwd=self.cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if self._process.stdin is None or self._process.stdout is None or self._process.stderr is None:
            self.close()
            raise CodexAppServerError("failed to open App Server stdio pipes")
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        atexit.register(self.close)
        try:
            self.initialize_result = self._request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "open-agronomy-benchmark",
                        "title": "Open Agronomy benchmark",
                        "version": "1",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            self._notify("initialized", {})
            self.protocol_identity = self._build_protocol_identity()
            self.catalog_model: dict[str, Any] | None = None
            if self.verify_catalog:
                self.catalog_model = self._verify_model_catalog()
        except Exception:
            self.close()
            raise

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                self._stdout_queue.put(line)
        finally:
            self._stdout_queue.put(None)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            self._stderr_lines.append(line.rstrip("\n"))
            if len(self._stderr_lines) > 2000:
                del self._stderr_lines[:1000]

    def _send(self, payload: dict[str, Any]) -> None:
        if self._closed or self._process.poll() is not None:
            raise CodexAppServerError(self._failure_message("App Server is not running"))
        assert self._process.stdin is not None
        self._process.stdin.write(_canonical_json(payload) + "\n")
        self._process.stdin.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def _read_message(self) -> dict[str, Any]:
        try:
            line = self._stdout_queue.get(timeout=self.timeout_seconds)
        except queue.Empty as exc:
            raise CodexAppServerError(self._failure_message("timed out waiting for App Server")) from exc
        if line is None:
            raise CodexAppServerError(self._failure_message("App Server closed stdout"))
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CodexAppServerError(f"App Server emitted invalid JSONL: {line[:500]!r}") from exc
        if not isinstance(payload, dict):
            raise CodexAppServerError("App Server JSONL message is not an object")
        return payload

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        self._send({"id": request_id, "method": method, "params": params})
        while True:
            payload = self._read_message()
            if payload.get("id") == request_id:
                if payload.get("error") is not None:
                    raise CodexAppServerError(f"App Server {method} error: {payload['error']}")
                result = payload.get("result")
                if not isinstance(result, dict):
                    raise CodexAppServerError(f"App Server {method} returned no object result")
                return result
            if "method" in payload and "id" not in payload:
                self._pending_notifications.append(payload)
                continue
            if "method" in payload and "id" in payload:
                raise CodexAppServerError(
                    f"App Server requested unsupported client action {payload.get('method')!r}; "
                    "benchmark turns must not request tools or approvals"
                )

    def _build_protocol_identity(self) -> dict[str, Any]:
        identity: dict[str, Any] = {
            "schema_version": "open_agronomy_agent.codex_app_server_protocol_identity.v1",
            "command": list(self.command),
            "initialize_result": self.initialize_result,
        }
        try:
            completed = subprocess.run(
                [self.command[0], "--version"],
                cwd=self.cwd,
                text=True,
                capture_output=True,
                check=False,
                timeout=20,
            )
            identity["codex_cli_version"] = completed.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            identity["codex_cli_version"] = None
        if not self.collect_protocol_identity:
            identity["protocol_schema_sha256"] = None
            return identity
        try:
            with tempfile.TemporaryDirectory(prefix="open-agronomy-app-server-") as temporary:
                schema_dir = Path(temporary)
                completed = subprocess.run(
                    [
                        self.command[0],
                        "app-server",
                        "generate-json-schema",
                        "--experimental",
                        "--out",
                        str(schema_dir),
                    ],
                    cwd=self.cwd,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=60,
                )
                schema = schema_dir / "codex_app_server_protocol.v2.schemas.json"
                identity["protocol_schema_sha256"] = (
                    hashlib.sha256(schema.read_bytes()).hexdigest()
                    if completed.returncode == 0 and schema.is_file()
                    else None
                )
        except (OSError, subprocess.SubprocessError):
            identity["protocol_schema_sha256"] = None
        return identity

    def _verify_model_catalog(self) -> dict[str, Any]:
        response = self._request("model/list", {"includeHidden": True})
        models = response.get("data")
        if not isinstance(models, list):
            raise CodexAppServerError("model/list did not return a model catalog")
        matches = [
            item
            for item in models
            if isinstance(item, dict)
            and self.expected_model in {str(item.get("id") or ""), str(item.get("model") or "")}
        ]
        if not matches:
            available = sorted(
                {str(item.get("model") or item.get("id") or "") for item in models if isinstance(item, dict)}
            )
            raise CodexAppServerError(
                f"requested model {self.expected_model!r} is not in the App Server catalog; "
                f"available={available}"
            )
        model = matches[0]
        efforts = {
            str(item.get("reasoningEffort") or "")
            for item in model.get("supportedReasoningEfforts") or []
            if isinstance(item, dict)
        }
        if efforts and self.expected_reasoning_effort not in efforts:
            raise CodexAppServerError(
                f"model {self.expected_model!r} does not advertise reasoning effort "
                f"{self.expected_reasoning_effort!r}; supported={sorted(efforts)}"
            )
        return model

    def generate(
        self,
        *,
        user_text: str,
        base_instructions: str,
        output_schema: dict[str, Any] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AppServerResult:
        started = perf_counter()
        self._pending_notifications.clear()
        controlled_instructions = (
            f"{TEXT_ONLY_BENCHMARK_CONTROL}\n\n{base_instructions.strip()}"
            if base_instructions.strip()
            else TEXT_ONLY_BENCHMARK_CONTROL
        )
        thread_result = self._request(
            "thread/start",
            {
                "model": self.expected_model,
                "cwd": self.cwd,
                "ephemeral": True,
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "baseInstructions": controlled_instructions,
                "allowProviderModelFallback": False,
                "environments": [],
                "dynamicTools": [],
                "config": {"web_search": "disabled"},
            },
        )
        thread = thread_result.get("thread") or {}
        thread_id = str(thread.get("id") or "")
        if not thread_id:
            raise CodexAppServerError("thread/start did not return a thread id")
        selected_model = str(thread_result.get("model") or self.expected_model)
        thread_default_effort = str(thread_result.get("reasoningEffort") or "") or None
        if selected_model != self.expected_model:
            raise CodexAppServerError(
                f"thread/start selected model {selected_model!r}, expected {self.expected_model!r}"
            )
        turn_result = self._request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": user_text}],
                "model": self.expected_model,
                "effort": self.expected_reasoning_effort,
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
                "environments": [],
                "outputSchema": output_schema,
                "responsesapiClientMetadata": metadata or {},
            },
        )
        turn = turn_result.get("turn") or {}
        turn_id = str(turn.get("id") or "")
        if not turn_id:
            raise CodexAppServerError("turn/start did not return a turn id")
        events = list(self._pending_notifications)
        self._pending_notifications.clear()
        completed_turn: dict[str, Any] | None = None
        while completed_turn is None:
            payload = self._read_message()
            if "method" in payload and "id" in payload:
                raise CodexAppServerError(
                    f"App Server requested unsupported client action {payload.get('method')!r}"
                )
            if "method" not in payload:
                continue
            events.append(payload)
            if payload.get("method") == "turn/completed":
                params = payload.get("params") or {}
                if params.get("threadId") == thread_id and (params.get("turn") or {}).get("id") == turn_id:
                    completed_turn = params.get("turn")
        if completed_turn.get("status") != "completed":
            raise CodexAppServerError(
                f"App Server turn failed: status={completed_turn.get('status')!r}, "
                f"error={completed_turn.get('error')!r}"
            )
        reroutes = [event.get("params") or {} for event in events if event.get("method") == "model/rerouted"]
        if reroutes and self.fail_on_reroute:
            raise CodexAppServerError(f"model reroute is forbidden for benchmark runs: {reroutes}")
        completed_item_types = Counter(
            str(((event.get("params") or {}).get("item") or {}).get("type") or "unknown")
            for event in events
            if event.get("method") == "item/completed"
        )
        allowed_item_types = {"userMessage", "agentMessage", "reasoning"}
        forbidden_item_types = {
            item_type: count
            for item_type, count in completed_item_types.items()
            if item_type not in allowed_item_types
        }
        if forbidden_item_types:
            forbidden_items = [
                (event.get("params") or {}).get("item") or {}
                for event in events
                if event.get("method") == "item/completed"
                and str(((event.get("params") or {}).get("item") or {}).get("type") or "unknown")
                in forbidden_item_types
            ]
            raise CodexAppServerError(
                "benchmark App Server turn used forbidden tools or item types: "
                f"{forbidden_item_types}; items={_canonical_json(forbidden_items)[:2000]}"
            )
        agent_messages = [
            (event.get("params") or {}).get("item") or {}
            for event in events
            if event.get("method") == "item/completed"
            and ((event.get("params") or {}).get("item") or {}).get("type") == "agentMessage"
        ]
        if not agent_messages:
            agent_messages = [
                item
                for item in completed_turn.get("items") or []
                if isinstance(item, dict) and item.get("type") == "agentMessage"
            ]
        text = "\n".join(str(item.get("text") or "").strip() for item in agent_messages).strip()
        if not text:
            raise CodexAppServerError("App Server completed without an agent message")
        usage_events = [event.get("params") or {} for event in events if event.get("method") == "thread/tokenUsage/updated"]
        token_usage = (usage_events[-1].get("tokenUsage") if usage_events else None) or {}
        event_records = [
            {
                "method": event.get("method"),
                "params_sha256": _sha256(_canonical_json(event.get("params") or {})),
            }
            for event in events
        ]
        receipt = {
            "schema_version": "open_agronomy_agent.codex_app_server_turn_receipt.v1",
            "protocol_identity": self.protocol_identity,
            "requested_model": self.expected_model,
            "requested_reasoning_effort": self.expected_reasoning_effort,
            "catalog_model": self.catalog_model,
            "selected_model": selected_model,
            "requested_turn_reasoning_effort": self.expected_reasoning_effort,
            "thread_default_reasoning_effort": thread_default_effort,
            "effective_turn_reasoning_effort_observed": False,
            "model_provider": thread_result.get("modelProvider") or thread.get("modelProvider"),
            "thread_id": thread_id,
            "turn_id": turn_id,
            "thread_ephemeral": bool(thread.get("ephemeral", True)),
            "sandbox": "read-only",
            "network_access": False,
            "approval_policy": "never",
            "transport_policy": "text_only_no_tools_v1",
            "reroutes": reroutes,
            "model_verifications": [
                event.get("params") or {} for event in events if event.get("method") == "model/verification"
            ],
            "token_usage": token_usage,
            "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
            "event_count": len(events),
            "event_method_counts": dict(Counter(str(event.get("method") or "unknown") for event in events)),
            "completed_item_type_counts": dict(completed_item_types),
            "event_stream_sha256": _sha256(_canonical_json(event_records)),
            "input_sha256": _sha256(user_text),
            "base_instructions_sha256": _sha256(controlled_instructions),
            "output_schema_sha256": _sha256(_canonical_json(output_schema)) if output_schema is not None else None,
            "output_sha256": _sha256(text),
        }
        return AppServerResult(text=text, receipt=receipt)

    def _failure_message(self, message: str) -> str:
        stderr = "\n".join(self._stderr_lines[-20:])
        return f"{message}: {stderr}" if stderr else message

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = getattr(self, "_process", None)
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    def __enter__(self) -> "CodexAppServerClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def split_chat_messages(messages: Iterable[dict[str, str]]) -> tuple[str, str]:
    """Map benchmark chat messages to App Server base instructions and user text."""

    instructions: list[str] = []
    conversation: list[str] = []
    for message in messages:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if role in {"system", "developer"}:
            instructions.append(content)
        elif role == "user":
            conversation.append(content)
        else:
            conversation.append(f"{role}: {content}")
    if not conversation:
        raise ValueError("App Server generation requires at least one user message")
    return "\n\n".join(instructions).strip(), "\n\n".join(conversation).strip()


class CodexAppServerGenerator:
    """Benchmark generator using ChatGPT-authenticated Codex App Server turns."""

    transport_control_active = True

    def __init__(
        self,
        model_id: str = DEFAULT_CODEX_MODEL,
        *,
        reasoning_effort: str = DEFAULT_REASONING_EFFORT,
        timeout_seconds: float = 360.0,
        command: Sequence[str] = DEFAULT_APP_SERVER_COMMAND,
        verify_catalog: bool = True,
    ) -> None:
        self.model_id = model_id
        self.reasoning_effort = reasoning_effort
        self.client = CodexAppServerClient(
            command=command,
            timeout_seconds=timeout_seconds,
            expected_model=model_id,
            expected_reasoning_effort=reasoning_effort,
            verify_catalog=verify_catalog,
        )
        self.model_identity = {
            "schema_version": "open_agronomy_agent.model_identity.v1",
            "model_id": model_id,
            "model_revision": None,
            "backend": "codex_app_server_chatgpt_auth",
            "request_model_id": model_id,
            "status": "catalog_verified" if self.client.catalog_model else "unverified_catalog",
            "protocol_identity": self.client.protocol_identity,
        }
        self.last_generation_stats: dict[str, Any] = {}

    def warmup(self) -> None:
        """Initialization and catalog verification happen in the constructor."""

    def generate(self, messages: list[dict[str, str]]) -> str:
        instructions, user_text = split_chat_messages(messages)
        result = self.client.generate(
            user_text=user_text,
            base_instructions=instructions,
            metadata={"application": "open-agronomy-benchmark", "role": "candidate"},
        )
        usage = result.receipt.get("token_usage") or {}
        last = usage.get("last") if isinstance(usage, dict) else {}
        last = last if isinstance(last, dict) else {}
        self.last_generation_stats = {
            "backend": "codex_app_server_chatgpt_auth",
            "request_model_id": self.model_id,
            "response_model_id": result.receipt.get("selected_model"),
            "prompt_tokens": last.get("inputTokens"),
            "cached_prompt_tokens": last.get("cachedInputTokens"),
            "generation_tokens": last.get("outputTokens"),
            "reasoning_output_tokens": last.get("reasoningOutputTokens"),
            "total_tokens": last.get("totalTokens"),
            "elapsed_ms": result.receipt.get("elapsed_ms"),
            "app_server_receipt": result.receipt,
            "model_identity": self.model_identity,
            "transport_control_active": True,
            "transport_control": "text_only_benchmark_control",
        }
        return result.text

    def close(self) -> None:
        self.client.close()
