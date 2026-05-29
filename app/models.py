import enum
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, DECIMAL, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

# ==================== ENUMS ====================
class PurchaseStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PARTIALLY_RECEIVED = "partially_received"

class LoanStatus(str, enum.Enum):
    ACTIVE = "active"
    PARTIALLY_PAID = "partially_paid"
    SETTLED = "settled"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"

class LoanPaymentMethod(str, enum.Enum):
    CASH = "cash"
    TICKET = "ticket"
    COUPON = "coupon"
    MIXED = "mixed"

class SaleStatus(str, enum.Enum):
    COMPLETED = "completed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    CANCELLED = "cancelled"

class PaymentMethod(str, enum.Enum):
    CASH = "cash"
    TRANSFER = "transfer"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    MOBILE_MONEY = "mobile_money"
    COUPON = "coupon"
    MIXED = "mixed"

class RefundStatus(str, enum.Enum):
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    COMPLETED = "completed"
    REJECTED = "rejected"

class DiscountType(str, enum.Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"

# ==================== BRANCH MODEL ====================
class Branch(Base):
    __tablename__ = "branches"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    address = Column(Text)
    phone = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    users = relationship("User", back_populates="branch", cascade="all, delete-orphan")
    stock = relationship("Stock", back_populates="branch", cascade="all, delete-orphan")
    sales = relationship("Sale", back_populates="branch", cascade="all, delete-orphan")
    purchases = relationship("Purchase", back_populates="branch", cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrder", back_populates="branch", cascade="all, delete-orphan")
    stock_movements = relationship("StockMovement", back_populates="branch")
    alerts = relationship("Alert", back_populates="branch")
    loans = relationship("Loan", back_populates="branch", cascade="all, delete-orphan")
    bank_accounts = relationship("BankAccount", back_populates="branch", cascade="all, delete-orphan")


# ==================== PRODUCT MODEL ====================
class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    color = Column(String(50))
    size = Column(String(50))
    pages = Column(Integer)
    price = Column(DECIMAL(12, 2), nullable=False)
    cost = Column(DECIMAL(12, 2), nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    stock = relationship("Stock", back_populates="product", cascade="all, delete-orphan")
    sale_items = relationship("SaleItem", back_populates="product")
    purchase_items = relationship("PurchaseItem", back_populates="product")
    purchase_order_items = relationship("PurchaseOrderItem", back_populates="product")
    stock_movements = relationship("StockMovement", back_populates="product")
    alerts = relationship("Alert", back_populates="product")
    loan_items = relationship("LoanItem", back_populates="product")
    refund_items = relationship("RefundItem", back_populates="product")


# ==================== USER MODEL ====================
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)  # admin or salesman
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    branch = relationship("Branch", back_populates="users")
    sales = relationship("Sale", back_populates="user")
    refunds = relationship("Refund", back_populates="user")
    stock_movements = relationship("StockMovement", back_populates="user")
    purchase_orders = relationship("PurchaseOrder", back_populates="creator")
    loans_created = relationship("Loan", foreign_keys="Loan.created_by", back_populates="creator")
    loans_approved = relationship("Loan", foreign_keys="Loan.approved_by", back_populates="approver")
    loan_payments = relationship("LoanPayment", back_populates="recorder")


# ==================== BANK ACCOUNT MODEL ====================
class BankAccount(Base):
    __tablename__ = "bank_accounts"
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    bank_name = Column(String(100), nullable=False)
    account_number = Column(String(50), nullable=False)
    account_name = Column(String(255), nullable=False)
    account_type = Column(String(50), default="checking")  # checking, savings, business
    currency = Column(String(3), default="ETB")
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    branch = relationship("Branch", back_populates="bank_accounts")
    sales = relationship("Sale", back_populates="bank_account")
    refunds = relationship("Refund", back_populates="bank_account")


# ==================== STOCK MODEL ====================
class Stock(Base):
    __tablename__ = "stock"
    __table_args__ = (
        UniqueConstraint('branch_id', 'product_id', name='unique_branch_product'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(DECIMAL(12, 2), default=0)
    reorder_level = Column(DECIMAL(12, 2), default=0)
    
    # Relationships
    branch = relationship("Branch", back_populates="stock")
    product = relationship("Product", back_populates="stock")


# ==================== SALE MODELS (ENHANCED) ====================
class Sale(Base):
    __tablename__ = "sales"
    
    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(50), unique=True, nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    customer_name = Column(String(255))
    customer_phone = Column(String(50))
    customer_email = Column(String(255))
    
    # Financial fields
    subtotal = Column(DECIMAL(12, 2), nullable=False, default=0)
    tax_amount = Column(DECIMAL(12, 2), default=0)
    tax_rate = Column(DECIMAL(5, 2), default=15)  # Tax percentage
    discount_amount = Column(DECIMAL(12, 2), default=0)
    discount_type = Column(String(20), default="percentage")  # percentage, fixed
    shipping_cost = Column(DECIMAL(12, 2), default=0)
    total_amount = Column(DECIMAL(12, 2), nullable=False)
    total_cost = Column(DECIMAL(12, 2), nullable=False)
    
    # Payment fields
    payment_method = Column(String(50), nullable=False, default=PaymentMethod.CASH.value)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    transaction_reference = Column(String(100), nullable=True)  # For transfer reference number
    
    # Status fields
    status = Column(String(50), default=SaleStatus.COMPLETED.value)
    refund_amount = Column(DECIMAL(12, 2), default=0)
    refund_status = Column(String(50), default=RefundStatus.NONE.value)
    
    # Additional fields
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    branch = relationship("Branch", back_populates="sales")
    user = relationship("User", back_populates="sales")
    bank_account = relationship("BankAccount", back_populates="sales")
    items = relationship("SaleItem", back_populates="sale", cascade="all, delete-orphan")
    refunds = relationship("Refund", back_populates="original_sale", cascade="all, delete-orphan")
    loan_payments = relationship("LoanPayment", back_populates="sale")


class SaleItem(Base):
    __tablename__ = "sale_items"
    
    id = Column(Integer, primary_key=True, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(DECIMAL(12, 2), nullable=False)
    unit_price = Column(DECIMAL(12, 2), nullable=False)
    discount_amount = Column(DECIMAL(12, 2), default=0)
    line_total = Column(DECIMAL(12, 2), nullable=False)
    
    # Relationships
    sale = relationship("Sale", back_populates="items")
    product = relationship("Product", back_populates="sale_items")
    loan_items = relationship("LoanItem", back_populates="sale_item")
    refund_items = relationship("RefundItem", back_populates="sale_item")


# ==================== REFUND MODELS ====================
class Refund(Base):
    __tablename__ = "refunds"
    
    id = Column(Integer, primary_key=True, index=True)
    refund_number = Column(String(50), unique=True, nullable=False, index=True)
    original_sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    customer_name = Column(String(255))
    
    # Refund details
    refund_amount = Column(DECIMAL(12, 2), nullable=False)
    refund_reason = Column(Text, nullable=False)
    refund_method = Column(String(50), nullable=False)  # cash, transfer, original_method
    
    # Bank transfer details for refund
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    transaction_reference = Column(String(100), nullable=True)
    
    # Status
    status = Column(String(50), default="pending")  # pending, approved, completed, rejected
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Relationships
    original_sale = relationship("Sale", back_populates="refunds")
    branch = relationship("Branch")
    user = relationship("User", foreign_keys=[user_id], back_populates="refunds")
    approver = relationship("User", foreign_keys=[approved_by])
    bank_account = relationship("BankAccount", back_populates="refunds")
    items = relationship("RefundItem", back_populates="refund", cascade="all, delete-orphan")


class RefundItem(Base):
    __tablename__ = "refund_items"
    
    id = Column(Integer, primary_key=True, index=True)
    refund_id = Column(Integer, ForeignKey("refunds.id"), nullable=False)
    sale_item_id = Column(Integer, ForeignKey("sale_items.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(DECIMAL(12, 2), nullable=False)
    unit_price = Column(DECIMAL(12, 2), nullable=False)
    refund_amount = Column(DECIMAL(12, 2), nullable=False)
    reason = Column(Text, nullable=True)
    
    # Relationships
    refund = relationship("Refund", back_populates="items")
    sale_item = relationship("SaleItem", back_populates="refund_items")
    product = relationship("Product", back_populates="refund_items")


# ==================== PURCHASE MODELS ====================

class PurchaseOrder(Base):
    """Main purchase order table - tracks bulk purchases"""
    __tablename__ = "purchase_orders"
    
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(50), unique=True, nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    supplier = Column(String(200), nullable=False)
    order_date = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expected_delivery_date = Column(DateTime(timezone=True), nullable=True)
    actual_delivery_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default=PurchaseStatus.PENDING.value)
    subtotal = Column(DECIMAL(12, 2), default=0)
    tax_amount = Column(DECIMAL(12, 2), default=0)
    shipping_cost = Column(DECIMAL(12, 2), default=0)
    discount_amount = Column(DECIMAL(12, 2), default=0)
    total_amount = Column(DECIMAL(12, 2), default=0)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    branch = relationship("Branch", back_populates="purchase_orders")
    items = relationship("PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by], back_populates="purchase_orders")


class PurchaseOrderItem(Base):
    """Individual items in a purchase order"""
    __tablename__ = "purchase_order_items"
    
    id = Column(Integer, primary_key=True, index=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity_ordered = Column(DECIMAL(12, 2), nullable=False)
    quantity_received = Column(DECIMAL(12, 2), default=0)
    unit_cost = Column(DECIMAL(12, 2), nullable=False)
    total_cost = Column(DECIMAL(12, 2), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Relationships
    purchase_order = relationship("PurchaseOrder", back_populates="items")
    product = relationship("Product", back_populates="purchase_order_items")


class Purchase(Base):
    __tablename__ = "purchases"
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    supplier_name = Column(String(255))
    total_amount = Column(DECIMAL(12, 2), nullable=False)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    branch = relationship("Branch", back_populates="purchases")
    items = relationship("PurchaseItem", back_populates="purchase", cascade="all, delete-orphan")
    purchase_order = relationship("PurchaseOrder")


class PurchaseItem(Base):
    __tablename__ = "purchase_items"
    
    id = Column(Integer, primary_key=True, index=True)
    purchase_id = Column(Integer, ForeignKey("purchases.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(DECIMAL(12, 2), nullable=False)
    unit_cost = Column(DECIMAL(12, 2), nullable=False)
    
    # Relationships
    purchase = relationship("Purchase", back_populates="items")
    product = relationship("Product", back_populates="purchase_items")


# ==================== LOAN SYSTEM MODELS ====================

class Loan(Base):
    """Track loans given to customers"""
    __tablename__ = "loans"
    
    id = Column(Integer, primary_key=True, index=True)
    loan_number = Column(String(50), unique=True, nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    customer_name = Column(String(255), nullable=False)
    customer_phone = Column(String(50), nullable=True)
    customer_email = Column(String(255), nullable=True)
    loan_date = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    due_date = Column(DateTime(timezone=True), nullable=False)
    total_amount = Column(DECIMAL(12, 2), nullable=False)
    paid_amount = Column(DECIMAL(12, 2), default=0)
    remaining_amount = Column(DECIMAL(12, 2), nullable=False)
    interest_rate = Column(DECIMAL(5, 2), default=0)
    interest_amount = Column(DECIMAL(12, 2), default=0)
    status = Column(String(50), default=LoanStatus.ACTIVE.value)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    branch = relationship("Branch", back_populates="loans")
    items = relationship("LoanItem", back_populates="loan", cascade="all, delete-orphan")
    payments = relationship("LoanPayment", back_populates="loan", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by], back_populates="loans_created")
    approver = relationship("User", foreign_keys=[approved_by], back_populates="loans_approved")


class LoanItem(Base):
    """Items included in a loan"""
    __tablename__ = "loan_items"
    
    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(DECIMAL(12, 2), nullable=False)
    unit_price = Column(DECIMAL(12, 2), nullable=False)
    line_total = Column(DECIMAL(12, 2), nullable=False)
    sale_item_id = Column(Integer, ForeignKey("sale_items.id"), nullable=True)
    
    # Relationships
    loan = relationship("Loan", back_populates="items")
    product = relationship("Product", back_populates="loan_items")
    sale_item = relationship("SaleItem", back_populates="loan_items")


class LoanPayment(Base):
    """Track loan payments/settlements"""
    __tablename__ = "loan_payments"
    
    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False)
    payment_number = Column(String(50), unique=True, nullable=False, index=True)
    payment_date = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    amount = Column(DECIMAL(12, 2), nullable=False)
    payment_method = Column(String(50), nullable=False)  # cash, ticket, coupon, mixed
    reference_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    recorded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    loan = relationship("Loan", back_populates="payments")
    recorder = relationship("User", back_populates="loan_payments")
    sale = relationship("Sale", back_populates="loan_payments")


class LoanSummary(Base):
    """Daily loan summary for reporting"""
    __tablename__ = "loan_summaries"
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    summary_date = Column(DateTime(timezone=True), nullable=False)
    total_loans_issued = Column(Integer, default=0)
    total_loan_amount = Column(DECIMAL(12, 2), default=0)
    total_repayments = Column(DECIMAL(12, 2), default=0)
    total_outstanding = Column(DECIMAL(12, 2), default=0)
    active_loans_count = Column(Integer, default=0)
    overdue_loans_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    branch = relationship("Branch")


# ==================== STOCK MOVEMENT MODEL ====================
# ==================== STOCK MOVEMENT MODEL ====================
class StockMovement(Base):
    __tablename__ = "stock_movements"
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    change_qty = Column(DECIMAL(12, 2), nullable=False)
    movement_type = Column(String(50), nullable=False)  # add, adjustment, sale, purchase, transfer_in, transfer_out, loan, refund
    reference_id = Column(Integer)  # Can reference sale_id, purchase_id, loan_id, refund_id, etc.
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    branch = relationship("Branch", back_populates="stock_movements")
    product = relationship("Product", back_populates="stock_movements")
    user = relationship("User", back_populates="stock_movements")
    
    
    
    # ==================== ALERT MODEL ====================
class Alert(Base):
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True))
    
    # Relationships
    branch = relationship("Branch", back_populates="alerts")
    product = relationship("Product", back_populates="alerts")


# ==================== SETTINGS MODELS ====================

class SystemSetting(Base):
    """Store system-wide settings"""
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(50), nullable=False, index=True)  # general, coupon, notification, backup, tax, payment
    key = Column(String(100), nullable=False)
    value = Column(Text, nullable=True)  # JSON string value
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint('category', 'key', name='unique_category_key'),
    )


class BackupRecord(Base):
    """Track database backups"""
    __tablename__ = "backup_records"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    size_mb = Column(DECIMAL(10, 2), default=0)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship
    creator = relationship("User", foreign_keys=[created_by])


class SystemLog(Base):
    """Track system activities and errors"""
    __tablename__ = "system_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    log_type = Column(String(50), nullable=False)  # info, warning, error, backup, settings
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship
    user = relationship("User", foreign_keys=[user_id])


# ==================== TEMP ITEM MODEL ====================
class TempItemStatus(str, enum.Enum):
    PENDING = "pending"
    RECEIVED = "received"
    CANCELLED = "cancelled"

class TempItem(Base):
    """Temporary item registration for salesmen"""
    __tablename__ = "temp_items"
    
    id = Column(Integer, primary_key=True, index=True)
    item_number = Column(String(50), unique=True, nullable=False, index=True)
    item_name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    quantity = Column(Integer, default=1)
    unit_price = Column(DECIMAL(12, 2), nullable=True)
    customer_name = Column(String(255), nullable=True)
    customer_phone = Column(String(50), nullable=True)
    status = Column(String(50), default=TempItemStatus.PENDING.value)
    registered_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    registered_at = Column(DateTime(timezone=True), server_default=func.now())
    received_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    received_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Relationships
    registrar = relationship("User", foreign_keys=[registered_by])
    receiver = relationship("User", foreign_keys=[received_by])


# ==================== Add reverse relationships ====================

# Add these after all models are defined to avoid circular references
Product.purchase_order_items = relationship("PurchaseOrderItem", back_populates="product")
Product.loan_items = relationship("LoanItem", back_populates="product")
Product.refund_items = relationship("RefundItem", back_populates="product")
SaleItem.refund_items = relationship("RefundItem", back_populates="sale_item")
Branch.purchase_orders = relationship("PurchaseOrder", back_populates="branch")
Branch.loans = relationship("Loan", back_populates="branch")
Branch.bank_accounts = relationship("BankAccount", back_populates="branch")
User.purchase_orders = relationship("PurchaseOrder", back_populates="creator")
User.loans_created = relationship("Loan", foreign_keys=[Loan.created_by], back_populates="creator")
User.loans_approved = relationship("Loan", foreign_keys=[Loan.approved_by], back_populates="approver")
User.loan_payments = relationship("LoanPayment", back_populates="recorder")
User.refunds = relationship("Refund", foreign_keys=[Refund.user_id], back_populates="user")