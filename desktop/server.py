from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

import requests
import uvicorn


def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(sock.getsockname()[1])


@dataclass
class LocalServerHandle:
    host: str
    port: int
    server: uvicorn.Server
    thread: threading.Thread

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def stop(self, timeout: float = 10.0) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=timeout)


def start_local_server(
    host: str = "127.0.0.1",
    port: int | None = None,
    log_level: str = "warning",
    startup_timeout: float = 15.0,
) -> LocalServerHandle:
    resolved_port = port or find_free_port(host)
    config = uvicorn.Config(
        "web_server:app",
        host=host,
        port=resolved_port,
        log_level=log_level,
        reload=False,
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(
        target=server.run,
        name="daily-recommender-local-server",
        daemon=True,
    )
    thread.start()

    base_url = f"http://{host}:{resolved_port}"
    deadline = time.time() + startup_timeout
    last_error: Exception | None = None

    while time.time() < deadline:
        if not thread.is_alive():
            raise RuntimeError("Local API server exited before startup completed.")

        try:
            response = requests.get(f"{base_url}/health", timeout=1.0)
            if response.ok:
                return LocalServerHandle(
                    host=host,
                    port=resolved_port,
                    server=server,
                    thread=thread,
                )
        except Exception as exc:  # pragma: no cover - best-effort startup polling
            last_error = exc

        time.sleep(0.2)

    if last_error:
        raise RuntimeError(f"Timed out waiting for local API server: {last_error}") from last_error
    raise RuntimeError("Timed out waiting for local API server.")
