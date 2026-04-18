from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import os

from fastapi import HTTPException
from sqlalchemy.orm import Session, selectinload

from .config import EXPORTS_DIR
from .models import Buyer, Invoice, InvoiceItem, Product, Seller
from .services import (
    archive_invoice_file_bytes,
    create_invoice_with_items,
    export_invoice_image_bundle,
    get_invoice_tax_rate,
    infer_invoice_number_from_filename,
    resolve_line_item_amounts,
)

INVOICE_TYPE_OPTIONS = [
    "普通发票",
    "增值税发票",
]

INVOICE_TAX_RATE_OPTIONS = [0.01, 0.03, 0.13]


def snapshot_upload_file(upload_file) -> dict | None:
    if not upload_file or not upload_file.filename:
        return None
    content = upload_file.file.read()
    return {
        "filename": upload_file.filename,
        "content": content,
    }


def parse_invoice_filters(
    *,
    start_date: str = "",
    end_date: str = "",
    recent_range: str = "",
    seller_id: str = "",
    buyer_id: str = "",
    salesperson: str = "",
    platform: str = "",
    invoice_type: str = "",
    status: str = "",
    keyword: str = "",
) -> dict:
    parsed_start_date = None
    parsed_end_date = None
    parsed_seller_id = None
    parsed_buyer_id = None

    start_date_text = start_date.strip()
    end_date_text = end_date.strip()
    recent_range_text = recent_range.strip()
    seller_id_text = seller_id.strip()
    buyer_id_text = buyer_id.strip()
    salesperson_text = salesperson.strip()
    platform_text = platform.strip()
    invoice_type_text = invoice_type.strip()
    status_text = status.strip()
    keyword_text = keyword.strip()

    today = date.today()
    range_days = {
        "7d": 7,
        "1m": 30,
        "3m": 90,
        "6m": 180,
        "9m": 270,
        "1y": 365,
    }

    if not start_date_text and not end_date_text:
        if recent_range_text in range_days:
            days = range_days[recent_range_text]
            parsed_end_date = today
            parsed_start_date = today - timedelta(days=days - 1)
        elif recent_range_text == "today":
            parsed_start_date = today
            parsed_end_date = today
        elif recent_range_text == "yesterday":
            target_day = today - timedelta(days=1)
            parsed_start_date = target_day
            parsed_end_date = target_day
        elif recent_range_text == "month":
            parsed_start_date = today.replace(day=1)
            parsed_end_date = today

    if start_date_text:
        try:
            parsed_start_date = date.fromisoformat(start_date_text)
        except ValueError:
            raise HTTPException(status_code=400, detail="开始日期格式不正确，请使用 YYYY-MM-DD")

    if end_date_text:
        try:
            parsed_end_date = date.fromisoformat(end_date_text)
        except ValueError:
            raise HTTPException(status_code=400, detail="结束日期格式不正确，请使用 YYYY-MM-DD")

    if seller_id_text:
        try:
            parsed_seller_id = int(seller_id_text)
        except ValueError:
            raise HTTPException(status_code=400, detail="销售方参数不正确")

    if buyer_id_text:
        try:
            parsed_buyer_id = int(buyer_id_text)
        except ValueError:
            raise HTTPException(status_code=400, detail="购买方参数不正确")

    return {
        "parsed_start_date": parsed_start_date,
        "parsed_end_date": parsed_end_date,
        "parsed_seller_id": parsed_seller_id,
        "parsed_buyer_id": parsed_buyer_id,
        "salesperson_text": salesperson_text,
        "platform_text": platform_text,
        "invoice_type_text": invoice_type_text,
        "status_text": status_text,
        "keyword_text": keyword_text,
    }


def query_invoices(db: Session, filters: dict):
    query = db.query(Invoice).options(
        selectinload(Invoice.items),
        selectinload(Invoice.seller),
        selectinload(Invoice.buyer),
    )
    if filters["parsed_start_date"]:
        query = query.filter(Invoice.invoice_date >= filters["parsed_start_date"])
    if filters["parsed_end_date"]:
        query = query.filter(Invoice.invoice_date <= filters["parsed_end_date"])
    if filters["parsed_seller_id"]:
        query = query.filter(Invoice.seller_id == filters["parsed_seller_id"])
    if filters["parsed_buyer_id"]:
        query = query.filter(Invoice.buyer_id == filters["parsed_buyer_id"])
    if filters["salesperson_text"]:
        query = query.filter(Invoice.salesperson.contains(filters["salesperson_text"]))
    if filters["platform_text"]:
        query = query.filter(Invoice.buyer.has(Buyer.platform == filters["platform_text"]))
    if filters["invoice_type_text"]:
        query = query.filter(Invoice.invoice_type == filters["invoice_type_text"])
    if filters["status_text"]:
        query = query.filter(Invoice.status == filters["status_text"])
    if filters["keyword_text"]:
        query = query.filter(
            Invoice.invoice_number.contains(filters["keyword_text"])
            | Invoice.order_number.contains(filters["keyword_text"])
            | Invoice.notes.contains(filters["keyword_text"])
        )
    return query.order_by(Invoice.invoice_date.desc(), Invoice.id.desc())


def create_export_file(db: Session, filters: dict) -> Path:
    invoices = query_invoices(db, filters).all()
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    export_path = EXPORTS_DIR / f"invoice_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    export_invoice_image_bundle(invoices, export_path)
    return export_path


def create_invoice_record(
    db: Session,
    *,
    seller_id: int,
    buyer_id: int,
    salesperson: str,
    invoice_type: str,
    tax_rate: str,
    invoice_number: str,
    invoice_date: str,
    order_number: str,
    order_date: str,
    status: str,
    notes: str,
    item_name: list[str],
    item_spec: list[str],
    item_unit_price: list[str],
    item_quantity: list[int],
    item_amount_with_tax: list[float],
    invoice_file_snapshot: dict | None,
    trade_voucher_snapshot: dict | None,
    trade_voucher_text: str,
) -> Invoice:
    if len(item_name) == 0:
        raise HTTPException(status_code=400, detail="至少需要一条商品明细")

    seller = db.get(Seller, seller_id)
    buyer = db.get(Buyer, buyer_id)
    if not seller or not buyer:
        raise HTTPException(status_code=400, detail="销售方或购买方不存在")
    if invoice_type not in INVOICE_TYPE_OPTIONS:
        raise HTTPException(status_code=400, detail="发票类型不正确")

    try:
        selected_tax_rate = float(tax_rate)
    except ValueError:
        raise HTTPException(status_code=400, detail="税率参数不正确")
    if selected_tax_rate not in INVOICE_TAX_RATE_OPTIONS:
        raise HTTPException(status_code=400, detail="税率仅支持 1%、3%、13%")

    file_original_name = None
    file_stored_path = None
    if invoice_file_snapshot:
        file_original_name, file_stored_path = archive_invoice_file_bytes(
            invoice_file_snapshot["filename"],
            invoice_file_snapshot["content"],
        )

    trade_voucher_original_name = None
    trade_voucher_stored_path = None
    if trade_voucher_snapshot:
        trade_voucher_original_name, trade_voucher_stored_path = archive_invoice_file_bytes(
            trade_voucher_snapshot["filename"],
            trade_voucher_snapshot["content"],
            bucket_name="trade-vouchers",
        )

    manual_invoice_number = invoice_number.strip()
    inferred_invoice_number = ""
    if not manual_invoice_number and file_original_name:
        inferred_invoice_number = infer_invoice_number_from_filename(file_original_name)
    normalized_number = manual_invoice_number or inferred_invoice_number

    normalized_date = date.today()
    invoice_date_text = invoice_date.strip()
    if invoice_date_text:
        try:
            normalized_date = date.fromisoformat(invoice_date_text)
        except ValueError:
            raise HTTPException(status_code=400, detail="开票日期格式不正确，请使用 YYYY-MM-DD")

    normalized_order_number = order_number.strip()
    parsed_order_date = None
    order_date_text = order_date.strip()
    if order_date_text:
        try:
            parsed_order_date = date.fromisoformat(order_date_text)
        except ValueError:
            raise HTTPException(status_code=400, detail="订单日期格式不正确，请使用 YYYY-MM-DD")

    if file_original_name and status == "待开":
        status = "已开"

    invoice = create_invoice_with_items(
        db,
        invoice_type=invoice_type,
        invoice_code="",
        invoice_number=normalized_number,
        invoice_date=normalized_date,
        order_number=normalized_order_number,
        order_date=parsed_order_date,
        tax_rate=selected_tax_rate,
        seller_id=seller_id,
        buyer_id=buyer_id,
        status=status,
        notes=notes,
        file_original_name=file_original_name,
        file_stored_path=file_stored_path,
        item_names=item_name,
        item_specs=item_spec,
        item_unit_prices=item_unit_price,
        item_quantities=item_quantity,
        item_amounts_with_tax=item_amount_with_tax,
    )
    invoice.salesperson = salesperson.strip()
    invoice.trade_voucher_original_name = trade_voucher_original_name
    invoice.trade_voucher_stored_path = trade_voucher_stored_path
    invoice.trade_voucher_text = trade_voucher_text.strip()
    db.commit()
    db.refresh(invoice)
    return invoice


def update_invoice_record(
    db: Session,
    *,
    invoice_id: int,
    seller_id: int,
    buyer_id: int,
    salesperson: str,
    invoice_type: str,
    tax_rate: str,
    invoice_number: str,
    invoice_date: str,
    order_number: str,
    order_date: str,
    status: str,
    notes: str,
    item_name: list[str],
    item_spec: list[str],
    item_unit_price: list[str],
    item_quantity: list[int],
    item_amount_with_tax: list[float],
    remove_invoice_file: str,
    invoice_file_snapshot: dict | None,
    trade_voucher_snapshot: dict | None,
    trade_voucher_text: str,
) -> Invoice:
    invoice = db.get(Invoice, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="发票不存在")
    if len(item_name) == 0:
        raise HTTPException(status_code=400, detail="至少需要一条商品明细")

    seller = db.get(Seller, seller_id)
    buyer = db.get(Buyer, buyer_id)
    if not seller or not buyer:
        raise HTTPException(status_code=400, detail="销售方或购买方不存在")
    if invoice_type not in INVOICE_TYPE_OPTIONS:
        raise HTTPException(status_code=400, detail="发票类型不正确")

    try:
        selected_tax_rate = float(tax_rate)
    except ValueError:
        raise HTTPException(status_code=400, detail="税率参数不正确")
    if selected_tax_rate not in INVOICE_TAX_RATE_OPTIONS:
        raise HTTPException(status_code=400, detail="税率仅支持 1%、3%、13%")

    remove_file_requested = remove_invoice_file.strip().lower() in {"1", "true", "on", "yes"}
    if remove_file_requested and invoice.file_stored_path:
        if os.path.exists(invoice.file_stored_path):
            os.remove(invoice.file_stored_path)
        invoice.file_original_name = None
        invoice.file_stored_path = None

    inferred_invoice_number = ""

    if invoice_file_snapshot:
        new_original_name, new_stored_path = archive_invoice_file_bytes(
            invoice_file_snapshot["filename"],
            invoice_file_snapshot["content"],
        )
        if invoice.file_stored_path and os.path.exists(invoice.file_stored_path):
            os.remove(invoice.file_stored_path)
        invoice.file_original_name = new_original_name
        invoice.file_stored_path = new_stored_path
        inferred_invoice_number = infer_invoice_number_from_filename(new_original_name)
        if status == "待开":
            status = "已开"

    if trade_voucher_snapshot:
        new_voucher_name, new_voucher_path = archive_invoice_file_bytes(
            trade_voucher_snapshot["filename"],
            trade_voucher_snapshot["content"],
            bucket_name="trade-vouchers",
        )
        if invoice.trade_voucher_stored_path and os.path.exists(invoice.trade_voucher_stored_path):
            os.remove(invoice.trade_voucher_stored_path)
        invoice.trade_voucher_original_name = new_voucher_name
        invoice.trade_voucher_stored_path = new_voucher_path

    invoice.seller_id = seller_id
    invoice.buyer_id = buyer_id
    invoice.salesperson = salesperson.strip()
    invoice.invoice_type = invoice_type
    invoice.invoice_code = ""
    invoice.invoice_number = invoice_number.strip() or inferred_invoice_number

    invoice_date_text = invoice_date.strip()
    if invoice_date_text:
        try:
            parsed_invoice_date = date.fromisoformat(invoice_date_text)
        except ValueError:
            raise HTTPException(status_code=400, detail="开票日期格式不正确，请使用 YYYY-MM-DD")
        invoice.invoice_date = parsed_invoice_date
    else:
        invoice.invoice_date = invoice.invoice_date or date.today()

    invoice.order_number = order_number.strip() or None
    order_date_text = order_date.strip()
    if order_date_text:
        try:
            invoice.order_date = date.fromisoformat(order_date_text)
        except ValueError:
            raise HTTPException(status_code=400, detail="订单日期格式不正确，请使用 YYYY-MM-DD")
    else:
        invoice.order_date = None

    invoice.status = status
    invoice.notes = notes
    invoice.trade_voucher_text = trade_voucher_text.strip()

    invoice.items.clear()
    amount_total = 0.0
    tax_total = 0.0
    tax_rate_val = selected_tax_rate
    for name, spec, unit_price_input, qty, total_with_tax_input in zip(
        item_name,
        item_spec,
        item_unit_price,
        item_quantity,
        item_amount_with_tax,
    ):
        qty_val = float(qty)
        unit_price_with_tax, total = resolve_line_item_amounts(
            quantity=qty_val,
            unit_price_input=unit_price_input,
            amount_with_tax_input=total_with_tax_input,
        )
        amount = round(total / (1 + tax_rate_val), 2)
        tax_amount = round(total - amount, 2)

        amount_total += amount
        tax_total += tax_amount

        invoice.items.append(
            InvoiceItem(
                product_name=name,
                spec_model=spec,
                tax_code="",
                quantity=qty_val,
                unit_price=unit_price_with_tax,
                amount=amount,
                tax_rate=tax_rate_val,
                tax_amount=tax_amount,
                total_with_tax=total,
            )
        )

    invoice.amount_without_tax = round(amount_total, 2)
    invoice.tax_amount = round(tax_total, 2)
    invoice.amount_with_tax = round(amount_total + tax_total, 2)

    db.commit()
    db.refresh(invoice)
    return invoice