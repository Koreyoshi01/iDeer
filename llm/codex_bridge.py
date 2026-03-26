from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import requests


CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
DEFAULT_AUTH_FILE = os.path.expanduser("~/.codex/auth.json")
DEFAULT_ISSUER = "https://auth.openai.com"
DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_BRIDGE_URL = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}/v1"
DEFAULT_CLI_MODEL = "gpt-5.4"
DEFAULT_CLI_REASONING_EFFORT = "low"
PROACTIVE_REFRESH_DAYS = 8
DEFAULT_TIMEOUT = 60.0
PLATFORM_RETRY_COOLDOWN_SECONDS = 600


class CodexBridgeError(RuntimeError):
    pass


@dataclass
class CodexBridgeSettings:
    auth_file: Path
    issuer: str = DEFAULT_ISSUER
    api_base: str = DEFAULT_API_BASE
    timeout: float = DEFAULT_TIMEOUT
    proactive_refresh_days: int = PROACTIVE_REFRESH_DAYS
    write_back: bool = True
    cli_cmd: str = "codex"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8"))
        return json.loads(decoded)
    except Exception:
        return {}


def _extract_account_id(id_token: str | None) -> str | None:
    if not id_token:
        return None
    claims = _decode_jwt_payload(id_token)
    auth_claims = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claims, dict):
        account_id = auth_claims.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


def _token_claims_subset(id_token: str | None) -> dict[str, Any]:
    claims = _decode_jwt_payload(id_token or "")
    return {
        "organization_id": claims.get("organization_id"),
        "project_id": claims.get("project_id"),
        "completed_platform_onboarding": claims.get("completed_platform_onboarding"),
        "is_org_owner": claims.get("is_org_owner"),
    }


def _bridge_origin(bridge_url: str) -> str:
    parsed = urlparse(bridge_url)
    if not parsed.scheme or not parsed.netloc:
        raise CodexBridgeError(f"Invalid bridge URL: {bridge_url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _bridge_health_url(bridge_url: str) -> str:
    return f"{_bridge_origin(bridge_url)}/health"


def _bridge_host_port(bridge_url: str) -> tuple[str, int]:
    parsed = urlparse(bridge_url)
    host = parsed.hostname or DEFAULT_HOST
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return host, port


def _truncate(text: str, limit: int = 800) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _safe_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message") or error.get("error_description")
                if isinstance(message, str) and message:
                    return message
            message = payload.get("message") or payload.get("error_description")
            if isinstance(message, str) and message:
                return message
    except ValueError:
        pass
    text = (response.text or "").strip()
    return text or "Unknown error"


class CodexAuthManager:
    def __init__(self, settings: CodexBridgeSettings):
        self.settings = settings
        self._lock = threading.Lock()
        self._cli_lock = threading.Lock()
        self._cached_api_key: tuple[str, float] | None = None
        self._platform_cooldown_until = 0.0
        self._platform_cooldown_reason: str | None = None
        self._cli_binary = shutil.which(self.settings.cli_cmd)
        self._cli_workdir = Path(tempfile.mkdtemp(prefix="daily-recommender-codex-"))
        self._cli_home_dir, self._cli_auth_proxy = self._prepare_cli_home()

    def _prepare_cli_home(self) -> tuple[Path, Path | None]:
        auth_file = self.settings.auth_file
        if auth_file.name == "auth.json":
            return auth_file.parent, None

        cli_home = Path(tempfile.mkdtemp(prefix="daily-recommender-codex-home-"))
        proxy_auth = cli_home / "auth.json"
        proxy_auth.write_bytes(auth_file.read_bytes())
        os.chmod(proxy_auth, 0o600)
        return cli_home, proxy_auth

    def _sync_cli_auth_file(self) -> None:
        if self._cli_auth_proxy is None:
            return
        self._cli_auth_proxy.write_bytes(self.settings.auth_file.read_bytes())
        os.chmod(self._cli_auth_proxy, 0o600)

    def _codex_env(self) -> dict[str, str]:
        try:
            auth = self._load_auth()
            if self._is_refresh_stale(auth):
                self.refresh_chatgpt_tokens()
        except CodexBridgeError:
            pass

        env = os.environ.copy()
        env["CODEX_HOME"] = str(self._cli_home_dir)
        env.setdefault("NO_COLOR", "1")
        env.setdefault("TERM", "dumb")
        self._sync_cli_auth_file()
        return env

    def _load_auth(self) -> dict[str, Any]:
        if not self.settings.auth_file.exists():
            raise CodexBridgeError(
                f"Codex auth file not found: {self.settings.auth_file}"
            )
        try:
            with self.settings.auth_file.open("r", encoding="utf-8") as f:
                auth = json.load(f)
        except json.JSONDecodeError as exc:
            raise CodexBridgeError(
                f"Codex auth file is not valid JSON: {self.settings.auth_file}"
            ) from exc
        if not isinstance(auth, dict):
            raise CodexBridgeError("Codex auth payload must be a JSON object")
        return auth

    def _save_auth(self, auth: dict[str, Any]) -> None:
        if not self.settings.write_back:
            return
        self.settings.auth_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.settings.auth_file.parent),
            prefix=".auth.",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(auth, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.settings.auth_file)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        self._sync_cli_auth_file()

    def _is_refresh_stale(self, auth: dict[str, Any]) -> bool:
        last_refresh = _parse_iso_datetime(auth.get("last_refresh"))
        if last_refresh is None:
            return True
        return last_refresh < _utc_now() - timedelta(
            days=self.settings.proactive_refresh_days
        )

    def _chatgpt_tokens(self, auth: dict[str, Any]) -> dict[str, Any]:
        tokens = auth.get("tokens")
        if not isinstance(tokens, dict):
            raise CodexBridgeError("Codex auth file does not contain ChatGPT tokens")
        return tokens

    def _should_fallback_to_codex_cli(self, error: Exception) -> bool:
        message = str(error).lower()
        return (
            "missing organization_id" in message
            or "missing project_id" in message
            or "completed platform onboarding" in message
            or "finish setting up your api organization" in message
            or "invalid id token" in message
            or "token expired" in message
        )

    def _set_platform_cooldown(self, reason: str) -> None:
        self._platform_cooldown_until = time.time() + PLATFORM_RETRY_COOLDOWN_SECONDS
        self._platform_cooldown_reason = reason

    def _platform_cooldown_active(self) -> bool:
        return time.time() < self._platform_cooldown_until

    def refresh_chatgpt_tokens(self) -> dict[str, Any]:
        auth = self._load_auth()
        tokens = self._chatgpt_tokens(auth)
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise CodexBridgeError("Codex auth file does not contain a refresh token")

        response = requests.post(
            f"{self.settings.issuer.rstrip('/')}/oauth/token",
            headers={"Content-Type": "application/json"},
            json={
                "client_id": CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=self.settings.timeout,
        )
        if not response.ok:
            message = _safe_error_message(response)
            raise CodexBridgeError(
                f"Failed to refresh Codex ChatGPT tokens: {response.status_code} {message}"
            )

        payload = response.json()
        for field in ("id_token", "access_token", "refresh_token"):
            value = payload.get(field)
            if value:
                tokens[field] = value
        tokens["account_id"] = _extract_account_id(tokens.get("id_token")) or tokens.get(
            "account_id"
        )
        auth["auth_mode"] = auth.get("auth_mode") or "chatgpt"
        auth["last_refresh"] = _isoformat_utc(_utc_now())
        self._save_auth(auth)
        self._cached_api_key = None
        self._platform_cooldown_until = 0.0
        self._platform_cooldown_reason = None
        return auth

    def _exchange_id_token_for_api_key(self, id_token: str) -> str:
        body = urlencode(
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "client_id": CLIENT_ID,
                "requested_token": "openai-api-key",
                "subject_token": id_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
            }
        )
        response = requests.post(
            f"{self.settings.issuer.rstrip('/')}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=body,
            timeout=self.settings.timeout,
        )
        if not response.ok:
            message = _safe_error_message(response)
            raise CodexBridgeError(
                f"Failed to exchange Codex ID token for an OpenAI API key: "
                f"{response.status_code} {message}"
            )
        payload = response.json()
        api_key = payload.get("access_token")
        if not api_key:
            raise CodexBridgeError("Token exchange did not return an OpenAI API key")
        return api_key

    def get_api_key(self, force_refresh: bool = False) -> str:
        with self._lock:
            now = time.time()
            if (
                not force_refresh
                and self._cached_api_key is not None
                and now < self._cached_api_key[1]
            ):
                return self._cached_api_key[0]

            auth = self._load_auth()
            auth_mode = str(auth.get("auth_mode") or "").lower()
            explicit_api_key = auth.get("OPENAI_API_KEY")
            if explicit_api_key and auth_mode in ("", "api", "apikey", "api_key"):
                self._cached_api_key = (explicit_api_key, now + 600)
                return explicit_api_key

            if self._platform_cooldown_active() and not force_refresh:
                raise CodexBridgeError(
                    self._platform_cooldown_reason or "OpenAI API key exchange is unavailable"
                )

            if force_refresh or self._is_refresh_stale(auth):
                auth = self.refresh_chatgpt_tokens()

            tokens = self._chatgpt_tokens(auth)
            id_token = tokens.get("id_token")
            if not id_token:
                if not force_refresh:
                    auth = self.refresh_chatgpt_tokens()
                    tokens = self._chatgpt_tokens(auth)
                    id_token = tokens.get("id_token")
                if not id_token:
                    raise CodexBridgeError("Codex auth file does not contain an ID token")

            try:
                api_key = self._exchange_id_token_for_api_key(id_token)
            except CodexBridgeError as exc:
                if force_refresh:
                    if self._should_fallback_to_codex_cli(exc):
                        self._set_platform_cooldown(str(exc))
                    raise
                auth = self.refresh_chatgpt_tokens()
                tokens = self._chatgpt_tokens(auth)
                refreshed_id_token = tokens.get("id_token")
                if not refreshed_id_token:
                    raise CodexBridgeError("No ID token after refreshing Codex auth")
                try:
                    api_key = self._exchange_id_token_for_api_key(refreshed_id_token)
                except CodexBridgeError as refreshed_exc:
                    if self._should_fallback_to_codex_cli(refreshed_exc):
                        self._set_platform_cooldown(str(refreshed_exc))
                    raise refreshed_exc

            self._cached_api_key = (api_key, now + 600)
            return api_key

    def _platform_request(
        self,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
        retry_on_unauthorized: bool = True,
    ) -> requests.Response:
        api_key = self.get_api_key(force_refresh=False)
        response = requests.request(
            method,
            f"{self.settings.api_base.rstrip('/')}{path}",
            json=json_payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=self.settings.timeout,
        )
        if response.status_code == 401 and retry_on_unauthorized:
            self._cached_api_key = None
            refreshed_api_key = self.get_api_key(force_refresh=True)
            response = requests.request(
                method,
                f"{self.settings.api_base.rstrip('/')}{path}",
                json=json_payload,
                headers={"Authorization": f"Bearer {refreshed_api_key}"},
                timeout=self.settings.timeout,
            )
        return response

    def cli_available(self) -> bool:
        return self._cli_binary is not None

    def _models_cache_payload(self) -> dict[str, Any] | None:
        candidates = [
            self.settings.auth_file.parent / "models_cache.json",
            Path.home() / ".codex" / "models_cache.json",
        ]
        for path in candidates:
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return payload
        return None

    def _supported_cli_models(self) -> list[str]:
        payload = self._models_cache_payload()
        if not payload:
            return [DEFAULT_CLI_MODEL]

        models: list[str] = []
        for item in payload.get("models", []):
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            if not isinstance(slug, str) or not slug:
                continue
            if item.get("supported_in_api") is False:
                continue
            models.append(slug)

        return models or [DEFAULT_CLI_MODEL]

    def _resolve_cli_model(self, requested_model: str | None) -> str:
        supported_models = self._supported_cli_models()
        if requested_model and requested_model in supported_models:
            return requested_model
        if DEFAULT_CLI_MODEL in supported_models:
            return DEFAULT_CLI_MODEL
        return supported_models[0]

    def _resolve_cli_reasoning_effort(self, payload: dict[str, Any]) -> str:
        requested = str(
            payload.get("reasoning_effort")
            or os.getenv("CODEX_BRIDGE_CLI_REASONING_EFFORT")
            or DEFAULT_CLI_REASONING_EFFORT
        ).strip().lower()
        if requested in {"minimal", "low", "medium", "high", "xhigh"}:
            return requested
        return DEFAULT_CLI_REASONING_EFFORT

    def list_models_payload(self) -> dict[str, Any]:
        try:
            response = self._platform_request("GET", "/models")
            if response.ok:
                payload = response.json()
                if isinstance(payload, dict):
                    return payload
        except CodexBridgeError:
            pass

        return {
            "object": "list",
            "data": [
                {
                    "id": model,
                    "object": "model",
                    "created": 0,
                    "owned_by": "openai",
                }
                for model in self._supported_cli_models()
            ],
        }

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return ""

        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    parts.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type in ("text", "input_text", "output_text") and isinstance(
                item.get("text"), str
            ):
                text = item["text"].strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()

    def _chat_messages_to_prompt(self, messages: list[dict[str, Any]]) -> str:
        system_parts: list[str] = []
        transcript_parts: list[str] = []

        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user").strip().lower() or "user"
            text = self._content_to_text(message.get("content"))
            if not text:
                continue
            if role == "system":
                system_parts.append(text)
                continue
            transcript_parts.append(f"{role.upper()}:\n{text}")

        parts = [
            (
                "You are acting as the LLM backend for another application. "
                "Answer only from the conversation below. Do not inspect local files, "
                "run tools, or mention Codex CLI unless the conversation explicitly asks."
            )
        ]
        if system_parts:
            parts.append("SYSTEM INSTRUCTIONS:\n" + "\n\n".join(system_parts))
        if transcript_parts:
            parts.append("CONVERSATION:\n" + "\n\n".join(transcript_parts))
        parts.append(
            "Reply as the assistant to the final request. Return only the answer content, "
            "with no markdown fences unless the conversation explicitly asks for them."
        )
        return "\n\n".join(parts)

    def _responses_input_to_messages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []

        instructions = payload.get("instructions")
        if isinstance(instructions, str) and instructions.strip():
            messages.append({"role": "system", "content": instructions.strip()})

        input_items = payload.get("input", [])
        if isinstance(input_items, str):
            messages.append({"role": "user", "content": input_items})
            return messages

        if not isinstance(input_items, list):
            return messages

        for item in input_items:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                role = item.get("role", "user")
                content = item.get("content")
                messages.append({"role": role, "content": content})
                continue

            if item.get("type") == "input_text" and isinstance(item.get("text"), str):
                messages.append({"role": "user", "content": item["text"]})

        return messages

    def _payload_requests_search(self, payload: dict[str, Any]) -> bool:
        tools = payload.get("tools")
        if not isinstance(tools, list):
            return False
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            tool_type = str(tool.get("type") or "").lower()
            if "search" in tool_type:
                return True
        return False

    def _run_codex_exec(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.cli_available():
            raise CodexBridgeError(
                "Codex CLI is not installed or not available on PATH for codex_bridge mode"
            )

        model = self._resolve_cli_model(payload.get("model"))
        reasoning_effort = self._resolve_cli_reasoning_effort(payload)
        prompt = self._chat_messages_to_prompt(payload.get("messages", []))
        if not prompt.strip():
            prompt = "Reply with a brief acknowledgment."

        output_fd, output_path = tempfile.mkstemp(
            prefix="daily-recommender-codex-response-",
            suffix=".txt",
        )
        os.close(output_fd)

        cmd = [
            self._cli_binary or self.settings.cli_cmd,
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--color",
            "never",
            "--ephemeral",
            "--cd",
            str(self._cli_workdir),
            "--output-last-message",
            output_path,
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
        ]
        if self._payload_requests_search(payload):
            cmd.append("--search")
        cmd.append("-")

        try:
            with self._cli_lock:
                result = subprocess.run(
                    cmd,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=max(self.settings.timeout, 300.0),
                    env=self._codex_env(),
                    check=False,
                )
            try:
                with open(output_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
            except OSError:
                content = ""
        finally:
            try:
                os.unlink(output_path)
            except OSError:
                pass

        if result.returncode != 0:
            error_text = _truncate(result.stderr or result.stdout or "Unknown codex exec error")
            raise CodexBridgeError(
                f"Codex CLI backend failed with exit code {result.returncode}: {error_text}"
            )
        if not content:
            error_text = _truncate(result.stderr or result.stdout or "Empty Codex CLI response")
            raise CodexBridgeError(f"Codex CLI backend returned an empty response: {error_text}")

        return {
            "id": f"chatcmpl-codex-cli-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }

    def create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._platform_request(
                "POST",
                "/chat/completions",
                json_payload=payload,
            )
            if response.ok:
                data = response.json()
                if isinstance(data, dict):
                    return data

            message = _safe_error_message(response)
            error = CodexBridgeError(
                f"OpenAI upstream returned {response.status_code}: {message}"
            )
            if not self._should_fallback_to_codex_cli(error):
                raise error
            self._set_platform_cooldown(str(error))
        except CodexBridgeError as exc:
            if not self.cli_available():
                raise
            if not self._should_fallback_to_codex_cli(exc) and not self._platform_cooldown_active():
                raise

        return self._run_codex_exec(payload)

    def create_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        chat_payload = {
            "model": payload.get("model"),
            "messages": self._responses_input_to_messages(payload),
        }
        if payload.get("temperature") is not None:
            chat_payload["temperature"] = payload["temperature"]

        chat_response = self.create_chat_completion(chat_payload)
        message = (
            chat_response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        usage = chat_response.get("usage") if isinstance(chat_response.get("usage"), dict) else {}
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        return {
            "id": (chat_response.get("id") or f"resp-{int(time.time() * 1000)}").replace(
                "chatcmpl", "resp"
            ),
            "object": "response",
            "created_at": _isoformat_utc(_utc_now()),
            "model": chat_response.get("model") or payload.get("model") or DEFAULT_CLI_MODEL,
            "output_text": message,
            "output": [
                {
                    "id": f"msg-{int(time.time() * 1000)}",
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": message,
                            "annotations": [],
                        }
                    ],
                }
            ],
            "usage": {
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        }

    def health_payload(self) -> dict[str, Any]:
        auth = self._load_auth()
        tokens = auth.get("tokens") if isinstance(auth.get("tokens"), dict) else {}
        claim_subset = _token_claims_subset(tokens.get("id_token"))
        platform_ready = bool(claim_subset.get("organization_id")) and bool(
            claim_subset.get("project_id")
        )
        preferred_backend = "openai_api" if platform_ready and not self._platform_cooldown_active() else "codex_cli"
        return {
            "status": "ok",
            "auth_file": str(self.settings.auth_file),
            "auth_mode": auth.get("auth_mode"),
            "last_refresh": auth.get("last_refresh"),
            "stale": self._is_refresh_stale(auth),
            "has_openai_api_key": bool(auth.get("OPENAI_API_KEY")),
            "has_id_token": bool(tokens.get("id_token")),
            "has_refresh_token": bool(tokens.get("refresh_token")),
            "has_platform_organization_id": bool(claim_subset.get("organization_id")),
            "has_platform_project_id": bool(claim_subset.get("project_id")),
            "completed_platform_onboarding": claim_subset.get("completed_platform_onboarding"),
            "preferred_backend": preferred_backend,
            "platform_cooldown_active": self._platform_cooldown_active(),
            "platform_cooldown_reason": self._platform_cooldown_reason,
            "codex_cli_available": self.cli_available(),
            "codex_cli_model_default": self._resolve_cli_model(None),
        }


class _CodexBridgeHandler(BaseHTTPRequestHandler):
    manager: CodexAuthManager

    server_version = "DailyRecommenderCodexBridge/0.2"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length > 0 else b""

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, self.manager.health_payload())
            return
        if self.path == "/v1/models":
            self._send_json(200, self.manager.list_models_payload())
            return
        self._send_json(404, {"error": {"message": "Not found"}})

    def do_POST(self) -> None:
        if self.path not in ("/v1/chat/completions", "/v1/responses"):
            self._send_json(404, {"error": {"message": "Not found"}})
            return

        body = self._read_body()
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "Request body must be valid JSON"}})
            return

        if payload.get("stream") is True:
            self._send_json(
                501,
                {"error": {"message": "Streaming is not supported by the local Codex bridge yet"}},
            )
            return

        try:
            if self.path == "/v1/chat/completions":
                response_payload = self.manager.create_chat_completion(payload)
            else:
                response_payload = self.manager.create_response(payload)
        except CodexBridgeError as exc:
            self._send_json(502, {"error": {"message": str(exc)}})
            return

        self._send_json(200, response_payload)


def serve_bridge(
    host: str,
    port: int,
    auth_file: str,
    issuer: str = DEFAULT_ISSUER,
    api_base: str = DEFAULT_API_BASE,
    timeout: float = DEFAULT_TIMEOUT,
    write_back: bool = True,
) -> None:
    settings = CodexBridgeSettings(
        auth_file=Path(os.path.expanduser(auth_file)),
        issuer=issuer,
        api_base=api_base,
        timeout=timeout,
        write_back=write_back,
    )
    manager = CodexAuthManager(settings)
    _CodexBridgeHandler.manager = manager
    server = ThreadingHTTPServer((host, port), _CodexBridgeHandler)
    print(f"Codex bridge listening on http://{host}:{port}", flush=True)
    server.serve_forever()


def ensure_local_bridge(
    bridge_url: str,
    auth_file: str,
    issuer: str = DEFAULT_ISSUER,
    api_base: str = DEFAULT_API_BASE,
    startup_timeout: float = 15.0,
) -> subprocess.Popen[bytes] | None:
    health_url = _bridge_health_url(bridge_url)
    try:
        response = requests.get(health_url, timeout=0.8)
        if response.ok:
            return None
    except requests.RequestException:
        pass

    host, port = _bridge_host_port(bridge_url)
    if host not in {"127.0.0.1", "localhost"}:
        raise CodexBridgeError(
            f"Codex bridge is not reachable at {health_url}. "
            "Auto-start only works for localhost bridge URLs."
        )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "llm.codex_bridge",
            "--host",
            host,
            "--port",
            str(port),
            "--auth-file",
            auth_file,
            "--issuer",
            issuer,
            "--api-base",
            api_base,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + startup_timeout
    last_error: str | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            raise CodexBridgeError(
                f"Codex bridge exited early with code {process.returncode}"
            )
        try:
            response = requests.get(health_url, timeout=0.8)
            if response.ok:
                return process
            last_error = f"{response.status_code}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(0.25)

    process.terminate()
    raise CodexBridgeError(
        f"Timed out waiting for the Codex bridge at {health_url}"
        + (f" ({last_error})" if last_error else "")
    )


def stop_local_bridge(process: subprocess.Popen[bytes] | None) -> None:
    if process is None:
        return
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Codex auth bridge")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind")
    parser.add_argument(
        "--auth-file",
        default=DEFAULT_AUTH_FILE,
        help="Path to Codex auth.json",
    )
    parser.add_argument(
        "--issuer",
        default=DEFAULT_ISSUER,
        help="OAuth issuer base URL",
    )
    parser.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE,
        help="Target OpenAI API base URL",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--no-write-back",
        action="store_true",
        help="Do not persist refreshed tokens back to auth.json",
    )
    args = parser.parse_args()
    serve_bridge(
        host=args.host,
        port=args.port,
        auth_file=args.auth_file,
        issuer=args.issuer,
        api_base=args.api_base,
        timeout=args.timeout,
        write_back=not args.no_write_back,
    )


if __name__ == "__main__":
    main()
