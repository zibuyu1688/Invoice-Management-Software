from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil
from typing import Iterable
from uuid import uuid4

from openpyxl import Workbook
from sqlalchemy.orm import Session

from .config import FILES_DIR
from .models import Buyer, Invoice, InvoiceItem

SPECIAL_ELECTRONIC_VAT_RATE = 0.13
STANDARD_ELECTRONIC_VAT_RATE = 0.01


def infer_invoice_number_from_filename(filename: str | None) -> str:
    if not filename:
        return ""

    stem = Path(filename).stem
    if not stem:
        return ""

    # Prefer long pure-digit segments (common in e-invoice filenames).
    digit_groups = re.findall(r"\d{8,20}", stem)
    if digit_groups:
        return digit_groups[-1]

    # Fallback to alpha-numeric invoice-like token.
    token_groups = re.findall(r"[A-Za-z0-9-]{6,}", stem)
    if token_groups:
        return token_groups[-1]

    return ""


def get_invoice_tax_rate(invoice_type: str) -> float:
    if invoice_type == "增值税发票" or "专用发票" in invoice_type or "电专" in invoice_type:
        return SPECIAL_ELECTRONIC_VAT_RATE
    return STANDARD_ELECTRONIC_VAT_RATE


def resolve_line_item_amounts(
    *,
    quantity: float,
    unit_price_input: str | None,
    amount_with_tax_input: float,
) -> tuple[float, float]:
    quantity_val = float(quantity or 0.0)
    amount_val = round(float(amount_with_tax_input or 0.0), 2)
    unit_text = (unit_price_input or "").strip()

    if unit_text:
        unit_price_val = round(float(unit_text), 6)
        amount_val = round(unit_price_val * quantity_val, 2)
        return unit_price_val, amount_val

    if quantity_val > 0:
        unit_price_val = round(amount_val / quantity_val, 6)
        return unit_price_val, amount_val

    return 0.0, amount_val


def archive_invoice_file(upload_file) -> tuple[str, str] | tuple[None, None]:
    if not upload_file or not upload_file.filename:
        return None, None

    month_dir = FILES_DIR / datetime.now().strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(upload_file.filename).suffix
    safe_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}{ext}"
    stored_path = month_dir / safe_name

    with stored_path.open("wb") as out:
        shutil.copyfileobj(upload_file.file, out)

    return upload_file.filename, str(stored_path)


def create_invoice_with_items(
    db: Session,
    *,
    invoice_type: str,
    invoice_code: str,
    invoice_number: str,
    invoice_date,
    order_number: str,
    order_date,
    tax_rate: float | None,
    seller_id: int,
    buyer_id: int,
    status: str,
    notes: str,
    file_original_name: str | None,
    file_stored_path: str | None,
    item_names: Iterable[str],
    item_specs: Iterable[str],
    item_unit_prices: Iterable[str],
    item_quantities: Iterable[float],
    item_amounts_with_tax: Iterable[float],
) -> Invoice:
    items = []
    amount_total = 0.0
    tax_total = 0.0
    tax_rate_val = tax_rate if tax_rate is not None else get_invoice_tax_rate(invoice_type)

    for name, spec, unit_price_input, qty, total_with_tax_input in zip(
        item_names,
        item_specs,
        item_unit_prices,
        item_quantities,
        item_amounts_with_tax,
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

        items.append(
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

    invoice = Invoice(
        invoice_type=invoice_type,
        invoice_code=invoice_code,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        order_number=order_number,
        order_date=order_date,
        seller_id=seller_id,
        buyer_id=buyer_id,
        amount_without_tax=round(amount_total, 2),
        tax_amount=round(tax_total, 2),
        amount_with_tax=round(amount_total + tax_total, 2),
        status=status,
        notes=notes,
        file_original_name=file_original_name,
        file_stored_path=file_stored_path,
        items=items,
    )
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def export_invoices_xlsx(invoices: list[Invoice], export_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "发票台账"

    ws.append(
        [
            "发票类型",
            "发票号码",
            "开票日期",
            "订单号码",
            "订单日期",
            "销售方",
            "购买方",
            "名称",
            "规格",
            "数量",
            "含税金额",
            "不含税金额",
            "税额",
            "价税合计",
            "状态",
            "原文件名",
            "归档路径",
        ]
    )

    for inv in invoices:
        item_names = "\n".join((item.product_name or "") for item in inv.items)
        item_specs = "\n".join((item.spec_model or "") for item in inv.items)
        item_quantities = "\n".join(str(item.quantity or "") for item in inv.items)
        item_amounts_with_tax = "\n".join(str(item.total_with_tax or "") for item in inv.items)

        ws.append(
            [
                inv.invoice_type,
                inv.invoice_number,
                inv.invoice_date.strftime("%Y-%m-%d") if inv.invoice_date else "",
                inv.order_number or "",
                inv.order_date.strftime("%Y-%m-%d") if inv.order_date else "",
                inv.seller.name if inv.seller else "",
                inv.buyer.name if inv.buyer else "",
                item_names,
                item_specs,
                item_quantities,
                item_amounts_with_tax,
                inv.amount_without_tax,
                inv.tax_amount,
                inv.amount_with_tax,
                inv.status,
                inv.file_original_name or "",
                inv.file_stored_path or "",
            ]
        )

    wb.save(export_path)
    return export_path


def export_customer_profile_xlsx(
    *,
    buyer: Buyer,
    invoices: list[Invoice],
    product_category_map: dict[str, str],
    export_path: Path,
) -> Path:
    wb = Workbook()

    summary_ws = wb.active
    summary_ws.title = "客户画像"

    total_amount = round(sum(float(inv.amount_with_tax or 0.0) for inv in invoices), 2)
    total_count = len(invoices)
    total_quantity = 0.0
    first_purchase_date = ""
    last_purchase_date = ""
    if invoices:
        sorted_invoices = sorted(invoices, key=lambda inv: (inv.invoice_date or datetime.today().date(), inv.id))
        first_purchase_date = sorted_invoices[0].invoice_date.strftime("%Y-%m-%d") if sorted_invoices[0].invoice_date else ""
        last_purchase_date = sorted_invoices[-1].invoice_date.strftime("%Y-%m-%d") if sorted_invoices[-1].invoice_date else ""
    avg_amount = round((total_amount / total_count), 2) if total_count else 0.0

    product_stats: dict[str, dict[str, float]] = {}
    category_stats: dict[str, dict[str, float]] = {}
    recent_details_rows = []
    product_frequency: dict[str, int] = {}

    for inv in sorted(invoices, key=lambda inv: (inv.invoice_date or datetime.today().date(), inv.id), reverse=True):
        invoice_products = set()
        order_qty = 0.0
        detail_names = []
        for item in inv.items:
            product_name = (item.product_name or "未命名商品").strip() or "未命名商品"
            category_name = product_category_map.get(product_name, "未分组")
            qty = float(item.quantity or 0.0)
            amount = float(item.total_with_tax or 0.0)
            total_quantity += qty
            order_qty += qty
            detail_names.append(product_name)
            invoice_products.add(product_name)

            product_stats.setdefault(product_name, {"amount": 0.0, "quantity": 0.0, "frequency": 0})
            product_stats[product_name]["amount"] += amount
            product_stats[product_name]["quantity"] += qty

            category_stats.setdefault(category_name, {"amount": 0.0, "quantity": 0.0})
            category_stats[category_name]["amount"] += amount
            category_stats[category_name]["quantity"] += qty

        for product_name in invoice_products:
            product_frequency[product_name] = product_frequency.get(product_name, 0) + 1

        recent_details_rows.append(
            [
                inv.invoice_date.strftime("%Y-%m-%d") if inv.invoice_date else "",
                inv.invoice_number,
                "、".join(detail_names[:3]) + (" 等" if len(detail_names) > 3 else ""),
                round(order_qty, 2),
                round(float(inv.amount_with_tax or 0.0), 2),
                inv.status or "",
            ]
        )

    summary_ws.append(["客户名称", buyer.name])
    summary_ws.append(["累计采购金额", total_amount])
    summary_ws.append(["累计采购数量", round(total_quantity, 2)])
    summary_ws.append(["采购频次", total_count])
    summary_ws.append(["平均客单价", avg_amount])
    summary_ws.append(["首次采购时间", first_purchase_date])
    summary_ws.append(["最近一次采购时间", last_purchase_date])

    product_ws = wb.create_sheet("商品排行")
    product_ws.append(["商品", "累计金额", "累计数量", "购买频次"])
    for name, stats in sorted(product_stats.items(), key=lambda row: row[1]["amount"], reverse=True):
        product_ws.append([
            name,
            round(stats["amount"], 2),
            round(stats["quantity"], 2),
            product_frequency.get(name, 0),
        ])

    category_ws = wb.create_sheet("品类分布")
    category_ws.append(["品类", "累计金额", "累计数量"])
    for name, stats in sorted(category_stats.items(), key=lambda row: row[1]["amount"], reverse=True):
        category_ws.append([name, round(stats["amount"], 2), round(stats["quantity"], 2)])

    detail_ws = wb.create_sheet("最近采购明细")
    detail_ws.append(["日期", "发票号", "商品摘要", "数量", "金额", "状态"])
    for row in recent_details_rows[:20]:
        detail_ws.append(row)

    wb.save(export_path)
    return export_path
