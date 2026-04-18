from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from .database import Base


class Seller(Base):
    __tablename__ = "sellers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True)
    tax_id = Column(String(64), nullable=True)
    salesperson = Column(String(64), nullable=True)
    address_phone = Column(String(255), nullable=True)
    bank_account = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    invoices = relationship("Invoice", back_populates="seller")
    salespeople = relationship(
        "SellerSalesperson",
        back_populates="seller",
        cascade="all, delete-orphan",
        order_by="SellerSalesperson.id.asc()",
    )


class SellerSalesperson(Base):
    __tablename__ = "seller_salespeople"

    id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(Integer, ForeignKey("sellers.id"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    phone = Column(String(64), nullable=True)
    wechat = Column(String(128), nullable=True)
    department = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    seller = relationship("Seller", back_populates="salespeople")


class Buyer(Base):
    __tablename__ = "buyers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True)
    tax_id = Column(String(64), nullable=True)
    platform = Column(String(32), nullable=True)
    contact_person = Column(String(64), nullable=True)
    contact_phone = Column(String(64), nullable=True)
    wechat_qq = Column(String(128), nullable=True)
    address = Column(String(255), nullable=True)
    shipping_address = Column(String(255), nullable=True)
    bank_name = Column(String(128), nullable=True)
    bank_account_no = Column(String(128), nullable=True)
    notes = Column(Text, nullable=True)
    address_phone = Column(String(255), nullable=True)
    bank_account = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    invoices = relationship("Invoice", back_populates="buyer")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    group_name = Column(String(128), nullable=True)
    name = Column(String(200), nullable=False)
    spec_model = Column(String(128), nullable=True)
    tax_code = Column(String(128), nullable=True)
    default_tax_rate = Column(Float, default=0.13)
    created_at = Column(DateTime, default=datetime.utcnow)


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    invoice_type = Column(String(32), nullable=False)  # "电普" or "电专"
    invoice_code = Column(String(64), nullable=True)
    invoice_number = Column(String(64), nullable=False, index=True)
    invoice_date = Column(Date, nullable=False)
    order_number = Column(String(64), nullable=True, index=True)
    order_date = Column(Date, nullable=True)

    seller_id = Column(Integer, ForeignKey("sellers.id"), nullable=False)
    buyer_id = Column(Integer, ForeignKey("buyers.id"), nullable=False)
    salesperson = Column(String(64), nullable=True)

    amount_without_tax = Column(Float, nullable=False)
    tax_amount = Column(Float, nullable=False)
    amount_with_tax = Column(Float, nullable=False)

    status = Column(String(32), default="待开")
    notes = Column(Text, nullable=True)

    file_original_name = Column(String(255), nullable=True)
    file_stored_path = Column(String(500), nullable=True)
    trade_voucher_original_name = Column(String(255), nullable=True)
    trade_voucher_stored_path = Column(String(500), nullable=True)
    trade_voucher_text = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    seller = relationship("Seller", back_populates="invoices")
    buyer = relationship("Buyer", back_populates="invoices")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)

    product_name = Column(String(255), nullable=False)
    spec_model = Column(String(128), nullable=True)
    tax_code = Column(String(128), nullable=True)
    quantity = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    tax_rate = Column(Float, nullable=False)
    tax_amount = Column(Float, nullable=False)
    total_with_tax = Column(Float, nullable=False)

    invoice = relationship("Invoice", back_populates="items")
