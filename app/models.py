# app/models.py
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, Date, ForeignKey, DECIMAL, UniqueConstraint, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base
import enum

# ==================== ENUMS ====================
class UserRole(str, enum.Enum):
    ADMIN = "admin"
    SALESMAN = "salesman"
    PRIVILEGED_SALES = "privileged_sales"

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
    ORIGINAL_METHOD = "original_method"

class RefundStatus(str, enum.Enum):
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    COMPLETED = "completed"
    REJECTED = "rejected"

class DiscountType(str, enum.Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"

# ==================== WALLET ENUMS ====================
class WalletTransactionType(str, enum.Enum):
    DEPOSIT = "deposit"           # Money added to wallet (manual deposit)
    WITHDRAWAL = "withdrawal"      # Money taken out (manual withdrawal)
    PURCHASE = "purchase"          # Money spent on purchase order
    RESTOCK = "restock"            # Money spent on restocking
    REFUND = "refund"              # Money refunded to customer (deducted from wallet)
    ADJUSTMENT = "adjustment"      # Manual adjustment
    TRANSFER = "transfer"          # Transfer between wallets

class WalletTransactionStatus(str, enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

class WalletType(str, enum.Enum):
    VAT = "vat"                    # VAT-tracked wallet
    REGULAR = "regular"            # Regular stock wallet
    PETTY_CASH = "petty_cash"      # Petty cash wallet
    EXPENSE = "expense"            # Expense wallet
    CUSTOM = "custom"              # Custom wallet type

class WalletPurpose(str, enum.Enum):
    VAT_OPERATIONS = "vat_operations"
    REGULAR_STOCK = "regular_stock"
    PETTY_CASH = "petty_cash"
    OPERATING_EXPENSES = "operating_expenses"
    MARKETING = "marketing"
    MAINTENANCE = "maintenance"
    OTHER = "other"

class WalletTransactionMethod(str, enum.Enum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    CARD = "card"
    MOBILE_MONEY = "mobile_money"
    INTERNAL_TRANSFER = "internal_transfer"

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
    damaged_goods = relationship("DamagedGoods", back_populates="branch", cascade="all, delete-orphan")
    vat_purchases = relationship("VATPurchase", back_populates="branch", cascade="all, delete-orphan")
    vat_sales = relationship("VATSale", back_populates="branch", cascade="all, delete-orphan")
    vat_summaries = relationship("VATSummary", back_populates="branch", cascade="all, delete-orphan")
    # Wallet relationships
    wallets = relationship("Wallet", back_populates="branch", cascade="all, delete-orphan")
    wallet_summaries = relationship("WalletSummary", back_populates="branch", cascade="all, delete-orphan")


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
    damaged_goods_reports = relationship("DamagedGoods", back_populates="product", cascade="all, delete-orphan")
    vat_purchases = relationship("VATPurchase", back_populates="product", cascade="all, delete-orphan")
    vat_sales = relationship("VATSale", back_populates="product", cascade="all, delete-orphan")


# ==================== USER MODEL ====================
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    branch = relationship("Branch", back_populates="users")
    sales = relationship("Sale", back_populates="user")
    refunds = relationship("Refund", foreign_keys="Refund.user_id", back_populates="user")
    stock_movements = relationship("StockMovement", back_populates="user")
    purchase_orders = relationship("PurchaseOrder", back_populates="creator")
    loans_created = relationship("Loan", foreign_keys="Loan.created_by", back_populates="creator")
    loans_approved = relationship("Loan", foreign_keys="Loan.approved_by", back_populates="approver")
    loan_payments = relationship("LoanPayment", back_populates="recorder")
    
    # Damaged goods relationships
    damaged_goods_reported = relationship("DamagedGoods", foreign_keys="DamagedGoods.reported_by", back_populates="reporter")
    damaged_goods_approved = relationship("DamagedGoods", foreign_keys="DamagedGoods.approved_by", back_populates="approver")
    damaged_goods_processed = relationship("DamagedGoods", foreign_keys="DamagedGoods.processed_by", back_populates="processor")
    
    # VAT relationships
    vat_purchases_created = relationship("VATPurchase", foreign_keys="VATPurchase.created_by", back_populates="creator")
    vat_sales_created = relationship("VATSale", foreign_keys="VATSale.created_by", back_populates="creator")
    vat_summaries_created = relationship("VATSummary", foreign_keys="VATSummary.created_by", back_populates="creator")
    vat_rates_created = relationship("VATRateHistory", foreign_keys="VATRateHistory.created_by", back_populates="creator")
    
    # Wallet relationships
    wallet_transactions_created = relationship("WalletTransaction", foreign_keys="WalletTransaction.created_by", back_populates="creator")
    wallets_created = relationship("Wallet", foreign_keys="Wallet.created_by", back_populates="creator")
    bank_accounts_created = relationship("BankAccount", foreign_keys="BankAccount.created_by", back_populates="creator")
    bank_transactions_reconciled = relationship("BankTransaction", foreign_keys="BankTransaction.reconciled_by", back_populates="reconciler")
    
    # Helper methods
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value
    
    def is_privileged(self) -> bool:
        return self.role in [UserRole.ADMIN.value, UserRole.PRIVILEGED_SALES.value]
    
    def can_create_loans(self) -> bool:
        return self.is_privileged()
    
    def can_approve_loans(self) -> bool:
        return self.is_admin()
    
    def can_process_refunds(self) -> bool:
        return self.is_privileged()
    
    def can_manage_users(self) -> bool:
        return self.is_admin()
    
    def can_manage_branches(self) -> bool:
        return self.is_admin()
    
    def can_view_reports(self) -> bool:
        return True
    
    def can_export_data(self) -> bool:
        return self.is_admin()


# ==================== BANK ACCOUNT MODEL ====================
class BankAccount(Base):
    __tablename__ = "bank_accounts"
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    
    # Bank details
    bank_name = Column(String(100), nullable=False)
    branch_name = Column(String(100), nullable=True)
    account_number = Column(String(50), nullable=False)
    account_name = Column(String(255), nullable=False)
    account_type = Column(String(50), default="checking")
    iban = Column(String(50), nullable=True)
    swift_code = Column(String(20), nullable=True)
    
    # Financial details
    currency = Column(String(3), default="ETB")
    current_balance = Column(DECIMAL(15, 2), default=0)
    
    # Account settings
    is_active = Column(Boolean, default=True)
    is_primary = Column(Boolean, default=False)
    account_category = Column(String(20), default="regular")
    
    # Reconciliation
    last_reconciled_at = Column(DateTime(timezone=True), nullable=True)
    last_reconciled_balance = Column(DECIMAL(15, 2), nullable=True)
    
    # Metadata
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    branch = relationship("Branch", back_populates="bank_accounts")
    wallets = relationship("Wallet", back_populates="bank_account")
    bank_transactions = relationship("BankTransaction", back_populates="bank_account", cascade="all, delete-orphan")
    sales = relationship("Sale", back_populates="bank_account")
    refunds = relationship("Refund", back_populates="bank_account")
    purchase_orders = relationship("PurchaseOrder", back_populates="bank_account")
    creator = relationship("User", foreign_keys=[created_by], back_populates="bank_accounts_created")
    
    __table_args__ = (
        UniqueConstraint('branch_id', 'account_number', name='unique_branch_account'),
        Index('idx_bank_account_branch', 'branch_id'),
        Index('idx_bank_account_active', 'is_active'),
        Index('idx_bank_account_category', 'account_category'),
    )


# ==================== STOCK MODEL ====================
class Stock(Base):
    __tablename__ = "stock"
    __table_args__ = (
        UniqueConstraint('branch_id', 'product_id', name='unique_branch_product'),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    quantity = Column(DECIMAL(12, 2), default=0)
    quantity_with_vat = Column(DECIMAL(12, 2), default=0)
    quantity_without_vat = Column(DECIMAL(12, 2), default=0)
    reorder_level = Column(DECIMAL(12, 2), default=0)
    
    # Relationships
    branch = relationship("Branch", back_populates="stock")
    product = relationship("Product", back_populates="stock")


# ==================== SALE MODELS ====================
class Sale(Base):
    __tablename__ = "sales"
    
    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(50), unique=True, nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    customer_name = Column(String(255))
    customer_phone = Column(String(50))
    customer_email = Column(String(255))
    
    subtotal = Column(DECIMAL(12, 2), nullable=False, default=0)
    tax_amount = Column(DECIMAL(12, 2), default=0)
    tax_rate = Column(DECIMAL(5, 2), default=15)
    discount_amount = Column(DECIMAL(12, 2), default=0)
    discount_type = Column(String(20), default="percentage")
    shipping_cost = Column(DECIMAL(12, 2), default=0)
    total_amount = Column(DECIMAL(12, 2), nullable=False)
    total_cost = Column(DECIMAL(12, 2), nullable=False)
    
    payment_method = Column(String(50), nullable=False, default=PaymentMethod.CASH.value)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    transaction_reference = Column(String(100), nullable=True)
    
    status = Column(String(50), default=SaleStatus.COMPLETED.value)
    refund_amount = Column(DECIMAL(12, 2), default=0)
    refund_status = Column(String(50), default=RefundStatus.NONE.value)
    
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
    vat_sales = relationship("VATSale", back_populates="sale", cascade="all, delete-orphan")


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
    vat_sale = relationship("VATSale", back_populates="sale_item", uselist=False)


# ==================== REFUND MODELS ====================
class Refund(Base):
    __tablename__ = "refunds"
    
    id = Column(Integer, primary_key=True, index=True)
    refund_number = Column(String(50), unique=True, nullable=False, index=True)
    original_sale_id = Column(Integer, ForeignKey("sales.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    customer_name = Column(String(255))
    
    refund_amount = Column(DECIMAL(12, 2), nullable=False)
    refund_reason = Column(Text, nullable=False)
    refund_method = Column(String(50), nullable=False)
    
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    transaction_reference = Column(String(100), nullable=True)
    
    status = Column(String(50), default="pending")
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    
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
    __tablename__ = "purchase_orders"
    
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(50), unique=True, nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    supplier = Column(String(200), nullable=False)
    order_date = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expected_delivery_date = Column(DateTime(timezone=True), nullable=True)
    actual_delivery_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(50), default=PurchaseStatus.PENDING.value)
    
    # Financial fields
    subtotal = Column(DECIMAL(12, 2), default=0)
    vat_rate = Column(DECIMAL(5, 2), default=15.00)
    vat_amount = Column(DECIMAL(12, 2), default=0)
    tax_amount = Column(DECIMAL(12, 2), default=0)
    shipping_cost = Column(DECIMAL(12, 2), default=0)
    
    # REMOVED: discount_amount = Column(DECIMAL(12, 2), default=0)
    # ADDED: Labour cost fields (replaces discount)
    labour_cost = Column(DECIMAL(12, 2), default=0)
    labour_cost_description = Column(Text, nullable=True)
    
    total_amount = Column(DECIMAL(12, 2), default=0)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    payment_reference = Column(String(100), nullable=True)
    payment_date = Column(DateTime(timezone=True), nullable=True)
    
    # Wallet payment fields
    use_wallet_payment = Column(Boolean, default=False)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=True)
    wallet_transaction_id = Column(Integer, ForeignKey("wallet_transactions.id"), nullable=True)
    
    # Relationships
    branch = relationship("Branch", back_populates="purchase_orders")
    items = relationship("PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by], back_populates="purchase_orders")
    bank_account = relationship("BankAccount", back_populates="purchase_orders")
    vat_purchases = relationship("VATPurchase", back_populates="purchase_order", cascade="all, delete-orphan")
    wallet = relationship("Wallet", foreign_keys=[wallet_id])
    wallet_transaction = relationship("WalletTransaction", foreign_keys=[wallet_transaction_id])


class PurchaseOrderItem(Base):
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
    
    # Financial fields
    subtotal = Column(DECIMAL(12, 2), default=0)
    vat_amount = Column(DECIMAL(12, 2), default=0)
    shipping_cost = Column(DECIMAL(12, 2), default=0)
    
    # Labour cost fields (replaces discount)
    labour_cost = Column(DECIMAL(12, 2), default=0)
    labour_cost_description = Column(Text, nullable=True)
    
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


# ==================== LOAN MODELS ====================
class Loan(Base):
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
    
    requires_approval = Column(Boolean, default=True)
    approval_status = Column(String(50), default="pending")
    
    # Relationships
    branch = relationship("Branch", back_populates="loans")
    items = relationship("LoanItem", back_populates="loan", cascade="all, delete-orphan")
    payments = relationship("LoanPayment", back_populates="loan", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by], back_populates="loans_created")
    approver = relationship("User", foreign_keys=[approved_by], back_populates="loans_approved")


class LoanItem(Base):
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
    __tablename__ = "loan_payments"
    
    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False)
    payment_number = Column(String(50), unique=True, nullable=False, index=True)
    payment_date = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    amount = Column(DECIMAL(12, 2), nullable=False)
    payment_method = Column(String(50), nullable=False)
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
class StockMovement(Base):
    __tablename__ = "stock_movements"
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    change_qty = Column(DECIMAL(12, 2), nullable=False)
    movement_type = Column(String(50), nullable=False)
    with_vat = Column(Boolean, default=True)
    reference_id = Column(Integer)
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
    __tablename__ = "system_settings"
    
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(50), nullable=False, index=True)
    key = Column(String(100), nullable=False)
    value = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    __table_args__ = (
        UniqueConstraint('category', 'key', name='unique_category_key'),
    )


class BackupRecord(Base):
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
    __tablename__ = "system_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    log_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship
    user = relationship("User", foreign_keys=[user_id])


# ==================== DAMAGED GOODS MODEL ====================
class DamagedGoodsStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSED = "processed"

class DamagedGoods(Base):
    __tablename__ = "damaged_goods"
    
    id = Column(Integer, primary_key=True, index=True)
    report_number = Column(String(50), unique=True, nullable=False, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(DECIMAL(12, 2), nullable=False)
    reason = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    reported_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    reported_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(50), default=DamagedGoodsStatus.PENDING.value)
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    processed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    branch = relationship("Branch", foreign_keys=[branch_id], back_populates="damaged_goods")
    product = relationship("Product", foreign_keys=[product_id], back_populates="damaged_goods_reports")
    reporter = relationship("User", foreign_keys=[reported_by], back_populates="damaged_goods_reported")
    approver = relationship("User", foreign_keys=[approved_by], back_populates="damaged_goods_approved")
    processor = relationship("User", foreign_keys=[processed_by], back_populates="damaged_goods_processed")

    __table_args__ = (
        Index('idx_damaged_branch', 'branch_id'),
        Index('idx_damaged_status', 'status'),
        Index('idx_damaged_date', 'reported_at'),
    )

# ==================== TEMP ITEM MODEL ====================
class TempItemStatus(str, enum.Enum):
    PENDING = "pending"
    RECEIVED = "received"
    CANCELLED = "cancelled"

class TempItem(Base):
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


# ==================== VAT TRACKING MODELS ====================
class VATTransactionType(str, enum.Enum):
    PURCHASE = "purchase"
    SALE = "sale"

class VATStatus(str, enum.Enum):
    PENDING = "pending"
    FILED = "filed"
    PAID = "paid"
    CANCELLED = "cancelled"

class VATPurchase(Base):
    __tablename__ = "vat_purchases"
    
    id = Column(Integer, primary_key=True, index=True)
    vat_number = Column(String(50), unique=True, nullable=False, index=True)
    purchase_order_id = Column(Integer, ForeignKey("purchase_orders.id"), nullable=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    product_name = Column(String(255), nullable=True)
    product_group = Column(String(100), nullable=True)
    sku = Column(String(100), nullable=True)
    
    quantity = Column(DECIMAL(12, 2), nullable=False)
    unit_cost = Column(DECIMAL(12, 2), nullable=False)
    total_cost = Column(DECIMAL(12, 2), nullable=False)
    
    vat_rate = Column(DECIMAL(5, 2), default=15.00)
    vat_amount = Column(DECIMAL(12, 2), nullable=False)
    total_with_vat = Column(DECIMAL(12, 2), nullable=False)
    
    calculated_selling_price = Column(DECIMAL(12, 2), nullable=True)
    calculated_selling_price_with_vat = Column(DECIMAL(12, 2), nullable=True)
    
    current_stock = Column(DECIMAL(12, 2), default=0)
    sold_quantity = Column(DECIMAL(12, 2), default=0)
    sold_value = Column(DECIMAL(12, 2), default=0)
    sold_vat = Column(DECIMAL(12, 2), default=0)
    current_value = Column(DECIMAL(12, 2), default=0)
    current_vat = Column(DECIMAL(12, 2), default=0)
    
    supplier_name = Column(String(255), nullable=True)
    invoice_number = Column(String(100), nullable=True)
    purchase_date = Column(DateTime(timezone=True), nullable=False)
    
    status = Column(String(50), default=VATStatus.PENDING.value)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Wallet payment fields
    use_wallet_payment = Column(Boolean, default=False)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=True)
    wallet_transaction_id = Column(Integer, ForeignKey("wallet_transactions.id"), nullable=True)
    
    # Relationships
    branch = relationship("Branch", foreign_keys=[branch_id], back_populates="vat_purchases")
    product = relationship("Product", foreign_keys=[product_id], back_populates="vat_purchases")
    creator = relationship("User", foreign_keys=[created_by], back_populates="vat_purchases_created")
    purchase_order = relationship("PurchaseOrder", foreign_keys=[purchase_order_id], back_populates="vat_purchases")
    vat_sales = relationship("VATSale", back_populates="vat_purchase", cascade="all, delete-orphan")
    wallet = relationship("Wallet", foreign_keys=[wallet_id])
    wallet_transaction = relationship("WalletTransaction", foreign_keys=[wallet_transaction_id])
    
    __table_args__ = (
        Index('idx_vat_purchase_branch', 'branch_id'),
        Index('idx_vat_purchase_product', 'product_id'),
        Index('idx_vat_purchase_group', 'product_group'),
        Index('idx_vat_purchase_date', 'purchase_date'),
        Index('idx_vat_purchase_status', 'status'),
    )


class VATSale(Base):
    __tablename__ = "vat_sales"
    
    id = Column(Integer, primary_key=True, index=True)
    vat_sale_number = Column(String(50), unique=True, nullable=False, index=True)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True)
    sale_item_id = Column(Integer, ForeignKey("sale_items.id"), nullable=True)
    vat_purchase_id = Column(Integer, ForeignKey("vat_purchases.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    product_name = Column(String(255), nullable=True)
    product_group = Column(String(100), nullable=True)
    sku = Column(String(100), nullable=True)
    
    quantity = Column(DECIMAL(12, 2), nullable=False)
    unit_cost = Column(DECIMAL(12, 2), nullable=False)
    selling_price = Column(DECIMAL(12, 2), nullable=False)
    selling_price_with_vat = Column(DECIMAL(12, 2), nullable=False)
    
    vat_rate = Column(DECIMAL(5, 2), default=15.00)
    vat_amount = Column(DECIMAL(12, 2), nullable=False)
    total_amount = Column(DECIMAL(12, 2), nullable=False)
    total_amount_with_vat = Column(DECIMAL(12, 2), nullable=False)
    
    cost_of_goods_sold = Column(DECIMAL(12, 2), nullable=False)
    profit = Column(DECIMAL(12, 2), nullable=False)
    profit_margin = Column(DECIMAL(5, 2), nullable=False)
    
    customer_name = Column(String(255), nullable=True)
    invoice_number = Column(String(50), nullable=True)
    sale_date = Column(DateTime(timezone=True), nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Wallet transaction tracking
    wallet_transaction_id = Column(Integer, ForeignKey("wallet_transactions.id"), nullable=True)
    
    # Relationships
    sale = relationship("Sale", foreign_keys=[sale_id], back_populates="vat_sales")
    sale_item = relationship("SaleItem", foreign_keys=[sale_item_id], back_populates="vat_sale")
    vat_purchase = relationship("VATPurchase", foreign_keys=[vat_purchase_id], back_populates="vat_sales")
    product = relationship("Product", foreign_keys=[product_id], back_populates="vat_sales")
    branch = relationship("Branch", foreign_keys=[branch_id], back_populates="vat_sales")
    creator = relationship("User", foreign_keys=[created_by], back_populates="vat_sales_created")
    wallet_transaction = relationship("WalletTransaction", foreign_keys=[wallet_transaction_id])
    
    __table_args__ = (
        Index('idx_vat_sale_branch', 'branch_id'),
        Index('idx_vat_sale_product', 'product_id'),
        Index('idx_vat_sale_group', 'product_group'),
        Index('idx_vat_sale_date', 'sale_date'),
        Index('idx_vat_purchase', 'vat_purchase_id'),
    )


class VATSummary(Base):
    __tablename__ = "vat_summaries"
    
    id = Column(Integer, primary_key=True, index=True)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    summary_month = Column(String(7), nullable=False)
    summary_year = Column(Integer, nullable=False)
    summary_month_num = Column(Integer, nullable=False)
    
    total_purchases_excl_vat = Column(DECIMAL(12, 2), default=0)
    total_purchase_vat = Column(DECIMAL(12, 2), default=0)
    total_purchases_incl_vat = Column(DECIMAL(12, 2), default=0)
    purchase_count = Column(Integer, default=0)
    purchase_by_group = Column(Text, nullable=True)
    
    total_sales_excl_vat = Column(DECIMAL(12, 2), default=0)
    total_sale_vat = Column(DECIMAL(12, 2), default=0)
    total_sales_incl_vat = Column(DECIMAL(12, 2), default=0)
    sale_count = Column(Integer, default=0)
    sale_by_group = Column(Text, nullable=True)
    
    vat_payable = Column(DECIMAL(12, 2), default=0)
    vat_receivable = Column(DECIMAL(12, 2), default=0)
    net_vat = Column(DECIMAL(12, 2), default=0)
    
    total_profit_excl_vat = Column(DECIMAL(12, 2), default=0)
    average_profit_margin = Column(DECIMAL(5, 2), default=0)
    
    status = Column(String(50), default=VATStatus.PENDING.value)
    filed_date = Column(DateTime(timezone=True), nullable=True)
    payment_date = Column(DateTime(timezone=True), nullable=True)
    payment_reference = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Relationships
    branch = relationship("Branch", foreign_keys=[branch_id], back_populates="vat_summaries")
    creator = relationship("User", foreign_keys=[created_by], back_populates="vat_summaries_created")
    
    __table_args__ = (
        UniqueConstraint('branch_id', 'summary_month', name='unique_branch_month'),
        Index('idx_vat_summary_month', 'summary_month'),
        Index('idx_vat_summary_status', 'status'),
    )


class VATRateHistory(Base):
    __tablename__ = "vat_rate_histories"
    
    id = Column(Integer, primary_key=True, index=True)
    vat_rate = Column(DECIMAL(5, 2), nullable=False)
    effective_from = Column(DateTime(timezone=True), nullable=False)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    creator = relationship("User", foreign_keys=[created_by], back_populates="vat_rates_created")
    
    __table_args__ = (
        Index('idx_vat_rate_effective', 'effective_from', 'effective_to'),
    )


# ==================== ENHANCED WALLET MODELS ====================

class Wallet(Base):
    __tablename__ = "wallets"
    
    id = Column(Integer, primary_key=True, index=True)
    wallet_number = Column(String(50), unique=True, nullable=False, index=True)
    wallet_name = Column(String(100), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    wallet_type = Column(String(50), nullable=False)  # vat, regular, petty_cash, expense, custom
    wallet_purpose = Column(String(50), default=WalletPurpose.OTHER.value)
    
    # Financial details
    balance = Column(DECIMAL(15, 2), default=0)
    currency = Column(String(3), default="ETB")
    
    # Bank account integration (optional - can be null for cash-based wallets)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=True)
    
    # Wallet settings
    is_active = Column(Boolean, default=True)
    requires_approval = Column(Boolean, default=False)  # For high-value transactions
    max_balance = Column(DECIMAL(15, 2), nullable=True)  # Optional max limit
    min_balance = Column(DECIMAL(15, 2), nullable=True)  # Optional minimum balance alert
    daily_limit = Column(DECIMAL(15, 2), nullable=True)
    transaction_limit = Column(DECIMAL(15, 2), nullable=True)
    
    # Metadata
    description = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    branch = relationship("Branch", back_populates="wallets")
    bank_account = relationship("BankAccount", back_populates="wallets")
    transactions = relationship(
        "WalletTransaction", 
        foreign_keys="WalletTransaction.wallet_id",
        back_populates="wallet", 
        cascade="all, delete-orphan"
    )
    summaries = relationship("WalletSummary", back_populates="wallet", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by], back_populates="wallets_created")
    
    __table_args__ = (
        UniqueConstraint('branch_id', 'wallet_number', name='unique_branch_wallet_number'),
        Index('idx_wallet_branch', 'branch_id'),
        Index('idx_wallet_type', 'wallet_type'),
        Index('idx_wallet_bank_account', 'bank_account_id'),
        Index('idx_wallet_active', 'is_active'),
    )


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    transaction_number = Column(String(50), unique=True, nullable=False, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=False)
    
    # Transaction details
    transaction_type = Column(String(50), nullable=False)  # deposit, withdrawal, transfer, purchase, restock, refund
    transaction_method = Column(String(50), nullable=False, default=WalletTransactionMethod.CASH.value)
    amount = Column(DECIMAL(15, 2), nullable=False)
    
    # For transfers between wallets
    from_wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=True)
    to_wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=True)
    
    # Balance tracking
    balance_before = Column(DECIMAL(15, 2), nullable=False)
    balance_after = Column(DECIMAL(15, 2), nullable=False)
    
    # Status tracking
    status = Column(String(50), default=WalletTransactionStatus.COMPLETED.value)
    approval_status = Column(String(50), default="approved")  # pending, approved, rejected
    approved_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    
    # Reference to related business transactions
    reference_type = Column(String(50), nullable=True)  # purchase_order, sale, refund, restock
    reference_id = Column(Integer, nullable=True)
    reference_number = Column(String(100), nullable=True)
    
    # Bank integration
    bank_transaction_id = Column(String(100), nullable=True)  # Reference to bank statement
    bank_reference = Column(String(100), nullable=True)
    
    # Additional details
    description = Column(Text, nullable=True)
    attachments = Column(Text, nullable=True)  # JSON array of attachment URLs
    notes = Column(Text, nullable=True)
    
    # Audit fields
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    wallet = relationship(
        "Wallet", 
        foreign_keys=[wallet_id],
        back_populates="transactions"
    )
    from_wallet = relationship(
        "Wallet", 
        foreign_keys=[from_wallet_id],
        back_populates=None
    )
    to_wallet = relationship(
        "Wallet", 
        foreign_keys=[to_wallet_id],
        back_populates=None
    )
    creator = relationship("User", foreign_keys=[created_by], back_populates="wallet_transactions_created")
    approver = relationship("User", foreign_keys=[approved_by])
    
    __table_args__ = (
        Index('idx_wallet_transaction_wallet', 'wallet_id'),
        Index('idx_wallet_transaction_type', 'transaction_type'),
        Index('idx_wallet_transaction_method', 'transaction_method'),
        Index('idx_wallet_transaction_reference', 'reference_type', 'reference_id'),
        Index('idx_wallet_transaction_created', 'created_at'),
        Index('idx_wallet_transaction_status', 'status'),
        Index('idx_wallet_transaction_bank_ref', 'bank_reference'),
    )


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id"), nullable=False)
    
    # Transaction details from bank
    transaction_date = Column(DateTime(timezone=True), nullable=False)
    transaction_type = Column(String(50), nullable=False)  # credit, debit
    amount = Column(DECIMAL(15, 2), nullable=False)
    description = Column(Text, nullable=True)
    reference = Column(String(100), nullable=True)
    
    # Bank statement reference
    statement_date = Column(Date, nullable=True)
    statement_balance = Column(DECIMAL(15, 2), nullable=True)
    
    # Reconciliation
    is_reconciled = Column(Boolean, default=False)
    reconciled_at = Column(DateTime(timezone=True), nullable=True)
    reconciled_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Link to wallet transaction
    wallet_transaction_id = Column(Integer, ForeignKey("wallet_transactions.id"), nullable=True)
    
    # Metadata
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    bank_account = relationship("BankAccount", back_populates="bank_transactions")
    wallet_transaction = relationship("WalletTransaction", foreign_keys=[wallet_transaction_id])
    reconciler = relationship("User", foreign_keys=[reconciled_by], back_populates="bank_transactions_reconciled")
    
    __table_args__ = (
        Index('idx_bank_transaction_account', 'bank_account_id'),
        Index('idx_bank_transaction_date', 'transaction_date'),
        Index('idx_bank_transaction_reconciled', 'is_reconciled'),
        Index('idx_bank_transaction_reference', 'reference'),
    )


class WalletSummary(Base):
    __tablename__ = "wallet_summaries"
    
    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=False)
    branch_id = Column(Integer, ForeignKey("branches.id"), nullable=False)
    summary_date = Column(Date, nullable=False)
    
    # Opening balances
    opening_balance = Column(DECIMAL(15, 2), default=0)
    
    # Income
    total_deposits = Column(DECIMAL(15, 2), default=0)
    total_transfers_in = Column(DECIMAL(15, 2), default=0)
    
    # Expenses
    total_withdrawals = Column(DECIMAL(15, 2), default=0)
    total_transfers_out = Column(DECIMAL(15, 2), default=0)
    total_purchases = Column(DECIMAL(15, 2), default=0)
    total_restocks = Column(DECIMAL(15, 2), default=0)
    total_refunds = Column(DECIMAL(15, 2), default=0)
    
    # Closing balance
    closing_balance = Column(DECIMAL(15, 2), default=0)
    
    # Statistics
    transaction_count = Column(Integer, default=0)
    average_transaction_amount = Column(DECIMAL(15, 2), default=0)
    highest_transaction = Column(DECIMAL(15, 2), default=0)
    lowest_transaction = Column(DECIMAL(15, 2), default=0)
    
    # Bank reconciliation
    bank_balance_at_date = Column(DECIMAL(15, 2), nullable=True)
    is_reconciled = Column(Boolean, default=False)
    reconciled_at = Column(DateTime(timezone=True), nullable=True)
    
    # Metadata
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    wallet = relationship(
        "Wallet", 
        foreign_keys=[wallet_id],
        back_populates="summaries"
    )
    branch = relationship("Branch", back_populates="wallet_summaries")
    
    __table_args__ = (
        UniqueConstraint('wallet_id', 'summary_date', name='unique_wallet_date_summary'),
        Index('idx_wallet_summary_wallet', 'wallet_id'),
        Index('idx_wallet_summary_date', 'summary_date'),
        Index('idx_wallet_summary_branch', 'branch_id'),
    )