from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import threading
from typing import Any, Callable
from uuid import uuid4


_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="invoice-job")
_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def create_background_job(
    job_type: str,
    target: Callable[..., None],
    *args,
    initial_message: str = "任务已创建",
    **kwargs,
) -> str:
    job_id = uuid4().hex
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "job_type": job_type,
            "status": "queued",
            "progress": 0,
            "message": initial_message,
            "error": "",
            "result": {},
            "created_at": now,
            "updated_at": now,
        }

    def runner() -> None:
        update_job(job_id, status="running", progress=5)
        try:
            target(job_id, *args, **kwargs)
        except Exception as exc:
            fail_job(job_id, str(exc))

    _executor.submit(runner)
    return job_id


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    message: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        if status is not None:
            job["status"] = status
        if progress is not None:
            job["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            job["message"] = message
        if result is not None:
            job["result"] = result
        if error is not None:
            job["error"] = error
        job["updated_at"] = now


def complete_job(job_id: str, result: dict[str, Any] | None = None, message: str = "任务已完成") -> None:
    update_job(job_id, status="completed", progress=100, message=message, result=result or {}, error="")


def fail_job(job_id: str, error_message: str) -> None:
    update_job(job_id, status="failed", progress=100, message="任务执行失败", error=error_message)


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return dict(job)