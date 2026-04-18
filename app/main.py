from collections import defaultdict
from datetime import date, datetime, timedelta
import json
import mimetypes
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import (
    APP_HOME,
    BACKUPS_DIR,
    EXPORTS_DIR,
    FILES_DIR,
    STATIC_DIR,
    TEMPLATES_DIR,
    get_deepseek_api_key,
    set_custom_app_home,
    set_custom_exports_dir,
    set_custom_files_dir,
    set_deepseek_api_key,
)
from .database import Base, SessionLocal, create_sqlite_backup, engine, get_db, get_sqlite_runtime_status
from .job_queue import complete_job, create_background_job, fail_job, get_job, update_job
from .models import Buyer, Invoice, InvoiceItem, Product, Seller, SellerSalesperson
from .services import (
    archive_invoice_file,
    create_invoice_with_items,
    export_customer_profile_xlsx,
    get_invoice_tax_rate,
    infer_invoice_number_from_filename,
    resolve_line_item_amounts,
)
from .task_helpers import (
    create_export_file,
    create_invoice_record,
    parse_invoice_filters,
    query_invoices,
    snapshot_upload_file,
    update_invoice_record,
)

Base.metadata.create_all(bind=engine)


def split_salesperson_names(raw_text: str) -> list[str]:
    tokens = re.split(r"[\n,，;；]+", raw_text or "")
    normalized: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        name = token.strip()
        if not name or name in seen:
            continue
        normalized.append(name)
        seen.add(name)
    return normalized


def ensure_sqlite_schema() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS seller_salespeople ("
                "id INTEGER PRIMARY KEY, "
                "seller_id INTEGER NOT NULL REFERENCES sellers(id) ON DELETE CASCADE, "
                "name VARCHAR(64) NOT NULL, "
                "phone VARCHAR(64), "
                "wechat VARCHAR(128), "
                "department VARCHAR(64), "
                "created_at DATETIME"
                ")"
            )
        )
        seller_salespeople_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(seller_salespeople)"))
        }
        if "phone" not in seller_salespeople_columns:
            conn.execute(text("ALTER TABLE seller_salespeople ADD COLUMN phone VARCHAR(64)"))
        if "wechat" not in seller_salespeople_columns:
            conn.execute(text("ALTER TABLE seller_salespeople ADD COLUMN wechat VARCHAR(128)"))
        if "department" not in seller_salespeople_columns:
            conn.execute(text("ALTER TABLE seller_salespeople ADD COLUMN department VARCHAR(64)"))

        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(buyers)"))
        }
        if "platform" not in columns:
            conn.execute(text("ALTER TABLE buyers ADD COLUMN platform VARCHAR(32)"))
        if "contact_person" not in columns:
            conn.execute(text("ALTER TABLE buyers ADD COLUMN contact_person VARCHAR(64)"))
        if "notes" not in columns:
            conn.execute(text("ALTER TABLE buyers ADD COLUMN notes TEXT"))
        if "contact_phone" not in columns:
            conn.execute(text("ALTER TABLE buyers ADD COLUMN contact_phone VARCHAR(64)"))
        if "wechat_qq" not in columns:
            conn.execute(text("ALTER TABLE buyers ADD COLUMN wechat_qq VARCHAR(128)"))
        if "address" not in columns:
            conn.execute(text("ALTER TABLE buyers ADD COLUMN address VARCHAR(255)"))
        if "shipping_address" not in columns:
            conn.execute(text("ALTER TABLE buyers ADD COLUMN shipping_address VARCHAR(255)"))
        if "bank_name" not in columns:
            conn.execute(text("ALTER TABLE buyers ADD COLUMN bank_name VARCHAR(128)"))
        if "bank_account_no" not in columns:
            conn.execute(text("ALTER TABLE buyers ADD COLUMN bank_account_no VARCHAR(128)"))

        seller_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(sellers)"))
        }
        if "salesperson" not in seller_columns:
            conn.execute(text("ALTER TABLE sellers ADD COLUMN salesperson VARCHAR(64)"))

        legacy_salespeople_rows = conn.execute(
            text("SELECT id, salesperson FROM sellers WHERE salesperson IS NOT NULL AND salesperson != ''")
        ).fetchall()
        for seller_id, salesperson in legacy_salespeople_rows:
            normalized_names = split_salesperson_names(str(salesperson or ""))
            for name in normalized_names:
                conn.execute(
                    text(
                        "INSERT INTO seller_salespeople (seller_id, name, created_at) "
                        "SELECT :seller_id, :name, :created_at "
                        "WHERE NOT EXISTS ("
                        "SELECT 1 FROM seller_salespeople WHERE seller_id = :seller_id AND name = :name"
                        ")"
                    ),
                    {
                        "seller_id": seller_id,
                        "name": name,
                        "created_at": datetime.utcnow(),
                    },
                )

        product_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(products)"))
        }
        if "group_name" not in product_columns:
            conn.execute(text("ALTER TABLE products ADD COLUMN group_name VARCHAR(128)"))

        invoice_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(invoices)"))
        }
        if "order_number" not in invoice_columns:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN order_number VARCHAR(64)"))
        if "order_date" not in invoice_columns:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN order_date DATE"))
        if "salesperson" not in invoice_columns:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN salesperson VARCHAR(64)"))
        if "trade_voucher_original_name" not in invoice_columns:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN trade_voucher_original_name VARCHAR(255)"))
        if "trade_voucher_stored_path" not in invoice_columns:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN trade_voucher_stored_path VARCHAR(500)"))
        if "trade_voucher_text" not in invoice_columns:
            conn.execute(text("ALTER TABLE invoices ADD COLUMN trade_voucher_text TEXT"))

        # Normalize legacy invoice status values for the new workflow.
        conn.execute(
            text(
                "UPDATE invoices SET status = '已开' "
                "WHERE status IS NULL OR status = '' OR status = '正常'"
            )
        )


ensure_sqlite_schema()


def build_salespeople_payload_from_names(names: list[str]) -> list[dict[str, str]]:
    return [{"name": name, "phone": "", "wechat": "", "department": ""} for name in names if name]


def normalize_salespeople_payload(payloads: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for payload in payloads:
        name = str(payload.get("name") or "").strip()
        if not name:
            continue
        phone = str(payload.get("phone") or "").strip()
        wechat = str(payload.get("wechat") or "").strip()
        department = str(payload.get("department") or "").strip()
        dedupe_key = (name, phone, wechat, department)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(
            {
                "name": name,
                "phone": phone,
                "wechat": wechat,
                "department": department,
            }
        )
    return normalized


def sync_seller_salespeople(seller: Seller, payloads: list[dict[str, str]]) -> None:
    seller.salespeople.clear()
    for payload in normalize_salespeople_payload(payloads):
        seller.salespeople.append(
            SellerSalesperson(
                name=payload["name"],
                phone=payload["phone"],
                wechat=payload["wechat"],
                department=payload["department"],
            )
        )


def parse_salespeople_form_lists(
    names: list[str], phones: list[str], wechats: list[str], departments: list[str]
) -> list[dict[str, str]]:
    max_len = max(len(names), len(phones), len(wechats), len(departments), 0)
    payloads: list[dict[str, str]] = []
    for index in range(max_len):
        payloads.append(
            {
                "name": names[index] if index < len(names) else "",
                "phone": phones[index] if index < len(phones) else "",
                "wechat": wechats[index] if index < len(wechats) else "",
                "department": departments[index] if index < len(departments) else "",
            }
        )
    return normalize_salespeople_payload(payloads)


def summarize_salespeople(salespeople: list[SellerSalesperson], limit: int = 3) -> tuple[str, list[str]]:
    names = [salesperson.name.strip() for salesperson in salespeople if salesperson.name.strip()]
    if not names:
        return ("暂无成员", [])
    if len(names) <= limit:
        return ("、".join(names), names)
    return ("、".join(names[:limit]) + f" +{len(names) - limit}", names)


def collect_salesperson_options(db: Session, sellers: list[Seller]) -> list[str]:
    return sorted(
        {
            salesperson.name.strip()
            for seller in sellers
            for salesperson in seller.salespeople
            if salesperson.name.strip()
        }
        | {
            (row[0] or "").strip()
            for row in db.query(Invoice.salesperson)
            .filter(Invoice.salesperson.isnot(None), Invoice.salesperson != "")
            .distinct()
            .all()
            if (row[0] or "").strip()
        }
    )


def build_runtime_health_snapshot() -> dict:
    db_status = None
    checks: dict[str, dict[str, str | bool]] = {
        "app_home": {
            "ok": APP_HOME.exists() and APP_HOME.is_dir(),
            "detail": str(APP_HOME),
        },
        "files_dir": {
            "ok": FILES_DIR.exists() and FILES_DIR.is_dir(),
            "detail": str(FILES_DIR),
        },
        "exports_dir": {
            "ok": EXPORTS_DIR.exists() and EXPORTS_DIR.is_dir(),
            "detail": str(EXPORTS_DIR),
        },
        "templates": {
            "ok": TEMPLATES_DIR.exists() and TEMPLATES_DIR.is_dir(),
            "detail": str(TEMPLATES_DIR),
        },
        "static": {
            "ok": STATIC_DIR.exists() and STATIC_DIR.is_dir(),
            "detail": str(STATIC_DIR),
        },
    }

    try:
        db_status = get_sqlite_runtime_status()
        checks["database"] = {
            "ok": bool(db_status["integrity_ok"]),
            "detail": f"journal_mode={db_status['journal_mode']}, busy_timeout={db_status['busy_timeout_ms']}ms, integrity={db_status['integrity_detail']}",
        }
    except Exception as exc:
        checks["database"] = {
            "ok": False,
            "detail": str(exc),
        }

    ready = all(bool(item["ok"]) for item in checks.values())
    return {
        "ok": ready,
        "status": "ready" if ready else "degraded",
        "checks": checks,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }

INVOICE_TYPE_OPTIONS = [
    "普通发票",
    "增值税发票",
]

INVOICE_TAX_RATE_OPTIONS = [0.01, 0.03, 0.13]

INVOICE_STATUS_OPTIONS = ["待开", "已开"]

app = FastAPI(title="蜀丞票管")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse(url="/static/favicon.ico", status_code=307)


@app.get("/health/live")
def health_live():
    return {
        "ok": True,
        "status": "live",
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


@app.get("/health/ready")
def health_ready():
    payload = build_runtime_health_snapshot()
    return JSONResponse(payload, status_code=200 if payload["ok"] else 503)


@app.get("/health/detail")
def health_detail():
    payload = build_runtime_health_snapshot()
    return JSONResponse(payload, status_code=200 if payload["ok"] else 503)


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.get("/api/jobs/{job_id}/download")
def download_job_result(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="任务尚未完成")
    result = job.get("result") or {}
    file_path_text = result.get("file_path")
    if not file_path_text:
        raise HTTPException(status_code=404, detail="任务结果文件不存在")
    file_path = Path(file_path_text)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="任务结果文件不存在")
    return FileResponse(
        file_path,
        filename=result.get("filename") or file_path.name,
        media_type=result.get("media_type") or mimetypes.guess_type(file_path.name)[0] or "application/octet-stream",
    )


def run_export_job(job_id: str, filters: dict) -> None:
    db = SessionLocal()
    try:
        update_job(job_id, progress=18, message="正在汇总筛选条件")
        export_path = create_export_file(db, filters)
        update_job(job_id, progress=92, message="正在生成发票与凭证图片包")
        complete_job(
            job_id,
            {
                "download_url": f"/api/jobs/{job_id}/download",
                "file_path": str(export_path),
                "filename": export_path.name,
                "media_type": "application/zip",
            },
            message="导出完成",
        )
    except HTTPException as exc:
        fail_job(job_id, str(exc.detail))
    except Exception as exc:
        fail_job(job_id, str(exc))
    finally:
        db.close()


def run_create_invoice_job(job_id: str, payload: dict) -> None:
    db = SessionLocal()
    try:
        update_job(job_id, progress=12, message="正在校验发票数据")
        if payload.get("invoice_file_snapshot"):
            update_job(job_id, progress=38, message="正在归档电子发票文件")
        invoice = create_invoice_record(db, **payload)
        complete_job(
            job_id,
            {
                "redirect_url": "/invoices",
                "invoice_id": invoice.id,
            },
            message="发票已保存",
        )
    except HTTPException as exc:
        fail_job(job_id, str(exc.detail))
    except Exception as exc:
        fail_job(job_id, str(exc))
    finally:
        db.close()


def run_update_invoice_job(job_id: str, payload: dict) -> None:
    db = SessionLocal()
    try:
        update_job(job_id, progress=12, message="正在校验发票修改内容")
        if payload.get("invoice_file_snapshot"):
            update_job(job_id, progress=38, message="正在归档或替换电子发票文件")
        invoice = update_invoice_record(db, **payload)
        complete_job(
            job_id,
            {
                "redirect_url": "/invoices",
                "invoice_id": invoice.id,
            },
            message="发票修改已保存",
        )
    except HTTPException as exc:
        fail_job(job_id, str(exc.detail))
    except Exception as exc:
        fail_job(job_id, str(exc))
    finally:
        db.close()


def resolve_invoice_file_or_404(invoice_id: int, db: Session) -> tuple[Invoice, Path]:
    invoice = db.get(Invoice, invoice_id)
    if not invoice or not invoice.file_stored_path:
        raise HTTPException(status_code=404, detail="文件不存在")

    file_path = Path(invoice.file_stored_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="归档文件不存在")

    return invoice, file_path


def resolve_trade_voucher_or_404(invoice_id: int, db: Session) -> tuple[Invoice, Path]:
    invoice = db.get(Invoice, invoice_id)
    if not invoice or not invoice.trade_voucher_stored_path:
        raise HTTPException(status_code=404, detail="交易凭证不存在")

    file_path = Path(invoice.trade_voucher_stored_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="交易凭证文件不存在")

    return invoice, file_path


def open_file_in_system(file_path: Path, *, reveal: bool = False) -> None:
    try:
        if sys.platform == "darwin":
            command = ["open"]
            if reveal:
                command.append("-R")
            command.append(str(file_path))
            subprocess.run(command, check=True)
            return

        if os.name == "nt":
            if reveal:
                subprocess.run(["explorer", f"/select,{file_path}"], check=True)
            else:
                os.startfile(str(file_path))
            return

        target = file_path.parent if reveal else file_path
        opener = shutil.which("xdg-open")
        if not opener:
            raise RuntimeError("当前系统缺少 xdg-open，无法打开文件")
        subprocess.run([opener, str(target)], check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"系统文件操作失败：{exc}") from exc
    except OSError as exc:
        raise RuntimeError(f"系统文件操作失败：{exc}") from exc


@app.get("/settings")
def settings_page(request: Request):
    deepseek_api_key = get_deepseek_api_key()
    masked_api_key = ""
    if deepseek_api_key:
        if len(deepseek_api_key) > 8:
            masked_api_key = f"{deepseek_api_key[:4]}...{deepseek_api_key[-4:]}"
        else:
            masked_api_key = "已设置"

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "current_app_home": str(APP_HOME),
            "current_files_dir": str(FILES_DIR),
            "current_exports_dir": str(EXPORTS_DIR),
            "current_backups_dir": str(BACKUPS_DIR),
            "database_status": get_sqlite_runtime_status(),
            "saved": request.query_params.get("saved", ""),
            "storage_paths_saved": request.query_params.get("storage_paths_saved", ""),
            "target_home": request.query_params.get("target_home", ""),
            "paths_saved": request.query_params.get("paths_saved", ""),
            "target_files_dir": request.query_params.get("target_files_dir", ""),
            "target_exports_dir": request.query_params.get("target_exports_dir", ""),
            "api_key_saved": request.query_params.get("api_key_saved", ""),
            "has_deepseek_api_key": "1" if deepseek_api_key else "0",
            "masked_deepseek_api_key": masked_api_key,
            "backup_saved": request.query_params.get("backup_saved", ""),
            "backup_file": request.query_params.get("backup_file", ""),
        },
    )


def _normalize_settings_path_override(raw_path: str, runtime_path: Path, default_path: Path) -> str:
    value = (raw_path or "").strip()
    if not value:
        return ""

    normalized_value = str(Path(value).expanduser())
    if normalized_value == str(runtime_path) and runtime_path == default_path:
        return ""
    return value


@app.post("/settings/storage")
def update_storage_setting(
    storage_path: str = Form(...),
    migrate_existing_data: str = Form("0"),
):
    new_home = set_custom_app_home(storage_path)

    if migrate_existing_data == "1":
        # Migrate current runtime data to new location; restart is still required.
        for folder_name in ["data", "files", "exports"]:
            src_dir = APP_HOME / folder_name
            dest_dir = new_home / folder_name
            if src_dir.exists() and src_dir.resolve() != dest_dir.resolve():
                dest_dir.mkdir(parents=True, exist_ok=True)
                for entry in src_dir.iterdir():
                    target = dest_dir / entry.name
                    if entry.is_dir():
                        shutil.copytree(entry, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(entry, target)

    return RedirectResponse(
        url=f"/settings?saved=1&target_home={new_home}",
        status_code=303,
    )


@app.post("/settings/storage-paths")
def update_storage_and_paths(
    storage_path: str = Form(...),
    migrate_existing_data: str = Form("0"),
    files_dir: str = Form(""),
    exports_dir: str = Form(""),
):
    new_home = set_custom_app_home(storage_path)

    if migrate_existing_data == "1":
        for folder_name in ["data", "files", "exports"]:
            src_dir = APP_HOME / folder_name
            dest_dir = new_home / folder_name
            if src_dir.exists() and src_dir.resolve() != dest_dir.resolve():
                dest_dir.mkdir(parents=True, exist_ok=True)
                for entry in src_dir.iterdir():
                    target = dest_dir / entry.name
                    if entry.is_dir():
                        shutil.copytree(entry, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(entry, target)

    target_files_dir = set_custom_files_dir(
        _normalize_settings_path_override(files_dir, FILES_DIR, APP_HOME / "files")
    )
    target_exports_dir = set_custom_exports_dir(
        _normalize_settings_path_override(exports_dir, EXPORTS_DIR, APP_HOME / "exports")
    )

    return RedirectResponse(
        url=(
            f"/settings?storage_paths_saved=1&target_home={new_home}"
            f"&target_files_dir={target_files_dir}&target_exports_dir={target_exports_dir}"
        ),
        status_code=303,
    )


@app.post("/settings/path-overrides")
def update_path_overrides(
    files_dir: str = Form(""),
    exports_dir: str = Form(""),
):
    target_files_dir = set_custom_files_dir(files_dir)
    target_exports_dir = set_custom_exports_dir(exports_dir)
    return RedirectResponse(
        url=f"/settings?paths_saved=1&target_files_dir={target_files_dir}&target_exports_dir={target_exports_dir}",
        status_code=303,
    )


@app.post("/settings/deepseek-api-key")
def update_deepseek_api_key(
    deepseek_api_key: str = Form(""),
):
    set_deepseek_api_key(deepseek_api_key)
    return RedirectResponse(url="/settings?api_key_saved=1", status_code=303)


@app.post("/api/settings/select-folder")
def select_folder_dialog():
    selected_path = ""

    if sys.platform == "darwin":
        script = (
            'set selectedFolder to POSIX path of (choose folder with prompt "选择目录")\n'
            'return selectedFolder'
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            # User canceled in AppleScript usually returns code -128.
            if "-128" in stderr or "User canceled" in stderr:
                return {"ok": False, "cancelled": True}
            return JSONResponse({"ok": False, "error": f"打开选择窗口失败: {stderr or '未知错误'}"}, status_code=500)
        selected_path = (result.stdout or "").strip()
    else:
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception:
            return JSONResponse({"ok": False, "error": "当前环境不支持系统文件夹选择窗口"}, status_code=500)

        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected_path = filedialog.askdirectory(title="选择目录")
            root.destroy()
        except Exception as exc:
            return JSONResponse({"ok": False, "error": f"打开选择窗口失败: {exc}"}, status_code=500)

    if not selected_path:
        return {"ok": False, "cancelled": True}

    return {"ok": True, "path": selected_path}


@app.post("/api/settings/open-app-home")
def open_app_home_in_system():
    try:
        open_file_in_system(APP_HOME, reveal=False)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True, "message": f"已打开目录：{APP_HOME}"}


@app.post("/api/settings/open-files-dir")
def open_files_dir_in_system():
    try:
        open_file_in_system(FILES_DIR, reveal=False)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True, "message": f"已打开目录：{FILES_DIR}"}


@app.post("/api/settings/open-exports-dir")
def open_exports_dir_in_system():
    try:
        open_file_in_system(EXPORTS_DIR, reveal=False)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True, "message": f"已打开目录：{EXPORTS_DIR}"}


@app.post("/api/settings/open-backups-dir")
def open_backups_dir_in_system():
    try:
        open_file_in_system(BACKUPS_DIR, reveal=False)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True, "message": f"已打开目录：{BACKUPS_DIR}"}


@app.post("/settings/database/backup")
def backup_database():
    backup_path = create_sqlite_backup()
    return RedirectResponse(
        url=f"/settings?backup_saved=1&backup_file={backup_path}",
        status_code=303,
    )


@app.get("/")
def index(
    request: Request,
    seller_id: str = Query(""),
    db: Session = Depends(get_db),
):
    sellers = db.query(Seller).order_by(Seller.name.asc()).all()
    selected_seller_id = None
    seller_id_text = seller_id.strip()
    if seller_id_text:
        try:
            selected_seller_id = int(seller_id_text)
        except ValueError:
            raise HTTPException(status_code=400, detail="销售方参数不正确")

    invoice_query = db.query(Invoice)
    if selected_seller_id is not None:
        invoice_query = invoice_query.filter(Invoice.seller_id == selected_seller_id)

    invoices = invoice_query.order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).all()
    today = date.today()
    month_begin = today.replace(day=1)

    def to_float(value) -> float:
        return float(value or 0.0)

    def is_abnormal(invoice: Invoice) -> bool:
        return (
            to_float(invoice.amount_with_tax) <= 0
            or (invoice.status == "已开" and not (invoice.invoice_number or "").strip())
            or (invoice.status == "已开" and not invoice.invoice_date)
        )

    def needs_completion(invoice: Invoice) -> bool:
        return (
            not (invoice.invoice_number or "").strip()
            or not (invoice.order_number or "").strip()
            or not (invoice.salesperson or "").strip()
            or invoice.buyer_id is None
        )

    seller_count = len(sellers)
    buyer_count = db.query(Buyer).count()
    invoice_count = len(invoices)
    total_amount = round(sum(to_float(inv.amount_with_tax) for inv in invoices), 2)

    today_amount = round(
        sum(to_float(inv.amount_with_tax) for inv in invoices if inv.invoice_date == today),
        2,
    )
    month_amount = round(
        sum(
            to_float(inv.amount_with_tax)
            for inv in invoices
            if inv.invoice_date and inv.invoice_date >= month_begin
        ),
        2,
    )
    pending_invoices = [inv for inv in invoices if inv.status == "待开"]
    abnormal_invoices = [inv for inv in invoices if is_abnormal(inv)]
    completion_invoices = [inv for inv in invoices if needs_completion(inv)]
    unarchived_invoices = [inv for inv in invoices if not inv.file_stored_path]

    recent_window = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    trend_rows = []
    max_trend_amount = 0.0
    for trend_day in recent_window:
        day_amount = round(
            sum(
                to_float(inv.amount_with_tax)
                for inv in invoices
                if inv.invoice_date == trend_day
            ),
            2,
        )
        max_trend_amount = max(max_trend_amount, day_amount)
        trend_rows.append(
            {
                "label": trend_day.strftime("%m-%d"),
                "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][trend_day.weekday()],
                "amount": day_amount,
            }
        )

    chart_width = 620
    chart_height = 220
    chart_padding_x = 20
    chart_padding_y = 22
    usable_width = chart_width - chart_padding_x * 2
    usable_height = chart_height - chart_padding_y * 2
    denominator = max_trend_amount if max_trend_amount > 0 else 1.0
    point_strings = []
    area_strings = [f"{chart_padding_x},{chart_height - chart_padding_y}"]
    chart_points = []
    for index, row in enumerate(trend_rows):
        x = chart_padding_x + (usable_width * index / max(len(trend_rows) - 1, 1))
        y = chart_height - chart_padding_y - (row["amount"] / denominator) * usable_height
        x_text = f"{x:.1f}"
        y_text = f"{y:.1f}"
        point_strings.append(f"{x_text},{y_text}")
        area_strings.append(f"{x_text},{y_text}")
        chart_points.append({"x": x_text, "y": y_text, **row})
    area_strings.append(f"{chart_width - chart_padding_x},{chart_height - chart_padding_y}")

    recent_invoices = invoices[:10]
    selected_seller = next((seller for seller in sellers if seller.id == selected_seller_id), None)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sellers": sellers,
            "selected_seller_id": selected_seller_id,
            "selected_seller_name": selected_seller.name if selected_seller else "全部主体",
            "seller_count": seller_count,
            "buyer_count": buyer_count,
            "invoice_count": invoice_count,
            "total_amount": total_amount,
            "today_amount": today_amount,
            "month_amount": month_amount,
            "pending_count": len(pending_invoices),
            "abnormal_count": len(abnormal_invoices),
            "completion_count": len(completion_invoices),
            "unarchived_count": len(unarchived_invoices),
            "task_cards": [
                {
                    "title": "待开票",
                    "count": len(pending_invoices),
                    "description": "需要尽快录入或完成开票处理",
                    "href": "/invoices?status=%E5%BE%85%E5%BC%80",
                    "tone": "warning",
                },
                {
                    "title": "待补信息",
                    "count": len(completion_invoices),
                    "description": "关键信息缺失，影响后续归档和对账",
                    "href": "/invoices",
                    "tone": "neutral",
                },
                {
                    "title": "待归档",
                    "count": len(unarchived_invoices),
                    "description": "电子发票原件尚未归档到系统",
                    "href": "/invoices",
                    "tone": "accent",
                },
                {
                    "title": "异常发票",
                    "count": len(abnormal_invoices),
                    "description": "开票状态与票面信息存在异常冲突",
                    "href": "/invoices",
                    "tone": "danger",
                },
            ],
            "quick_actions": [
                {"title": "录入发票", "subtitle": "进入高频主流程", "href": "/invoices/new", "tone": "primary"},
                {"title": "导出报表", "subtitle": "导出台账和经营数据", "href": "/export.xlsx", "tone": "secondary"},
                {"title": "客户管理", "subtitle": "维护购买方档案", "href": "/buyers", "tone": "secondary"},
                {"title": "数据罗盘", "subtitle": "查看趋势与结构洞察", "href": "/analytics", "tone": "secondary"},
            ],
            "trend_rows": trend_rows,
            "trend_points": " ".join(point_strings),
            "trend_area": " ".join(area_strings),
            "trend_chart_points": chart_points,
            "recent_invoices": recent_invoices,
        },
    )


@app.get("/analytics")
def analytics_page(
    request: Request,
    months: int = Query(6, ge=1, le=24),
    buyer_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    buyers = db.query(Buyer).order_by(Buyer.name.asc()).all()
    buyer_options = [{"id": b.id, "name": b.name} for b in buyers]
    products = db.query(Product).all()
    product_category_map = {
        (p.name or "").strip(): ((p.group_name or "").strip() or "未分组")
        for p in products
        if p.name
    }

    invoices = db.query(Invoice).order_by(Invoice.invoice_date.asc(), Invoice.id.asc()).all()
    today = date.today()

    total_count = len(invoices)
    total_amount = round(sum(float(inv.amount_with_tax or 0.0) for inv in invoices), 2)
    avg_amount = round((total_amount / total_count), 2) if total_count else 0.0

    month_begin = today.replace(day=1)
    last_month_end = month_begin - timedelta(days=1)
    last_month_begin = last_month_end.replace(day=1)

    current_month_amount = 0.0
    last_month_amount = 0.0

    status_counts: dict[str, int] = defaultdict(int)
    status_amounts: dict[str, float] = defaultdict(float)
    type_counts: dict[str, int] = defaultdict(int)
    type_amounts: dict[str, float] = defaultdict(float)
    buyer_amounts: dict[str, float] = defaultdict(float)
    buyer_counts: dict[str, int] = defaultdict(int)
    buyer_last_purchase: dict[str, date] = {}
    platform_amounts: dict[str, float] = defaultdict(float)
    monthly_amounts: dict[str, float] = defaultdict(float)
    monthly_counts: dict[str, int] = defaultdict(int)
    product_amounts: dict[str, float] = defaultdict(float)
    product_quantities: dict[str, float] = defaultdict(float)
    spec_amounts: dict[str, float] = defaultdict(float)
    spec_quantities: dict[str, float] = defaultdict(float)
    customer_dates: dict[str, list[date]] = defaultdict(list)
    customer_amount_details: dict[str, list[float]] = defaultdict(list)
    customer_product_amounts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    customer_product_quantities: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    customer_spec_amounts: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    customer_spec_quantities: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    pending_aging: dict[str, int] = {
        "0-7天": 0,
        "8-15天": 0,
        "16-30天": 0,
        "31天以上": 0,
    }

    for inv in invoices:
        amount = float(inv.amount_with_tax or 0.0)
        inv_date = inv.invoice_date or today

        status_key = (inv.status or "未标记").strip() or "未标记"
        type_key = (inv.invoice_type or "未标记").strip() or "未标记"
        buyer_key = inv.buyer.name if inv.buyer and inv.buyer.name else "未知客户"
        platform_key = "未填写平台"
        if inv.buyer and inv.buyer.platform and inv.buyer.platform.strip():
            platform_key = inv.buyer.platform.strip()

        status_counts[status_key] += 1
        status_amounts[status_key] += amount
        type_counts[type_key] += 1
        type_amounts[type_key] += amount
        buyer_amounts[buyer_key] += amount
        buyer_counts[buyer_key] += 1
        platform_amounts[platform_key] += amount
        customer_dates[buyer_key].append(inv_date)
        customer_amount_details[buyer_key].append(amount)
        if buyer_key not in buyer_last_purchase or inv_date > buyer_last_purchase[buyer_key]:
            buyer_last_purchase[buyer_key] = inv_date

        month_key = inv_date.strftime("%Y-%m")
        monthly_amounts[month_key] += amount
        monthly_counts[month_key] += 1

        for item in inv.items:
            product_name = (item.product_name or "未命名商品").strip() or "未命名商品"
            spec_name = (item.spec_model or "未填规格").strip() or "未填规格"
            qty = float(item.quantity or 0.0)
            item_amount = float(item.total_with_tax or 0.0)

            product_amounts[product_name] += item_amount
            product_quantities[product_name] += qty
            spec_amounts[spec_name] += item_amount
            spec_quantities[spec_name] += qty

            customer_product_amounts[buyer_key][product_name] += item_amount
            customer_product_quantities[buyer_key][product_name] += qty
            customer_spec_amounts[buyer_key][spec_name] += item_amount
            customer_spec_quantities[buyer_key][spec_name] += qty

        if inv_date >= month_begin:
            current_month_amount += amount
        if last_month_begin <= inv_date <= last_month_end:
            last_month_amount += amount

        if status_key == "待开":
            age_days = max((today - inv_date).days, 0)
            if age_days <= 7:
                pending_aging["0-7天"] += 1
            elif age_days <= 15:
                pending_aging["8-15天"] += 1
            elif age_days <= 30:
                pending_aging["16-30天"] += 1
            else:
                pending_aging["31天以上"] += 1

    def month_shift(src: date, offset: int) -> date:
        month_index = src.month - 1 + offset
        year = src.year + month_index // 12
        month = month_index % 12 + 1
        return date(year, month, 1)

    start_month = month_shift(month_begin, -(months - 1))
    monthly_trend = []
    max_monthly_amount = 0.0
    for idx in range(months):
        point = month_shift(start_month, idx)
        key = point.strftime("%Y-%m")
        amount = round(monthly_amounts.get(key, 0.0), 2)
        count = monthly_counts.get(key, 0)
        monthly_trend.append({"month": key, "amount": amount, "count": count})
        max_monthly_amount = max(max_monthly_amount, amount)

    if max_monthly_amount <= 0:
        max_monthly_amount = 1.0
    for row in monthly_trend:
        row["amount_ratio"] = round(row["amount"] / max_monthly_amount * 100, 2)

    status_items = []
    for key, count in sorted(status_counts.items(), key=lambda x: x[1], reverse=True):
        amount = round(status_amounts.get(key, 0.0), 2)
        status_items.append(
            {
                "name": key,
                "count": count,
                "amount": amount,
                "count_ratio": round((count / total_count * 100), 2) if total_count else 0.0,
            }
        )

    type_items = []
    for key, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        amount = round(type_amounts.get(key, 0.0), 2)
        type_items.append(
            {
                "name": key,
                "count": count,
                "amount": amount,
                "count_ratio": round((count / total_count * 100), 2) if total_count else 0.0,
            }
        )

    top_buyers = []
    for name, amount in sorted(buyer_amounts.items(), key=lambda x: x[1], reverse=True)[:10]:
        last_purchase = buyer_last_purchase.get(name)
        days_since_last = (today - last_purchase).days if last_purchase else None
        top_buyers.append(
            {
                "name": name,
                "amount": round(amount, 2),
                "ratio": round((amount / total_amount * 100), 2) if total_amount else 0.0,
                "count": buyer_counts.get(name, 0),
                "last_purchase_date": last_purchase.isoformat() if last_purchase else "",
                "days_since_last": days_since_last,
            }
        )

    top_platforms = []
    for name, amount in sorted(platform_amounts.items(), key=lambda x: x[1], reverse=True)[:5]:
        top_platforms.append(
            {
                "name": name,
                "amount": round(amount, 2),
                "ratio": round((amount / total_amount * 100), 2) if total_amount else 0.0,
            }
        )

    pending_total = sum(pending_aging.values())
    pending_items = [
        {
            "bucket": bucket,
            "count": count,
            "ratio": round((count / pending_total * 100), 2) if pending_total else 0.0,
        }
        for bucket, count in pending_aging.items()
    ]

    mom_change = 0.0
    if last_month_amount > 0:
        mom_change = round((current_month_amount - last_month_amount) / last_month_amount * 100, 2)
    elif current_month_amount > 0:
        mom_change = 100.0

    total_item_amount = sum(product_amounts.values())
    total_item_quantity = sum(product_quantities.values())

    top_products = []
    for name, amount in sorted(product_amounts.items(), key=lambda x: x[1], reverse=True)[:12]:
        qty = round(product_quantities.get(name, 0.0), 2)
        top_products.append(
            {
                "name": name,
                "amount": round(amount, 2),
                "quantity": qty,
                "amount_ratio": round((amount / total_item_amount * 100), 2) if total_item_amount else 0.0,
                "quantity_ratio": round((qty / total_item_quantity * 100), 2) if total_item_quantity else 0.0,
            }
        )

    top_specs = []
    for name, amount in sorted(spec_amounts.items(), key=lambda x: x[1], reverse=True)[:12]:
        qty = round(spec_quantities.get(name, 0.0), 2)
        top_specs.append(
            {
                "name": name,
                "amount": round(amount, 2),
                "quantity": qty,
                "amount_ratio": round((amount / total_item_amount * 100), 2) if total_item_amount else 0.0,
                "quantity_ratio": round((qty / total_item_quantity * 100), 2) if total_item_quantity else 0.0,
            }
        )

    customer_segment = {
        "active": 0,
        "risk": 0,
        "dormant": 0,
        "new": 0,
    }
    dormant_customers = []
    for b in buyers:
        last_purchase = buyer_last_purchase.get(b.name)
        if not last_purchase:
            customer_segment["new"] += 1
            dormant_customers.append({"name": b.name, "days_since_last": "从未购买", "amount": 0.0})
            continue

        days_since = (today - last_purchase).days
        if days_since <= 30:
            customer_segment["active"] += 1
        elif days_since <= 90:
            customer_segment["risk"] += 1
        else:
            customer_segment["dormant"] += 1

        if days_since > 30:
            dormant_customers.append(
                {
                    "name": b.name,
                    "days_since_last": days_since,
                    "amount": round(buyer_amounts.get(b.name, 0.0), 2),
                }
            )

    dormant_customers.sort(
        key=lambda row: row["days_since_last"] if isinstance(row["days_since_last"], int) else 999999,
        reverse=True,
    )
    dormant_customers = dormant_customers[:10]

    selected_buyer = None
    selected_customer = None
    if buyer_id:
        selected_buyer = db.get(Buyer, buyer_id)

    if selected_buyer:
        key = selected_buyer.name
        selected_dates = sorted(customer_dates.get(key, []))
        selected_amounts = customer_amount_details.get(key, [])
        selected_total_amount = round(sum(selected_amounts), 2)
        selected_total_count = len(selected_amounts)
        selected_first_date = selected_dates[0] if selected_dates else None
        selected_last_date = selected_dates[-1] if selected_dates else None
        selected_days_since_last = (today - selected_last_date).days if selected_last_date else None
        selected_avg_amount = round((selected_total_amount / selected_total_count), 2) if selected_total_count else 0.0

        selected_avg_interval = None
        selected_max_interval = None
        if len(selected_dates) >= 2:
            gaps = [(selected_dates[idx] - selected_dates[idx - 1]).days for idx in range(1, len(selected_dates))]
            selected_avg_interval = round(sum(gaps) / len(gaps), 2)
            selected_max_interval = max(gaps)

        selected_monthly_map: dict[str, float] = defaultdict(float)
        for inv in invoices:
            if inv.buyer_id != selected_buyer.id:
                continue
            inv_date = inv.invoice_date or today
            selected_monthly_map[inv_date.strftime("%Y-%m")] += float(inv.amount_with_tax or 0.0)

        selected_monthly_trend = []
        selected_max_monthly = 0.0
        for idx in range(months):
            point = month_shift(start_month, idx)
            month_key = point.strftime("%Y-%m")
            amount = round(selected_monthly_map.get(month_key, 0.0), 2)
            selected_monthly_trend.append({"month": month_key, "amount": amount})
            selected_max_monthly = max(selected_max_monthly, amount)
        if selected_max_monthly <= 0:
            selected_max_monthly = 1.0
        for row in selected_monthly_trend:
            row["ratio"] = round(row["amount"] / selected_max_monthly * 100, 2)

        selected_12m_trend = []
        selected_12m_max_amount = 0.0
        twelve_month_start = month_shift(month_begin, -11)
        for idx in range(12):
            point = month_shift(twelve_month_start, idx)
            month_key = point.strftime("%Y-%m")
            amount = round(selected_monthly_map.get(month_key, 0.0), 2)
            selected_12m_trend.append({"month": month_key, "amount": amount})
            selected_12m_max_amount = max(selected_12m_max_amount, amount)
        if selected_12m_max_amount <= 0:
            selected_12m_max_amount = 1.0

        chart_width = 760
        chart_height = 260
        chart_padding_left = 48
        chart_padding_right = 18
        chart_padding_top = 18
        chart_padding_bottom = 36
        usable_width = chart_width - chart_padding_left - chart_padding_right
        usable_height = chart_height - chart_padding_top - chart_padding_bottom
        point_count = max(len(selected_12m_trend) - 1, 1)
        trend_12m_points: list[str] = []
        trend_12m_dots = []
        trend_12m_labels = []

        for idx, row in enumerate(selected_12m_trend):
            x = chart_padding_left + usable_width * idx / point_count
            y = chart_padding_top + usable_height * (1 - row["amount"] / selected_12m_max_amount)
            trend_12m_points.append(f"{round(x, 2)},{round(y, 2)}")
            trend_12m_dots.append({"cx": round(x, 2), "cy": round(y, 2), "month": row["month"], "amount": row["amount"]})
            trend_12m_labels.append({"x": round(x, 2), "y": chart_height - 10, "text": row["month"][5:]})

        trend_12m_y_axis_labels = [
            {"x": 4, "y": chart_padding_top + 6, "text": round(selected_12m_max_amount, 2)},
            {"x": 4, "y": chart_padding_top + usable_height / 2 + 6, "text": round(selected_12m_max_amount / 2, 2)},
            {"x": 18, "y": chart_padding_top + usable_height + 6, "text": 0},
        ]

        customer_product_amount_map = customer_product_amounts.get(key, {})
        customer_product_qty_map = customer_product_quantities.get(key, {})
        customer_spec_amount_map = customer_spec_amounts.get(key, {})
        customer_spec_qty_map = customer_spec_quantities.get(key, {})

        selected_total_item_amount = sum(customer_product_amount_map.values())
        selected_total_item_qty = sum(customer_product_qty_map.values())

        selected_invoices = [inv for inv in invoices if inv.buyer_id == selected_buyer.id]
        selected_invoices.sort(key=lambda inv: ((inv.invoice_date or today), inv.id), reverse=True)

        recent_purchase_details = []
        product_order_frequency: dict[str, int] = defaultdict(int)
        category_amount_map: dict[str, float] = defaultdict(float)
        category_qty_map: dict[str, float] = defaultdict(float)
        recent_3m_category_amounts: dict[str, float] = defaultdict(float)
        prev_3m_category_amounts: dict[str, float] = defaultdict(float)
        recent_6m_category_amounts: dict[str, float] = defaultdict(float)
        order_quantity_buckets = {"1-5": 0, "6-20": 0, "21以上": 0}
        order_item_type_buckets = {"1种": 0, "2-3种": 0, "4种以上": 0}
        monthly_order_count = 0
        quarterly_order_count = 0
        yearly_order_count = 0

        recent_3m_start = today - timedelta(days=90)
        prev_3m_start = today - timedelta(days=180)
        recent_6m_start = today - timedelta(days=180)
        recent_30d_start = today - timedelta(days=30)
        recent_90d_start = today - timedelta(days=90)
        recent_365d_start = today - timedelta(days=365)

        for inv in selected_invoices:
            inv_date = inv.invoice_date or today
            total_qty = 0.0
            product_names_in_invoice: set[str] = set()
            item_names = []
            for item in inv.items:
                product_name = (item.product_name or "未命名商品").strip() or "未命名商品"
                category_name = product_category_map.get(product_name, "未分组")
                qty = float(item.quantity or 0.0)
                total_with_tax = float(item.total_with_tax or 0.0)

                total_qty += qty
                item_names.append(product_name)
                product_names_in_invoice.add(product_name)
                category_amount_map[category_name] += total_with_tax
                category_qty_map[category_name] += qty

                if inv_date >= recent_3m_start:
                    recent_3m_category_amounts[category_name] += total_with_tax
                elif prev_3m_start <= inv_date < recent_3m_start:
                    prev_3m_category_amounts[category_name] += total_with_tax
                if inv_date >= recent_6m_start:
                    recent_6m_category_amounts[category_name] += total_with_tax

            for product_name in product_names_in_invoice:
                product_order_frequency[product_name] += 1

            if inv_date >= recent_30d_start:
                monthly_order_count += 1
            if inv_date >= recent_90d_start:
                quarterly_order_count += 1
            if inv_date >= recent_365d_start:
                yearly_order_count += 1

            if total_qty <= 5:
                order_quantity_buckets["1-5"] += 1
            elif total_qty <= 20:
                order_quantity_buckets["6-20"] += 1
            else:
                order_quantity_buckets["21以上"] += 1

            item_type_count = len(product_names_in_invoice)
            if item_type_count <= 1:
                order_item_type_buckets["1种"] += 1
            elif item_type_count <= 3:
                order_item_type_buckets["2-3种"] += 1
            else:
                order_item_type_buckets["4种以上"] += 1

            recent_purchase_details.append(
                {
                    "invoice_number": inv.invoice_number,
                    "invoice_date": inv_date.isoformat(),
                    "amount": round(float(inv.amount_with_tax or 0.0), 2),
                    "quantity": round(total_qty, 2),
                    "product_summary": "、".join(item_names[:3]) + (" 等" if len(item_names) > 3 else ""),
                    "status": inv.status or "",
                }
            )

        recent_purchase_details = recent_purchase_details[:10]

        selected_top_products = []
        for name, amount in sorted(customer_product_amount_map.items(), key=lambda x: x[1], reverse=True)[:5]:
            qty = round(customer_product_qty_map.get(name, 0.0), 2)
            selected_top_products.append(
                {
                    "name": name,
                    "amount": round(amount, 2),
                    "quantity": qty,
                    "frequency": product_order_frequency.get(name, 0),
                    "amount_ratio": round((amount / selected_total_item_amount * 100), 2) if selected_total_item_amount else 0.0,
                }
            )

        total_category_amount = sum(category_amount_map.values())
        category_distribution = []
        for name, amount in sorted(category_amount_map.items(), key=lambda x: x[1], reverse=True)[:8]:
            qty = round(category_qty_map.get(name, 0.0), 2)
            category_distribution.append(
                {
                    "name": name,
                    "amount": round(amount, 2),
                    "quantity": qty,
                    "ratio": round((amount / total_category_amount * 100), 2) if total_category_amount else 0.0,
                }
            )

        recent_3m_total = sum(recent_3m_category_amounts.values())
        prev_3m_total = sum(prev_3m_category_amounts.values())
        recent_6m_total = sum(recent_6m_category_amounts.values())
        category_trend_rows = []
        category_names = set(category_amount_map.keys()) | set(recent_3m_category_amounts.keys()) | set(prev_3m_category_amounts.keys())
        for category_name in sorted(category_names):
            recent_3_ratio = round((recent_3m_category_amounts.get(category_name, 0.0) / recent_3m_total * 100), 2) if recent_3m_total else 0.0
            prev_3_ratio = round((prev_3m_category_amounts.get(category_name, 0.0) / prev_3m_total * 100), 2) if prev_3m_total else 0.0
            recent_6_ratio = round((recent_6m_category_amounts.get(category_name, 0.0) / recent_6m_total * 100), 2) if recent_6m_total else 0.0
            category_trend_rows.append(
                {
                    "name": category_name,
                    "recent_3_ratio": recent_3_ratio,
                    "prev_3_ratio": prev_3_ratio,
                    "change_pp": round(recent_3_ratio - prev_3_ratio, 2),
                    "recent_6_ratio": recent_6_ratio,
                }
            )
        category_trend_rows.sort(key=lambda row: abs(row["change_pp"]), reverse=True)
        category_trend_rows = category_trend_rows[:8]

        avg_items_per_order = round((selected_total_item_qty / selected_total_count), 2) if selected_total_count else 0.0
        if selected_avg_interval is None:
            purchase_cycle_label = "样本不足"
        elif selected_avg_interval <= 35 and (selected_max_interval or 0) <= 50:
            purchase_cycle_label = "较规律，接近月度采购"
        elif selected_avg_interval <= 100:
            purchase_cycle_label = "中等规律，偏季度节奏"
        else:
            purchase_cycle_label = "波动较大，采购节奏不固定"

        selected_product_mix = []
        for name, amount in sorted(customer_product_amount_map.items(), key=lambda x: x[1], reverse=True)[:10]:
            qty = round(customer_product_qty_map.get(name, 0.0), 2)
            selected_product_mix.append(
                {
                    "name": name,
                    "amount": round(amount, 2),
                    "quantity": qty,
                    "amount_ratio": round((amount / selected_total_item_amount * 100), 2) if selected_total_item_amount else 0.0,
                    "quantity_ratio": round((qty / selected_total_item_qty * 100), 2) if selected_total_item_qty else 0.0,
                }
            )

        selected_spec_mix = []
        for name, amount in sorted(customer_spec_amount_map.items(), key=lambda x: x[1], reverse=True)[:10]:
            qty = round(customer_spec_qty_map.get(name, 0.0), 2)
            selected_spec_mix.append(
                {
                    "name": name,
                    "amount": round(amount, 2),
                    "quantity": qty,
                    "amount_ratio": round((amount / selected_total_item_amount * 100), 2) if selected_total_item_amount else 0.0,
                    "quantity_ratio": round((qty / selected_total_item_qty * 100), 2) if selected_total_item_qty else 0.0,
                }
            )

        selected_customer = {
            "id": selected_buyer.id,
            "name": selected_buyer.name,
            "total_amount": selected_total_amount,
            "total_quantity": round(selected_total_item_qty, 2),
            "total_count": selected_total_count,
            "avg_amount": selected_avg_amount,
            "first_purchase_date": selected_first_date.isoformat() if selected_first_date else "",
            "last_purchase_date": selected_last_date.isoformat() if selected_last_date else "",
            "days_since_last": selected_days_since_last,
            "avg_interval": selected_avg_interval,
            "max_interval": selected_max_interval,
            "monthly_order_count": monthly_order_count,
            "quarterly_order_count": quarterly_order_count,
            "yearly_order_count": yearly_order_count,
            "avg_items_per_order": avg_items_per_order,
            "purchase_cycle_label": purchase_cycle_label,
            "monthly_trend": selected_monthly_trend,
            "trend_12m": selected_12m_trend,
            "trend_12m_polyline": " ".join(trend_12m_points),
            "trend_12m_dots": trend_12m_dots,
            "trend_12m_labels": trend_12m_labels,
            "trend_12m_y_axis_labels": trend_12m_y_axis_labels,
            "trend_12m_chart_width": chart_width,
            "trend_12m_chart_height": chart_height,
            "product_mix": selected_product_mix,
            "spec_mix": selected_spec_mix,
            "top_products": selected_top_products,
            "category_distribution": category_distribution,
            "category_trends": category_trend_rows,
            "recent_purchase_details": recent_purchase_details,
            "order_quantity_buckets": [
                {"bucket": bucket, "count": count, "ratio": round((count / selected_total_count * 100), 2) if selected_total_count else 0.0}
                for bucket, count in order_quantity_buckets.items()
            ],
            "order_item_type_buckets": [
                {"bucket": bucket, "count": count, "ratio": round((count / selected_total_count * 100), 2) if selected_total_count else 0.0}
                for bucket, count in order_item_type_buckets.items()
            ],
        }

    return templates.TemplateResponse(
        request,
        "analytics.html",
        {
            "buyer_options": buyer_options,
            "selected_buyer_id": buyer_id,
            "months": months,
            "total_count": total_count,
            "total_amount": total_amount,
            "avg_amount": avg_amount,
            "current_month_amount": round(current_month_amount, 2),
            "last_month_amount": round(last_month_amount, 2),
            "mom_change": mom_change,
            "monthly_trend": monthly_trend,
            "status_items": status_items,
            "type_items": type_items,
            "top_buyers": top_buyers,
            "top_platforms": top_platforms,
            "pending_items": pending_items,
            "pending_total": pending_total,
            "top_products": top_products,
            "top_specs": top_specs,
            "customer_segment": customer_segment,
            "dormant_customers": dormant_customers,
            "selected_customer": selected_customer,
        },
    )


@app.get("/analytics/customer-export.xlsx")
def export_customer_profile(
    buyer_id: int = Query(...),
    db: Session = Depends(get_db),
):
    buyer = db.get(Buyer, buyer_id)
    if not buyer:
        raise HTTPException(status_code=404, detail="购买方不存在")

    invoices = (
        db.query(Invoice)
        .filter(Invoice.buyer_id == buyer_id)
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .all()
    )
    products = db.query(Product).all()
    product_category_map = {
        (p.name or "").strip(): ((p.group_name or "").strip() or "未分组")
        for p in products
        if p.name
    }

    export_dir = EXPORTS_DIR
    export_dir.mkdir(parents=True, exist_ok=True)
    safe_name = buyer.name.replace("/", "-").replace("\\", "-").strip() or f"buyer_{buyer_id}"
    export_path = export_dir / f"customer_profile_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    export_customer_profile_xlsx(buyer=buyer, invoices=invoices, product_category_map=product_category_map, export_path=export_path)

    return FileResponse(
        export_path,
        filename=export_path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.get("/sellers")
def sellers_page(request: Request, db: Session = Depends(get_db)):
    sellers = db.query(Seller).options(selectinload(Seller.salespeople)).order_by(Seller.id.desc()).all()
    seller_cards = []
    total_salespeople = 0
    for seller in sellers:
        summary_text, full_names = summarize_salespeople(list(seller.salespeople))
        total_salespeople += len(full_names)
        seller_cards.append(
            {
                "seller": seller,
                "member_summary": summary_text,
                "member_names": full_names,
                "member_count": len(full_names),
                "members": [
                    {
                        "name": salesperson.name or "",
                        "phone": salesperson.phone or "",
                        "wechat": salesperson.wechat or "",
                        "department": salesperson.department or "",
                    }
                    for salesperson in seller.salespeople
                ],
            }
        )
    return templates.TemplateResponse(
        request,
        "sellers.html",
        {
            "sellers": sellers,
            "seller_cards": seller_cards,
            "seller_count": len(sellers),
            "salesperson_count": total_salespeople,
        },
    )


@app.post("/sellers")
def create_seller(
    name: str = Form(...),
    tax_id: str = Form(""),
    address_phone: str = Form(""),
    bank_account: str = Form(""),
    db: Session = Depends(get_db),
):
    seller = Seller(
        name=name.strip(),
        tax_id=tax_id.strip(),
        salesperson="",
        address_phone=address_phone.strip(),
        bank_account=bank_account.strip(),
    )
    db.add(seller)
    db.commit()
    return RedirectResponse(url="/sellers", status_code=303)


@app.get("/sellers/{seller_id}/edit")
def edit_seller_page(seller_id: int, request: Request, db: Session = Depends(get_db)):
    seller = db.query(Seller).options(selectinload(Seller.salespeople)).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(status_code=404, detail="销售方不存在")
    return templates.TemplateResponse(request, "seller_edit.html", {"seller": seller})


@app.post("/sellers/{seller_id}/edit")
def update_seller(
    seller_id: int,
    name: str = Form(...),
    tax_id: str = Form(""),
    address_phone: str = Form(""),
    bank_account: str = Form(""),
    db: Session = Depends(get_db),
):
    seller = db.query(Seller).options(selectinload(Seller.salespeople)).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(status_code=404, detail="销售方不存在")

    seller.name = name.strip()
    seller.tax_id = tax_id.strip()
    seller.address_phone = address_phone.strip()
    seller.bank_account = bank_account.strip()
    db.commit()
    return RedirectResponse(url="/sellers", status_code=303)


@app.post("/sellers/{seller_id}/salespeople")
def update_seller_salespeople(
    seller_id: int,
    member_name: list[str] = Form([]),
    member_phone: list[str] = Form([]),
    member_wechat: list[str] = Form([]),
    member_department: list[str] = Form([]),
    db: Session = Depends(get_db),
):
    seller = db.query(Seller).options(selectinload(Seller.salespeople)).filter(Seller.id == seller_id).first()
    if not seller:
        raise HTTPException(status_code=404, detail="销售方不存在")

    payloads = parse_salespeople_form_lists(member_name, member_phone, member_wechat, member_department)
    sync_seller_salespeople(seller, payloads)
    seller.salesperson = payloads[0]["name"] if payloads else ""
    db.commit()
    return RedirectResponse(url="/sellers", status_code=303)


@app.post("/api/sellers/ai-parse-salespeople")
def ai_parse_seller_salespeople(raw_text: str = Form("")):
    text_input = raw_text.strip()
    if not text_input:
        return JSONResponse({"ok": False, "error": "请输入包含联系人的原始文本"}, status_code=400)

    api_key = get_deepseek_api_key()
    if not api_key:
        return JSONResponse({"ok": False, "error": "未设置 DeepSeek API Key，请先到设置页保存"}, status_code=400)

    try:
        from openai import OpenAI
    except Exception:
        return JSONResponse({"ok": False, "error": "缺少 openai 依赖，请先安装 requirements.txt"}, status_code=500)

    system_prompt = (
        "你是销售团队录入助手。"
        "请从原始文本中提取多个联系人，严格返回 JSON 数组，不要返回 markdown。"
        "每个元素仅包含: name,phone,wechat,department。缺失字段返回空字符串。"
    )
    user_prompt = f"请解析以下销售团队信息并输出 JSON 数组:\n{text_input}"

    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
            temperature=0.1,
        )
        content = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"调用 DeepSeek 失败: {exc}"}, status_code=502)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start_idx = content.find("[")
        end_idx = content.rfind("]")
        if start_idx >= 0 and end_idx > start_idx:
            try:
                parsed = json.loads(content[start_idx : end_idx + 1])
            except json.JSONDecodeError:
                parsed = []
        else:
            parsed = []

    if not isinstance(parsed, list):
        parsed = []

    payloads = normalize_salespeople_payload(
        [
            {
                "name": item.get("name", "") if isinstance(item, dict) else "",
                "phone": item.get("phone", "") if isinstance(item, dict) else "",
                "wechat": item.get("wechat", "") if isinstance(item, dict) else "",
                "department": item.get("department", "") if isinstance(item, dict) else "",
            }
            for item in parsed
        ]
    )
    return {"ok": True, "data": payloads}


@app.post("/sellers/{seller_id}/delete")
def delete_seller(seller_id: int, db: Session = Depends(get_db)):
    seller = db.get(Seller, seller_id)
    if not seller:
        raise HTTPException(status_code=404, detail="销售方不存在")

    invoice_count = db.query(Invoice).filter(Invoice.seller_id == seller_id).count()
    if invoice_count > 0:
        raise HTTPException(status_code=400, detail="该销售方已有关联发票，无法删除")

    db.delete(seller)
    db.commit()
    return RedirectResponse(url="/sellers", status_code=303)


def build_buyers_directory_context(
    db: Session,
    *,
    q: str = "",
    platform: str = "",
    wechat_qq_keyword: str = "",
    profile_status: str = "",
    error: str | None = None,
    form_values: dict[str, str] | None = None,
):
    query = db.query(Buyer)
    keyword = q.strip() or wechat_qq_keyword.strip()
    platform_value = platform.strip()
    profile_status_value = profile_status.strip()
    complete_profile_filter = and_(
        Buyer.tax_id.is_not(None), Buyer.tax_id != "",
        Buyer.contact_phone.is_not(None), Buyer.contact_phone != "",
        Buyer.address.is_not(None), Buyer.address != "",
        Buyer.bank_name.is_not(None), Buyer.bank_name != "",
        Buyer.bank_account_no.is_not(None), Buyer.bank_account_no != "",
    )
    incomplete_profile_filter = or_(
        Buyer.tax_id.is_(None), Buyer.tax_id == "",
        Buyer.contact_phone.is_(None), Buyer.contact_phone == "",
        Buyer.address.is_(None), Buyer.address == "",
        Buyer.bank_name.is_(None), Buyer.bank_name == "",
        Buyer.bank_account_no.is_(None), Buyer.bank_account_no == "",
    )

    if keyword:
        query = query.filter(
            or_(
                Buyer.name.contains(keyword),
                Buyer.tax_id.contains(keyword),
                Buyer.contact_person.contains(keyword),
                Buyer.contact_phone.contains(keyword),
                Buyer.wechat_qq.contains(keyword),
                Buyer.platform.contains(keyword),
                Buyer.address.contains(keyword),
                Buyer.shipping_address.contains(keyword),
                Buyer.bank_name.contains(keyword),
                Buyer.bank_account_no.contains(keyword),
                Buyer.notes.contains(keyword),
            )
        )
    if platform_value:
        query = query.filter(Buyer.platform == platform_value)
    if profile_status_value == "ready":
        query = query.filter(complete_profile_filter)
    elif profile_status_value == "incomplete":
        query = query.filter(incomplete_profile_filter)

    buyers = query.order_by(Buyer.id.desc()).all()
    total_buyers = db.query(Buyer).count()
    ready_profiles = db.query(Buyer).filter(complete_profile_filter).count()
    incomplete_profiles = db.query(Buyer).filter(incomplete_profile_filter).count()

    return {
        "buyers": buyers,
        "q": keyword,
        "platform": platform_value,
        "profile_status": profile_status_value,
        "total_buyers": total_buyers,
        "filtered_count": len(buyers),
        "ready_profiles": ready_profiles,
        "incomplete_profiles": incomplete_profiles,
        "active_filter_count": sum(1 for value in [keyword, platform_value, profile_status_value] if value),
        "platform_options": ["1688", "淘宝", "公对公", "微信"],
        "error": error,
        "form_values": form_values or {},
    }


@app.get("/buyers")
def buyers_page(
    request: Request,
    q: str = Query(""),
    platform: str = Query(""),
    wechat_qq_keyword: str = Query(""),
    profile_status: str = Query(""),
    db: Session = Depends(get_db),
):
    context = build_buyers_directory_context(
        db,
        q=q,
        platform=platform,
        wechat_qq_keyword=wechat_qq_keyword,
        profile_status=profile_status,
    )
    return templates.TemplateResponse(request, "buyers.html", context)


@app.get("/api/buyers")
def buyers_api(q: str = Query(""), db: Session = Depends(get_db)):
    query = db.query(Buyer)
    if q:
        kw = q.strip()
        query = query.filter(
            or_(
                Buyer.name.contains(kw),
                Buyer.platform.contains(kw),
                Buyer.contact_person.contains(kw),
                Buyer.contact_phone.contains(kw),
                Buyer.wechat_qq.contains(kw),
                Buyer.tax_id.contains(kw),
                Buyer.address.contains(kw),
                Buyer.shipping_address.contains(kw),
                Buyer.bank_name.contains(kw),
                Buyer.bank_account_no.contains(kw),
            )
        )
    buyers = query.order_by(Buyer.id.desc()).limit(20).all()
    return [
        {
            "id": b.id,
            "name": b.name,
            "tax_id": b.tax_id or "",
            "platform": b.platform or "",
            "contact_person": b.contact_person or "",
            "contact_phone": b.contact_phone or "",
            "wechat_qq": b.wechat_qq or "",
            "address": b.address or "",
            "shipping_address": b.shipping_address or "",
            "bank_name": b.bank_name or "",
            "bank_account_no": b.bank_account_no or "",
            "notes": b.notes or "",
            "address_phone": b.address_phone
            or " ".join(part for part in [b.address or "", b.contact_phone or ""] if part).strip(),
            "bank_account": b.bank_account
            or " ".join(part for part in [b.bank_name or "", b.bank_account_no or ""] if part).strip(),
        }
        for b in buyers
    ]


@app.get("/api/buyers/{buyer_id}/invoice-defaults")
def buyer_invoice_defaults_api(buyer_id: int, db: Session = Depends(get_db)):
    buyer = db.get(Buyer, buyer_id)
    if not buyer:
        raise HTTPException(status_code=404, detail="购买方不存在")

    latest_invoice = (
        db.query(Invoice)
        .options(selectinload(Invoice.items))
        .filter(Invoice.buyer_id == buyer_id)
        .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
        .first()
    )

    invoice_type = "普通发票"
    tax_rate = 0.01

    if latest_invoice:
        invoice_type = latest_invoice.invoice_type or invoice_type
        if latest_invoice.items:
            tax_rate = float(latest_invoice.items[0].tax_rate or get_invoice_tax_rate(invoice_type))
        else:
            tax_rate = float(get_invoice_tax_rate(invoice_type))

    return {
        "buyer_id": buyer.id,
        "buyer_name": buyer.name,
        "default_invoice_type": invoice_type,
        "default_tax_rate": tax_rate,
        "source": "latest-invoice" if latest_invoice else "fallback",
    }


@app.post("/api/buyers/ai-parse")
def ai_parse_buyer(raw_text: str = Form("")):
    text_input = raw_text.strip()
    if not text_input:
        return JSONResponse({"ok": False, "error": "请输入要解析的客户信息文本"}, status_code=400)

    api_key = get_deepseek_api_key()
    if not api_key:
        return JSONResponse({"ok": False, "error": "未设置 DeepSeek API Key，请先到设置页保存"}, status_code=400)

    try:
        from openai import OpenAI
    except Exception:
        return JSONResponse({"ok": False, "error": "缺少 openai 依赖，请先安装 requirements.txt"}, status_code=500)

    fields = {
        "name": "",
        "tax_id": "",
        "address": "",
        "bank_name": "",
        "bank_account_no": "",
        "contact_person": "",
        "contact_phone": "",
        "wechat_qq": "",
        "shipping_address": "",
        "platform": "",
        "notes": "",
    }

    system_prompt = (
        "你是企业客户资料录入助手。"
        "请从用户输入中提取并标准化字段，严格返回 JSON 对象，不要返回 markdown。"
        "字段仅包含: name,tax_id,address,bank_name,bank_account_no,contact_person,contact_phone,wechat_qq,shipping_address,platform,notes。"
        "若字段缺失则给空字符串。"
    )
    user_prompt = f"请解析以下客户信息并输出 JSON:\n{text_input}"

    try:
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
            temperature=0.1,
        )
        content = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": f"调用 DeepSeek 失败: {exc}"}, status_code=502)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx >= 0 and end_idx > start_idx:
            try:
                parsed = json.loads(content[start_idx : end_idx + 1])
            except json.JSONDecodeError:
                parsed = {}
        else:
            parsed = {}

    if not isinstance(parsed, dict):
        parsed = {}

    for key in fields.keys():
        value = parsed.get(key, "")
        fields[key] = value.strip() if isinstance(value, str) else ""

    if not fields["name"]:
        return JSONResponse({"ok": False, "error": "AI 未识别到账户名称，请补充文本后重试"}, status_code=400)

    return {"ok": True, "data": fields}


@app.post("/buyers")
def create_buyer(
    name: str = Form(...),
    platform: str = Form(""),
    tax_id: str = Form(""),
    contact_person: str = Form(""),
    contact_phone: str = Form(""),
    wechat_qq: str = Form(""),
    address: str = Form(""),
    shipping_address: str = Form(""),
    bank_name: str = Form(""),
    bank_account_no: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    normalized_address = address.strip()
    normalized_phone = contact_phone.strip()
    normalized_bank_name = bank_name.strip()
    normalized_bank_account_no = bank_account_no.strip()

    buyer = Buyer(
        name=name.strip(),
        tax_id=tax_id.strip(),
        platform=platform.strip(),
        contact_person=contact_person.strip(),
        contact_phone=normalized_phone,
        wechat_qq=wechat_qq.strip(),
        address=normalized_address,
        shipping_address=shipping_address.strip(),
        bank_name=normalized_bank_name,
        bank_account_no=normalized_bank_account_no,
        address_phone=" ".join(part for part in [normalized_address, normalized_phone] if part).strip(),
        bank_account=" ".join(part for part in [normalized_bank_name, normalized_bank_account_no] if part).strip(),
        notes=notes.strip(),
    )
    db.add(buyer)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        context = build_buyers_directory_context(
            db,
            error=f"账户名称「{name.strip()}」已存在，请使用其他名称。",
            form_values={
                "name": name.strip(),
                "platform": platform.strip(),
                "tax_id": tax_id.strip(),
                "contact_person": contact_person.strip(),
                "contact_phone": normalized_phone,
                "wechat_qq": wechat_qq.strip(),
                "address": normalized_address,
                "shipping_address": shipping_address.strip(),
                "bank_name": normalized_bank_name,
                "bank_account_no": normalized_bank_account_no,
                "notes": notes.strip(),
            },
        )
        return templates.TemplateResponse(request, "buyers.html", context, status_code=422)
    return RedirectResponse(url="/buyers", status_code=303)


@app.get("/buyers/{buyer_id}/edit")
def edit_buyer_page(buyer_id: int, request: Request, db: Session = Depends(get_db)):
    buyer = db.get(Buyer, buyer_id)
    if not buyer:
        raise HTTPException(status_code=404, detail="购买方不存在")
    return templates.TemplateResponse(request, "buyer_edit.html", {"buyer": buyer})


@app.post("/buyers/{buyer_id}/edit")
def update_buyer(
    buyer_id: int,
    name: str = Form(...),
    platform: str = Form(""),
    tax_id: str = Form(""),
    contact_person: str = Form(""),
    contact_phone: str = Form(""),
    wechat_qq: str = Form(""),
    address: str = Form(""),
    shipping_address: str = Form(""),
    bank_name: str = Form(""),
    bank_account_no: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    buyer = db.get(Buyer, buyer_id)
    if not buyer:
        raise HTTPException(status_code=404, detail="购买方不存在")

    normalized_address = address.strip()
    normalized_phone = contact_phone.strip()
    normalized_bank_name = bank_name.strip()
    normalized_bank_account_no = bank_account_no.strip()

    buyer.name = name.strip()
    buyer.platform = platform.strip()
    buyer.tax_id = tax_id.strip()
    buyer.contact_person = contact_person.strip()
    buyer.contact_phone = normalized_phone
    buyer.wechat_qq = wechat_qq.strip()
    buyer.address = normalized_address
    buyer.shipping_address = shipping_address.strip()
    buyer.bank_name = normalized_bank_name
    buyer.bank_account_no = normalized_bank_account_no
    buyer.address_phone = " ".join(part for part in [normalized_address, normalized_phone] if part).strip()
    buyer.bank_account = " ".join(part for part in [normalized_bank_name, normalized_bank_account_no] if part).strip()
    buyer.notes = notes.strip()
    db.commit()
    return RedirectResponse(url="/buyers", status_code=303)


@app.post("/buyers/{buyer_id}/delete")
def delete_buyer(buyer_id: int, db: Session = Depends(get_db)):
    buyer = db.get(Buyer, buyer_id)
    if not buyer:
        raise HTTPException(status_code=404, detail="购买方不存在")

    invoice_count = db.query(Invoice).filter(Invoice.buyer_id == buyer_id).count()
    if invoice_count > 0:
        raise HTTPException(status_code=400, detail="该购买方已有关联发票，无法删除")

    db.delete(buyer)
    db.commit()
    return RedirectResponse(url="/buyers", status_code=303)


@app.get("/products")
def products_page(
    request: Request,
    product_name: str = Query(""),
    group_name: str = Query(""),
    db: Session = Depends(get_db),
):
    query = db.query(Product)
    if product_name:
        query = query.filter(Product.name == product_name)
    if group_name:
        query = query.filter(Product.group_name == group_name)

    products = query.order_by(Product.id.desc()).all()
    product_name_options = [
        row[0]
        for row in db.query(Product.name).distinct().order_by(Product.name.asc()).all()
        if row[0]
    ]
    group_name_options = [
        row[0]
        for row in db.query(Product.group_name).filter(Product.group_name.isnot(None), Product.group_name != "").distinct().order_by(Product.group_name.asc()).all()
        if row[0]
    ]
    return templates.TemplateResponse(
        request,
        "products.html",
        {
            "products": products,
            "product_name_options": product_name_options,
            "group_name_options": group_name_options,
        },
    )


@app.post("/products")
def create_product(
    name: str = Form(...),
    group_name: str = Form(""),
    spec_model: str = Form(""),
    db: Session = Depends(get_db),
):
    product = Product(
        group_name=group_name.strip(),
        name=name.strip(),
        spec_model=spec_model.strip(),
    )
    db.add(product)
    db.commit()
    return RedirectResponse(url="/products", status_code=303)


@app.post("/products/bulk")
def create_products_bulk(
    bulk_text: str = Form(...),
    group_name: str = Form(""),
    db: Session = Depends(get_db),
):
    normalized_group = group_name.strip()
    lines = [line.strip() for line in bulk_text.splitlines() if line.strip()]
    for line in lines:
        normalized = line.replace("，", ",")
        parts = [part.strip() for part in normalized.split(",")]
        if len(parts) >= 3:
            inline_group_name = parts[0]
            name = parts[1]
            spec_model = ",".join(parts[2:]).strip()
        elif len(parts) == 2:
            inline_group_name = normalized_group
            name = parts[0]
            spec_model = parts[1]
        else:
            inline_group_name = normalized_group
            name, spec_model = normalized, ""

        if not name:
            continue

        db.add(
            Product(
                group_name=inline_group_name,
                name=name,
                spec_model=spec_model,
            )
        )

    db.commit()
    return RedirectResponse(url="/products", status_code=303)


@app.get("/products/{product_id}/edit")
def edit_product_page(product_id: int, request: Request, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    return templates.TemplateResponse(request, "product_edit.html", {"product": product})


@app.post("/products/{product_id}/edit")
def update_product(
    product_id: int,
    name: str = Form(...),
    group_name: str = Form(""),
    spec_model: str = Form(""),
    db: Session = Depends(get_db),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")

    product.group_name = group_name.strip()
    product.name = name.strip()
    product.spec_model = spec_model.strip()
    db.commit()
    return RedirectResponse(url="/products", status_code=303)


@app.post("/products/{product_id}/delete")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    db.delete(product)
    db.commit()
    return RedirectResponse(url="/products", status_code=303)


@app.get("/invoices/new")
def new_invoice_page(request: Request, db: Session = Depends(get_db)):
    sellers = db.query(Seller).options(selectinload(Seller.salespeople)).all()
    buyers = db.query(Buyer).all()
    products = db.query(Product).all()
    salesperson_options = collect_salesperson_options(db, sellers)
    product_name_options: list[str] = []
    product_specs_map: dict[str, list[str]] = {}
    for p in products:
        if p.name:
            if p.name not in product_name_options:
                product_name_options.append(p.name)
            product_specs_map.setdefault(p.name, [])
            if p.spec_model and p.spec_model not in product_specs_map[p.name]:
                product_specs_map[p.name].append(p.spec_model)
    return templates.TemplateResponse(
        request,
        "invoice_form.html",
        {
            "sellers": sellers,
            "buyers": buyers,
            "products": products,
            "salesperson_options": salesperson_options,
            "product_name_options": product_name_options,
            "product_specs_map": product_specs_map,
            "invoice_type_options": INVOICE_TYPE_OPTIONS,
            "invoice_tax_rate_options": INVOICE_TAX_RATE_OPTIONS,
            "default_tax_rate": 0.01,
            "invoice_status_options": INVOICE_STATUS_OPTIONS,
        },
    )


@app.post("/invoices/new")
def create_invoice(
    seller_id: int = Form(...),
    buyer_id: int = Form(...),
    salesperson: str = Form(""),
    invoice_type: str = Form(...),
    tax_rate: str = Form("0.01"),
    invoice_number: str = Form(""),
    invoice_date: str = Form(""),
    order_number: str = Form(""),
    order_date: str = Form(""),
    status: str = Form("待开"),
    notes: str = Form(""),
    item_name: list[str] = Form(...),
    item_spec: list[str] = Form(...),
    item_unit_price: list[str] = Form(...),
    item_quantity: list[int] = Form(...),
    item_amount_with_tax: list[float] = Form(...),
    invoice_file: UploadFile | None = File(None),
    trade_voucher_file: UploadFile | None = File(None),
    trade_voucher_text: str = Form(""),
    db: Session = Depends(get_db),
):
    create_invoice_record(
        db,
        seller_id=seller_id,
        buyer_id=buyer_id,
        salesperson=salesperson,
        invoice_type=invoice_type,
        tax_rate=tax_rate,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        order_number=order_number,
        order_date=order_date,
        status=status,
        notes=notes,
        item_name=item_name,
        item_spec=item_spec,
        item_unit_price=item_unit_price,
        item_quantity=item_quantity,
        item_amount_with_tax=item_amount_with_tax,
        invoice_file_snapshot=snapshot_upload_file(invoice_file),
        trade_voucher_snapshot=snapshot_upload_file(trade_voucher_file),
        trade_voucher_text=trade_voucher_text,
    )

    return RedirectResponse(url="/invoices", status_code=303)


@app.post("/api/jobs/invoices/create")
def create_invoice_async(
    seller_id: int = Form(...),
    buyer_id: int = Form(...),
    salesperson: str = Form(""),
    invoice_type: str = Form(...),
    tax_rate: str = Form("0.01"),
    invoice_number: str = Form(""),
    invoice_date: str = Form(""),
    order_number: str = Form(""),
    order_date: str = Form(""),
    status: str = Form("待开"),
    notes: str = Form(""),
    item_name: list[str] = Form(...),
    item_spec: list[str] = Form(...),
    item_unit_price: list[str] = Form(...),
    item_quantity: list[int] = Form(...),
    item_amount_with_tax: list[float] = Form(...),
    invoice_file: UploadFile | None = File(None),
    trade_voucher_file: UploadFile | None = File(None),
    trade_voucher_text: str = Form(""),
):
    payload = {
        "seller_id": seller_id,
        "buyer_id": buyer_id,
        "salesperson": salesperson,
        "invoice_type": invoice_type,
        "tax_rate": tax_rate,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "order_number": order_number,
        "order_date": order_date,
        "status": status,
        "notes": notes,
        "item_name": item_name,
        "item_spec": item_spec,
        "item_unit_price": item_unit_price,
        "item_quantity": item_quantity,
        "item_amount_with_tax": item_amount_with_tax,
        "invoice_file_snapshot": snapshot_upload_file(invoice_file),
        "trade_voucher_snapshot": snapshot_upload_file(trade_voucher_file),
        "trade_voucher_text": trade_voucher_text,
    }
    job_id = create_background_job("invoice-create", run_create_invoice_job, payload, initial_message="已进入后台保存队列")
    return {"ok": True, "job_id": job_id}


@app.get("/invoices/{invoice_id}/edit")
def edit_invoice_page(invoice_id: int, request: Request, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")

    sellers = db.query(Seller).options(selectinload(Seller.salespeople)).all()
    buyers = db.query(Buyer).all()
    products = db.query(Product).all()
    salesperson_options = collect_salesperson_options(db, sellers)
    product_name_options: list[str] = []
    product_specs_map: dict[str, list[str]] = {}
    for p in products:
        if p.name:
            if p.name not in product_name_options:
                product_name_options.append(p.name)
            product_specs_map.setdefault(p.name, [])
            if p.spec_model and p.spec_model not in product_specs_map[p.name]:
                product_specs_map[p.name].append(p.spec_model)

    default_tax_rate = get_invoice_tax_rate(invoice.invoice_type)
    if invoice.items:
        default_tax_rate = float(invoice.items[0].tax_rate or default_tax_rate)
    if default_tax_rate not in INVOICE_TAX_RATE_OPTIONS:
        default_tax_rate = 0.01

    return templates.TemplateResponse(
        request,
        "invoice_edit.html",
        {
            "invoice": invoice,
            "sellers": sellers,
            "buyers": buyers,
            "products": products,
            "salesperson_options": salesperson_options,
            "product_name_options": product_name_options,
            "product_specs_map": product_specs_map,
            "invoice_type_options": INVOICE_TYPE_OPTIONS,
            "invoice_tax_rate_options": INVOICE_TAX_RATE_OPTIONS,
            "default_tax_rate": default_tax_rate,
            "invoice_status_options": INVOICE_STATUS_OPTIONS,
        },
    )


@app.post("/invoices/{invoice_id}/edit")
def update_invoice(
    invoice_id: int,
    seller_id: int = Form(...),
    buyer_id: int = Form(...),
    salesperson: str = Form(""),
    invoice_type: str = Form(...),
    tax_rate: str = Form("0.01"),
    invoice_number: str = Form(""),
    invoice_date: str = Form(""),
    order_number: str = Form(""),
    order_date: str = Form(""),
    status: str = Form("待开"),
    notes: str = Form(""),
    item_name: list[str] = Form(...),
    item_spec: list[str] = Form(...),
    item_unit_price: list[str] = Form(...),
    item_quantity: list[int] = Form(...),
    item_amount_with_tax: list[float] = Form(...),
    remove_invoice_file: str = Form(""),
    invoice_file: UploadFile | None = File(None),
    trade_voucher_file: UploadFile | None = File(None),
    trade_voucher_text: str = Form(""),
    db: Session = Depends(get_db),
):
    update_invoice_record(
        db,
        invoice_id=invoice_id,
        seller_id=seller_id,
        buyer_id=buyer_id,
        salesperson=salesperson,
        invoice_type=invoice_type,
        tax_rate=tax_rate,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        order_number=order_number,
        order_date=order_date,
        status=status,
        notes=notes,
        item_name=item_name,
        item_spec=item_spec,
        item_unit_price=item_unit_price,
        item_quantity=item_quantity,
        item_amount_with_tax=item_amount_with_tax,
        remove_invoice_file=remove_invoice_file,
        invoice_file_snapshot=snapshot_upload_file(invoice_file),
        trade_voucher_snapshot=snapshot_upload_file(trade_voucher_file),
        trade_voucher_text=trade_voucher_text,
    )
    return RedirectResponse(url="/invoices", status_code=303)


@app.post("/api/jobs/invoices/{invoice_id}/update")
def update_invoice_async(
    invoice_id: int,
    seller_id: int = Form(...),
    buyer_id: int = Form(...),
    salesperson: str = Form(""),
    invoice_type: str = Form(...),
    tax_rate: str = Form("0.01"),
    invoice_number: str = Form(""),
    invoice_date: str = Form(""),
    order_number: str = Form(""),
    order_date: str = Form(""),
    status: str = Form("待开"),
    notes: str = Form(""),
    item_name: list[str] = Form(...),
    item_spec: list[str] = Form(...),
    item_unit_price: list[str] = Form(...),
    item_quantity: list[int] = Form(...),
    item_amount_with_tax: list[float] = Form(...),
    remove_invoice_file: str = Form(""),
    invoice_file: UploadFile | None = File(None),
    trade_voucher_file: UploadFile | None = File(None),
    trade_voucher_text: str = Form(""),
):
    payload = {
        "invoice_id": invoice_id,
        "seller_id": seller_id,
        "buyer_id": buyer_id,
        "salesperson": salesperson,
        "invoice_type": invoice_type,
        "tax_rate": tax_rate,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "order_number": order_number,
        "order_date": order_date,
        "status": status,
        "notes": notes,
        "item_name": item_name,
        "item_spec": item_spec,
        "item_unit_price": item_unit_price,
        "item_quantity": item_quantity,
        "item_amount_with_tax": item_amount_with_tax,
        "remove_invoice_file": remove_invoice_file,
        "invoice_file_snapshot": snapshot_upload_file(invoice_file),
        "trade_voucher_snapshot": snapshot_upload_file(trade_voucher_file),
        "trade_voucher_text": trade_voucher_text,
    }
    job_id = create_background_job("invoice-update", run_update_invoice_job, payload, initial_message="已进入后台保存队列")
    return {"ok": True, "job_id": job_id}


@app.post("/invoices/{invoice_id}/status")
def update_invoice_status(
    invoice_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")
    if status not in INVOICE_STATUS_OPTIONS:
        raise HTTPException(status_code=400, detail="非法状态")

    invoice.status = status
    db.commit()
    return RedirectResponse(url="/invoices", status_code=303)


@app.post("/invoices/{invoice_id}/delete")
def delete_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")

    if invoice.file_stored_path and os.path.exists(invoice.file_stored_path):
        os.remove(invoice.file_stored_path)

    db.delete(invoice)
    db.commit()
    return RedirectResponse(url="/invoices", status_code=303)


@app.get("/invoices")
def invoices_page(
    request: Request,
    start_date: str = Query(""),
    end_date: str = Query(""),
    recent_range: str = Query(""),
    seller_id: str = Query(""),
    buyer_id: str = Query(""),
    salesperson: str = Query(""),
    platform: str = Query(""),
    invoice_type: str = Query(""),
    status: str = Query(""),
    keyword: str = Query(""),
    db: Session = Depends(get_db),
):
    start_date_value = start_date.strip()
    end_date_value = end_date.strip()
    recent_range_value = recent_range.strip()
    if not start_date_value and not end_date_value and not recent_range_value:
        recent_range_value = "7d"

    current_filters = {
        "start_date": start_date_value,
        "end_date": end_date_value,
        "recent_range": recent_range_value,
        "seller_id": seller_id.strip(),
        "buyer_id": buyer_id.strip(),
        "salesperson": salesperson.strip(),
        "platform": platform.strip(),
        "invoice_type": invoice_type.strip(),
        "status": status.strip(),
        "keyword": keyword.strip(),
    }

    def build_invoice_link(**overrides: str) -> str:
        payload = {key: value for key, value in current_filters.items() if value}
        for key, value in overrides.items():
            normalized = value.strip() if isinstance(value, str) else value
            if normalized:
                payload[key] = normalized
            else:
                payload.pop(key, None)
        query_text = urlencode(payload)
        return f"/invoices?{query_text}" if query_text else "/invoices"

    filters = parse_invoice_filters(
        start_date=current_filters["start_date"],
        end_date=current_filters["end_date"],
        recent_range=current_filters["recent_range"],
        seller_id=current_filters["seller_id"],
        buyer_id=current_filters["buyer_id"],
        salesperson=current_filters["salesperson"],
        platform=current_filters["platform"],
        invoice_type=current_filters["invoice_type"],
        status=current_filters["status"],
        keyword=current_filters["keyword"],
    )

    invoices = query_invoices(db, filters).all()
    sellers = db.query(Seller).options(selectinload(Seller.salespeople)).all()
    buyers = db.query(Buyer).order_by(Buyer.name.asc()).all()
    platform_rows = (
        db.query(Buyer.platform)
        .filter(Buyer.platform.isnot(None), Buyer.platform != "")
        .distinct()
        .all()
    )
    platform_options = sorted([row[0] for row in platform_rows if row[0]])
    salesperson_options = collect_salesperson_options(db, sellers)
    export_query = urlencode({key: value for key, value in current_filters.items() if value})
    overview_links = {
        "total": build_invoice_link(),
        "opened": build_invoice_link(status="已开"),
        "pending": build_invoice_link(status="待开"),
        "voucher": build_invoice_link(),
    }

    return templates.TemplateResponse(
        request,
        "invoices.html",
        {
            "invoices": invoices,
            "sellers": sellers,
            "buyers": buyers,
            "platform_options": platform_options,
            "salesperson_options": salesperson_options,
            "invoice_type_options": INVOICE_TYPE_OPTIONS,
            "invoice_status_options": INVOICE_STATUS_OPTIONS,
            "current_filters": current_filters,
            "export_query": export_query,
            "overview_links": overview_links,
        },
    )


@app.get("/api/invoices/{invoice_id}/items")
def invoice_items_api(invoice_id: int, db: Session = Depends(get_db)):
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")

    trade_voucher_url = f"/invoices/{invoice.id}/trade-voucher" if invoice.trade_voucher_stored_path else ""
    trade_voucher_name = invoice.trade_voucher_original_name or ""
    guessed_mime_type, _ = mimetypes.guess_type(trade_voucher_name or trade_voucher_url)
    normalized_mime_type = guessed_mime_type or ""
    is_image_voucher = normalized_mime_type.startswith("image/") or trade_voucher_name.lower().endswith((".jpg", ".jpeg", ".jpge", ".png", ".webp", ".gif", ".bmp"))

    return {
        "invoice_number": invoice.invoice_number,
        "order_number": invoice.order_number or "",
        "order_date": invoice.order_date.strftime("%Y-%m-%d") if invoice.order_date else "",
        "invoice_type": invoice.invoice_type,
        "salesperson": invoice.salesperson or "",
        "trade_voucher_text": invoice.trade_voucher_text or "",
        "trade_voucher": {
            "name": trade_voucher_name,
            "url": trade_voucher_url,
            "is_image": is_image_voucher,
            "mime_type": normalized_mime_type,
            "has_file": bool(invoice.trade_voucher_stored_path),
        },
        "items": [
            {
                "product_name": item.product_name,
                "spec_model": item.spec_model or "",
                "tax_code": item.tax_code or "",
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "amount": item.amount,
                "tax_rate": item.tax_rate,
                "tax_amount": item.tax_amount,
                "total_with_tax": item.total_with_tax,
            }
            for item in invoice.items
        ],
    }


@app.get("/invoices/{invoice_id}/file")
def open_invoice_file(invoice_id: int, db: Session = Depends(get_db)):
    _, file_path = resolve_invoice_file_or_404(invoice_id, db)

    return FileResponse(file_path)


@app.post("/api/invoices/{invoice_id}/open-native")
def open_invoice_file_native(invoice_id: int, db: Session = Depends(get_db)):
    invoice, file_path = resolve_invoice_file_or_404(invoice_id, db)
    try:
        open_file_in_system(file_path, reveal=False)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    return {
        "ok": True,
        "message": f"已用系统默认程序打开：{invoice.file_original_name or file_path.name}",
    }


@app.post("/api/invoices/{invoice_id}/reveal-native")
def reveal_invoice_file_native(invoice_id: int, db: Session = Depends(get_db)):
    invoice, file_path = resolve_invoice_file_or_404(invoice_id, db)
    try:
        open_file_in_system(file_path, reveal=True)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    return {
        "ok": True,
        "message": f"已定位文件：{invoice.file_original_name or file_path.name}",
    }


@app.get("/invoices/{invoice_id}/trade-voucher")
def open_trade_voucher_file(invoice_id: int, db: Session = Depends(get_db)):
    _, file_path = resolve_trade_voucher_or_404(invoice_id, db)
    return FileResponse(file_path)


@app.post("/api/invoices/{invoice_id}/trade-voucher/open-native")
def open_trade_voucher_file_native(invoice_id: int, db: Session = Depends(get_db)):
    invoice, file_path = resolve_trade_voucher_or_404(invoice_id, db)
    try:
        open_file_in_system(file_path, reveal=False)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True, "message": f"已用系统默认程序打开：{invoice.trade_voucher_original_name or file_path.name}"}


@app.post("/api/invoices/{invoice_id}/trade-voucher/reveal-native")
def reveal_trade_voucher_file_native(invoice_id: int, db: Session = Depends(get_db)):
    invoice, file_path = resolve_trade_voucher_or_404(invoice_id, db)
    try:
        open_file_in_system(file_path, reveal=True)
    except RuntimeError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True, "message": f"已定位交易凭证：{invoice.trade_voucher_original_name or file_path.name}"}


@app.get("/export.zip")
@app.get("/export.xlsx")
def export_excel(
    start_date: str = Query(""),
    end_date: str = Query(""),
    recent_range: str = Query(""),
    seller_id: str = Query(""),
    buyer_id: str = Query(""),
    salesperson: str = Query(""),
    platform: str = Query(""),
    invoice_type: str = Query(""),
    status: str = Query(""),
    keyword: str = Query(""),
    db: Session = Depends(get_db),
):
    filters = parse_invoice_filters(
        start_date=start_date,
        end_date=end_date,
        recent_range=recent_range,
        seller_id=seller_id,
        buyer_id=buyer_id,
        salesperson=salesperson,
        platform=platform,
        invoice_type=invoice_type,
        status=status,
        keyword=keyword,
    )
    export_path = create_export_file(db, filters)

    return FileResponse(
        export_path,
        filename=export_path.name,
        media_type="application/zip",
    )


@app.post("/api/jobs/export-invoices")
def export_excel_async(
    start_date: str = Query(""),
    end_date: str = Query(""),
    recent_range: str = Query(""),
    seller_id: str = Query(""),
    buyer_id: str = Query(""),
    salesperson: str = Query(""),
    platform: str = Query(""),
    invoice_type: str = Query(""),
    status: str = Query(""),
    keyword: str = Query(""),
):
    filters = parse_invoice_filters(
        start_date=start_date,
        end_date=end_date,
        recent_range=recent_range,
        seller_id=seller_id,
        buyer_id=buyer_id,
        salesperson=salesperson,
        platform=platform,
        invoice_type=invoice_type,
        status=status,
        keyword=keyword,
    )
    job_id = create_background_job("invoice-export", run_export_job, filters, initial_message="已进入后台导出队列")
    return {"ok": True, "job_id": job_id}
