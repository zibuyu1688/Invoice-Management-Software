from __future__ import annotations

import socket
import threading
import time
import webbrowser

import uvicorn

from app.main import app as fastapi_app


def find_available_port(host: str, start_port: int, max_tries: int = 30) -> int:
    for offset in range(max_tries):
        port = start_port + offset
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
            return port
        except OSError:
            continue
        finally:
            sock.close()
    raise RuntimeError(f"从端口 {start_port} 开始连续尝试 {max_tries} 个端口都不可用")


def wait_until_server_ready(host: str, port: int, timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            time.sleep(0.2)
        finally:
            sock.close()
    return False


def run_server(host: str, port: int) -> None:
    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    bind_host = "0.0.0.0"
    browse_host = "127.0.0.1"
    start_port = 8765

    selected_port = find_available_port(browse_host, start_port)
    server_thread = threading.Thread(target=run_server, args=(bind_host, selected_port), daemon=True)
    server_thread.start()

    if wait_until_server_ready(browse_host, selected_port):
        webbrowser.open(f"http://{browse_host}:{selected_port}")

    # Keep main thread alive so packaged app does not exit.
    while True:
        time.sleep(3600)
