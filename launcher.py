from __future__ import annotations

import argparse
from html import escape
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib import error, request

APP_TITLE = "蜀丞票管"
APP_HOST = "127.0.0.1"
START_PORT = 8765
MAX_PORT_TRIES = 30
READY_TIMEOUT_SECONDS = 25.0


def render_shell_html(title: str, message: str, detail: str = "", *, tone: str = "loading") -> str:
        palette = {
                "loading": ("#0f172a", "#f8fafc", "#2563eb", "#475569"),
                "error": ("#3f1d1d", "#fff7f7", "#c62828", "#7f1d1d"),
        }
        background, surface, accent, text_muted = palette.get(tone, palette["loading"])
        detail_block = ""
        if detail.strip():
                detail_block = (
                        "<pre style=\"white-space:pre-wrap;overflow:auto;max-height:320px;"
                        "border-radius:14px;padding:16px;background:#0b1220;color:#dbeafe;"
                        "font:13px/1.6 Menlo, Monaco, monospace;\">"
                        f"{escape(detail)}"
                        "</pre>"
                )

        return f"""
<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(APP_TITLE)}</title>
    <style>
        :root {{
            color-scheme: light;
            font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            min-height: 100vh;
            display: grid;
            place-items: center;
            background: radial-gradient(circle at top, rgba(37,99,235,.16), transparent 40%), {background};
            color: #0f172a;
        }}
        .shell {{
            width: min(760px, calc(100vw - 48px));
            border-radius: 24px;
            padding: 28px;
            background: {surface};
            box-shadow: 0 30px 80px rgba(15, 23, 42, .22);
            border: 1px solid rgba(148, 163, 184, .25);
        }}
        .kicker {{
            margin: 0 0 10px;
            color: {accent};
            font-size: 12px;
            font-weight: 700;
            letter-spacing: .12em;
            text-transform: uppercase;
        }}
        h1 {{
            margin: 0;
            font-size: 30px;
            line-height: 1.2;
        }}
        p {{
            margin: 12px 0 0;
            font-size: 15px;
            line-height: 1.7;
            color: {text_muted};
        }}
        .status {{
            margin: 22px 0;
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 16px 18px;
            border-radius: 18px;
            background: rgba(148, 163, 184, .08);
        }}
        .dot {{
            width: 12px;
            height: 12px;
            border-radius: 999px;
            background: {accent};
            box-shadow: 0 0 0 10px rgba(37, 99, 235, .12);
            animation: pulse 1.4s ease-in-out infinite;
            flex: none;
        }}
        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); opacity: 1; }}
            50% {{ transform: scale(.78); opacity: .65; }}
        }}
        .tips {{
            margin-top: 18px;
            display: grid;
            gap: 10px;
            color: {text_muted};
            font-size: 14px;
        }}
    </style>
</head>
<body>
    <main class="shell">
        <p class="kicker">Desktop Launcher</p>
        <h1>{escape(title)}</h1>
        <div class="status">
            <div class="dot"></div>
            <div>
                <strong>{escape(message)}</strong>
                <p>启动器正在准备本地服务、数据库和界面窗口。</p>
            </div>
        </div>
        {detail_block}
        <div class="tips">
            <div>如果长时间停留在此界面，请稍后重试或检查数据目录权限。</div>
            <div>目录、数据库和错误详情都会被写入本机日志，便于定位问题。</div>
        </div>
    </main>
</body>
</html>
"""


def show_fatal_dialog(message: str) -> None:
        try:
                import tkinter
                from tkinter import messagebox

                root = tkinter.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                messagebox.showerror(APP_TITLE, message)
                root.destroy()
        except Exception:
                print(message, file=sys.stderr)


def ensure_runtime_environment() -> dict[str, str]:
    from app.config import APP_HOME, BACKUPS_DIR, DATA_DIR, DB_PATH, EXPORTS_DIR, FILES_DIR
    from app.database import initialize_sqlite_runtime

    APP_HOME.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    logs_dir = APP_HOME / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    try:
        initialize_sqlite_runtime()
    except Exception as exc:
        raise RuntimeError(f"数据库初始化失败：{exc}") from exc

    return {
        "app_home": str(APP_HOME),
        "db_path": str(DB_PATH),
        "logs_dir": str(logs_dir),
    }


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
def read_log_tail(log_path: Path, max_chars: int = 4000) -> str:
    if not log_path.exists():
        return ""
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return content[-max_chars:]


def summarize_health(payload: dict) -> str:
    failed_items = []
    for name, item in (payload.get("checks") or {}).items():
        if item.get("ok"):
            continue
        failed_items.append(f"- {name}: {item.get('detail', '未知错误')}")
    return "\n".join(failed_items)


def read_ready_payload(ready_url: str) -> tuple[int | None, dict | None]:
    try:
        with request.urlopen(ready_url, timeout=1.5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
            return exc.code, json.loads(body)
        except Exception:
            return exc.code, None
    except Exception:
        return None, None


def wait_until_server_ready(
    process: subprocess.Popen,
    ready_url: str,
    timeout: float = READY_TIMEOUT_SECONDS,
) -> dict:
    deadline = time.time() + timeout
    last_detail = "健康检查尚未通过。"
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("后端服务在启动过程中提前退出。")

        status_code, payload = read_ready_payload(ready_url)
        if payload:
            if status_code == 200 and payload.get("ok"):
                return payload
            summary = summarize_health(payload)
            if summary:
                last_detail = summary

        time.sleep(0.35)

    raise RuntimeError(f"后端健康检查超时。\n{last_detail}")


def stop_backend_process(process: subprocess.Popen | None) -> None:
    if not process or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def build_backend_command(port: int) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--serve", "--port", str(port)]
    return [sys.executable, str(Path(__file__).resolve()), "--serve", "--port", str(port)]


def start_backend_process(port: int, log_path: Path) -> tuple[subprocess.Popen, object]:
    log_handle = log_path.open("a", encoding="utf-8")
    log_handle.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] launcher start backend on port {port}\n")
    log_handle.flush()
    process = subprocess.Popen(
        build_backend_command(port),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        cwd=str(Path(__file__).resolve().parent),
        env=os.environ.copy(),
    )
    return process, log_handle


def run_server(host: str, port: int) -> None:
    import uvicorn
    from app.main import app as fastapi_app

    uvicorn.run(fastapi_app, host=host, port=port, log_level="info")


def update_window_shell(window, title: str, message: str, detail: str = "", *, tone: str = "loading") -> None:
    window.load_html(render_shell_html(title, message, detail, tone=tone))


def run_desktop_launcher() -> int:
    try:
        import webview
    except Exception as exc:
        show_fatal_dialog(f"无法加载桌面窗口组件 pywebview：{exc}")
        return 1

    window = webview.create_window(
        APP_TITLE,
        html=render_shell_html("初始化中", "正在准备本地工作台"),
        width=1680,
        height=1040,
        min_size=(1280, 820),
        text_select=True,
    )

    backend_ref: dict[str, subprocess.Popen | None] = {"process": None}

    def on_closed() -> None:
        stop_backend_process(backend_ref.get("process"))

    window.events.closed += on_closed

    def start_app() -> None:
        process = None
        log_handle = None
        log_path = Path.cwd() / "launcher.log"
        try:
            update_window_shell(window, "初始化中", "正在检查数据目录和数据库")
            runtime_paths = ensure_runtime_environment()
            log_path = Path(runtime_paths["logs_dir"]) / "launcher.log"

            update_window_shell(window, "服务启动中", "正在分配本地端口并启动服务进程")
            selected_port = find_available_port(APP_HOST, START_PORT, MAX_PORT_TRIES)
            process, log_handle = start_backend_process(selected_port, log_path)
            backend_ref["process"] = process

            update_window_shell(window, "健康检查中", "正在等待后端服务可用")
            base_url = f"http://{APP_HOST}:{selected_port}"
            health_payload = wait_until_server_ready(process, f"{base_url}/health/ready")

            detail_lines = [
                f"端口：{selected_port}",
                f"数据库：{runtime_paths['db_path']}",
                f"数据目录：{runtime_paths['app_home']}",
                f"状态：{health_payload.get('status', 'ready')}",
            ]
            update_window_shell(window, "界面加载中", "本地工作台已就绪，正在打开主界面", "\n".join(detail_lines))
            window.load_url(base_url)
        except Exception as exc:
            stop_backend_process(process)
            backend_ref["process"] = None
            detail = read_log_tail(log_path)
            full_message = str(exc)
            if detail:
                full_message = f"{full_message}\n\n最近日志：\n{detail}"
            update_window_shell(window, "启动失败", "未能启动本地工作台", full_message, tone="error")
        finally:
            if log_handle:
                log_handle.close()

    webview.start(start_app, debug=False)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=START_PORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.serve:
        run_server(APP_HOST, args.port)
        return 0
    return run_desktop_launcher()


if __name__ == "__main__":
    raise SystemExit(main())
