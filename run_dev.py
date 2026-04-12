from pathlib import Path
import os
import socket
import sys

try:
    import uvicorn
except ModuleNotFoundError:
    project_root = Path(__file__).resolve().parent
    venv_python = project_root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    in_virtualenv = getattr(sys, "base_prefix", sys.prefix) != sys.prefix

    if venv_python.exists() and not in_virtualenv:
        os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve())])

    raise SystemExit(
        "未找到 uvicorn。请先执行: source .venv/bin/activate && pip install -r requirements.txt"
    )


if __name__ == "__main__":
    host = "127.0.0.1"
    start_port = 8765
    max_tries = 30

    def find_available_port(bind_host: str, begin: int, tries: int) -> int:
        for offset in range(tries):
            port = begin + offset
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind((bind_host, port))
                return port
            except OSError:
                continue
            finally:
                sock.close()

        raise RuntimeError(f"从端口 {begin} 开始连续尝试 {tries} 个端口都被占用")

    try:
        selected_port = find_available_port(host, start_port, max_tries)
    except RuntimeError as exc:
        raise SystemExit(str(exc))

    if selected_port != start_port:
        print(f"端口 {start_port} 已占用，自动切换到端口 {selected_port}")

    uvicorn.run("app.main:app", host=host, port=selected_port, reload=True)
