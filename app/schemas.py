# app/schemas.py
from enum import Enum
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from datetime import datetime, date
from typing import Optional, List, Any
from decimal import Decimal

# ==================== ENUMS ====================
class PurchaseStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    PARTIALLY_RECEIVED = "partially_received"

class LoanStatus(str, Enum):
    ACTIVE = "active"
    PARTIALLY_PAID = "partially_paid"
    SETTLED = "settled"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"

class LoanPaymentMethod(str, Enum):
    CASH = "cash"
    TICKET = "ticket"
    COUPON = "coupon"
    MIXED = "mixed"
    WALLET = "wallet"

class SaleStatus(str, Enum):
    COMPLETED = "completed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    CANCELLED = "cancelled"

class PaymentMethod(str, Enum):
    CASH = "cash"
    TRANSFER = "transfer"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    MOBILE_MONEY = "mobile_money"
    COUPON = "coupon"
    MIXED = "mixed"
    ORIGINAL_METHOD = "original_method"

class RefundStatus(str, Enum):
    NONE = "none"
    PENDING = "pending"
    APPROVED = "approved"
    COMPLETED = "completed"
    REJECTED = "rejected"

class DiscountType(str, Enum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"

class DamagedGoodsStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSED = "processed"

# ==================== ENHANCED WALLET ENUMS ====================
class WalletType(str, Enum):
    VAT = "vat"
    REGULAR = "regular"
    PETTY_CASH = "petty_cash"
    EXPENSE = "expense"
    CUSTOM = "custom"

class WalletPurpose(str, Enum):
    VAT_OPERATIONS = "vat_operations"
    REGULAR_STOCK = "regular_stock"
    PETTY_CASH = "petty_cash"
    OPERATING_EXPENSES = "operating_expenses"
    MARKETING = "marketing"
    MAINTENANCE = "maintenance"
    OTHER = "other"

class WalletTransactionType(str, Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    PURCHASE = "purchase"
    RESTOCK = "restock"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"
    TRANSFER = "transfer"

class WalletTransactionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"

class WalletTransactionMethod(str, Enum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    CARD = "card"
    MOBILE_MONEY = "mobile_money"
    INTERNAL_TRANSFER = "internal_transfer"

# ==================== DATE RANGE SCHEMA ====================
class DateRange(BaseModel):
    from_date: date
    to_date: date

# ==================== BRANCH SCHEMAS ====================
class BranchBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    address: Optional[str] = None
    phone: Optional[str] = Field(None, max_length=50)

class BranchCreate(BranchBase):
    pass

class BranchUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    address: Optional[str] = None
    phone: Optional[str] = Field(None, max_length=50)

class Branch(BranchBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== ENHANCED BANK ACCOUNT SCHEMAS ====================
class BankAccountBase(BaseModel):
    bank_name: str = Field(..., min_length=1, max_length=100)
    branch_name: Optional[str] = Field(None, max_length=100)
    account_number: str = Field(..., min_length=1, max_length=50)
    account_name: str = Field(..., min_length=1, max_length=255)
    account_type: str = Field(default="checking", pattern="^(checking|savings|business)$")
    iban: Optional[str] = Field(None, max_length=50)
    swift_code: Optional[str] = Field(None, max_length=20)
    currency: str = Field(default="ETB", min_length=3, max_length=3)
    is_active: bool = True
    is_primary: bool = False
    account_category: str = Field(default="regular", pattern="^(regular|vat)$")
    notes: Optional[str] = None

class BankAccountCreate(BankAccountBase):
    branch_id: int

class BankAccountUpdate(BaseModel):
    bank_name: Optional[str] = Field(None, min_length=1, max_length=100)
    branch_name: Optional[str] = Field(None, max_length=100)
    account_number: Optional[str] = Field(None, min_length=1, max_length=50)
    account_name: Optional[str] = Field(None, min_length=1, max_length=255)
    account_type: Optional[str] = Field(None, pattern="^(checking|savings|business)$")
    iban: Optional[str] = Field(None, max_length=50)
    swift_code: Optional[str] = Field(None, max_length=20)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    is_active: Optional[bool] = None
    is_primary: Optional[bool] = None
    account_category: Optional[str] = Field(None, pattern="^(regular|vat)$")
    notes: Optional[str] = None

class BankAccountResponse(BankAccountBase):
    id: int
    branch_id: int
    current_balance: float = 0
    last_reconciled_at: Optional[datetime] = None
    last_reconciled_balance: Optional[float] = None
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# ==================== PRODUCT SCHEMAS ====================
class ProductBase(BaseModel):
    sku: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None, max_length=50)
    size: Optional[str] = Field(None, max_length=50)
    pages: Optional[int] = Field(None, ge=0)
    price: float = Field(..., gt=0)
    cost: float = Field(..., gt=0)
    active: bool = True

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    sku: Optional[str] = Field(None, min_length=1, max_length=100)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    color: Optional[str] = Field(None, max_length=50)
    size: Optional[str] = Field(None, max_length=50)
    pages: Optional[int] = Field(None, ge=0)
    price: Optional[float] = Field(None, gt=0)
    cost: Optional[float] = Field(None, gt=0)
    active: Optional[bool] = None

class Product(ProductBase):
    id: int
    created_at: datetime
    stock_quantity: Optional[float] = 0
    reorder_level: Optional[float] = 0
    
    class Config:
        from_attributes = True


# ==================== USER SCHEMAS ====================
class UserBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    role: str = Field(..., pattern="^(admin|salesman|privileged_sales)$")
    branch_id: Optional[int] = None
    active: bool = True

class UserCreate(UserBase):
    password: str = Field(..., min_length=6)

class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    role: Optional[str] = Field(None, pattern="^(admin|salesman|privileged_sales)$")
    branch_id: Optional[int] = None
    active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=6)
    
class User(UserBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== STOCK SCHEMAS ====================
class StockBase(BaseModel):
    branch_id: int
    product_id: Optional[int] = None
    quantity: float = Field(0, ge=0)
    quantity_with_vat: float = Field(0, ge=0, description="Stock quantity purchased with VAT")
    quantity_without_vat: float = Field(0, ge=0, description="Stock quantity purchased without VAT")
    reorder_level: float = Field(0, ge=0)

class StockCreate(StockBase):
    pass

class StockUpdate(BaseModel):
    quantity: Optional[float] = Field(None, ge=0)
    quantity_with_vat: Optional[float] = Field(None, ge=0)
    quantity_without_vat: Optional[float] = Field(None, ge=0)
    reorder_level: Optional[float] = Field(None, ge=0)

class Stock(StockBase):
    id: int
    
    class Config:
        from_attributes = True

class StockResponse(BaseModel):
    product_id: Optional[int] = None
    product_name: str
    product_sku: str
    quantity: float
    stock_with_vat: float = Field(0, description="Stock quantity with VAT")
    stock_without_vat: float = Field(0, description="Stock quantity without VAT")
    reorder_level: float
    status: str


# ==================== STOCK MOVEMENT SCHEMAS ====================
class StockMovementBase(BaseModel):
    branch_id: int
    product_id: Optional[int] = None
    change_qty: float
    movement_type: str
    with_vat: bool = Field(True, description="Whether this movement was with VAT")
    notes: Optional[str] = None

class StockMovementCreate(StockMovementBase):
    pass

class StockMovementResponse(StockMovementBase):
    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    reference_id: Optional[int] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


# ==================== SALE SCHEMAS ====================
class SaleItemCreate(BaseModel):
    product_id: int
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., gt=0)
    discount_amount: float = Field(default=0, ge=0)

class SaleItemUpdate(BaseModel):
    quantity: Optional[float] = Field(None, gt=0)
    discount_amount: Optional[float] = Field(None, ge=0)

class SaleItemResponse(BaseModel):
    id: int
    sale_id: int
    product_id: int
    product_name: Optional[str] = None
    product_sku: Optional[str] = None
    quantity: float
    unit_price: float
    discount_amount: float
    line_total: float
    
    class Config:
        from_attributes = True

class SaleCreate(BaseModel):
    branch_id: Optional[int] = None
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[EmailStr] = None
    items: List[SaleItemCreate] = Field(..., min_length=1)
    tax_rate: float = Field(default=15, ge=0, le=100)
    discount_amount: float = Field(default=0, ge=0)
    discount_type: DiscountType = Field(default=DiscountType.PERCENTAGE)
    
    # Additional costs for sales
    shipping_cost: float = Field(default=0, ge=0, description="Shipping cost for the sale")
    labour_cost: float = Field(default=0, ge=0, description="Labour cost for the sale")
    other_cost: float = Field(default=0, ge=0, description="Other miscellaneous costs")
    other_cost_description: Optional[str] = Field(None, description="Description of other costs")
    
    payment_method: PaymentMethod = Field(default=PaymentMethod.CASH)
    bank_account_id: Optional[int] = None
    transaction_reference: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None

class SaleUpdate(BaseModel):
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    customer_email: Optional[EmailStr] = None
    notes: Optional[str] = None
    shipping_cost: Optional[float] = Field(None, ge=0)
    labour_cost: Optional[float] = Field(None, ge=0)
    other_cost: Optional[float] = Field(None, ge=0)
    other_cost_description: Optional[str] = None

class SaleResponse(BaseModel):
    id: int
    invoice_number: str
    branch_id: int
    branch_name: Optional[str] = None
    user_id: int
    user_name: Optional[str] = None
    customer_name: Optional[str]
    customer_phone: Optional[str]
    customer_email: Optional[str]
    
    subtotal: float
    tax_amount: float
    tax_rate: float
    discount_amount: float
    discount_type: DiscountType
    
    # Additional costs
    shipping_cost: float = 0
    labour_cost: float = 0
    other_cost: float = 0
    other_cost_description: Optional[str] = None
    
    total_amount: float
    
    payment_method: PaymentMethod
    bank_account_id: Optional[int]
    bank_account_details: Optional[BankAccountResponse] = None
    transaction_reference: Optional[str]
    
    status: SaleStatus
    refund_amount: float
    refund_status: RefundStatus
    
    created_at: datetime
    updated_at: Optional[datetime]
    notes: Optional[str]
    items: List[SaleItemResponse] = []
    
    class Config:
        from_attributes = True


# ==================== REFUND SCHEMAS ====================
class RefundItemCreate(BaseModel):
    sale_item_id: int
    quantity: float = Field(..., gt=0)
    reason: Optional[str] = None

class RefundCreate(BaseModel):
    original_sale_id: int
    refund_reason: str = Field(..., min_length=1)
    refund_method: PaymentMethod = Field(default=PaymentMethod.ORIGINAL_METHOD)
    bank_account_id: Optional[int] = None
    transaction_reference: Optional[str] = Field(None, max_length=100)
    items: List[RefundItemCreate] = Field(..., min_length=1)
    notes: Optional[str] = None

class RefundItemResponse(BaseModel):
    id: int
    sale_item_id: int
    product_id: int
    product_name: Optional[str] = None
    quantity: float
    unit_price: float
    refund_amount: float
    reason: Optional[str]
    
    class Config:
        from_attributes = True

class RefundResponse(BaseModel):
    id: int
    refund_number: str
    original_sale_id: int
    original_invoice_number: Optional[str] = None
    branch_id: int
    branch_name: Optional[str] = None
    user_id: int
    user_name: Optional[str] = None
    customer_name: Optional[str]
    
    refund_amount: float
    refund_reason: str
    refund_method: PaymentMethod
    
    bank_account_id: Optional[int]
    bank_account_details: Optional[BankAccountResponse] = None
    transaction_reference: Optional[str]
    
    status: str
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    
    created_at: datetime
    completed_at: Optional[datetime]
    notes: Optional[str]
    items: List[RefundItemResponse] = []
    
    class Config:
        from_attributes = True

class RefundApprove(BaseModel):
    approved: bool = True
    notes: Optional[str] = None


# ==================== PURCHASE SCHEMAS ====================
class PurchaseItemCreate(BaseModel):
    product_id: int
    quantity: float = Field(..., gt=0)
    unit_cost: float = Field(..., gt=0)

class PurchaseItem(BaseModel):
    id: int
    purchase_id: int
    product_id: int
    quantity: float
    unit_cost: float
    
    class Config:
        from_attributes = True

class PurchaseCreate(BaseModel):
    branch_id: int
    supplier_name: Optional[str] = None
    subtotal: float = Field(default=0, ge=0)
    vat_amount: float = Field(default=0, ge=0)
    
    # Additional costs for purchases
    shipping_cost: float = Field(default=0, ge=0, description="Shipping cost for the purchase")
    labour_cost: float = Field(default=0, ge=0, description="Labour cost for the purchase")
    labour_cost_description: Optional[str] = Field(None, description="Description of labour work")
    other_cost: float = Field(default=0, ge=0, description="Other miscellaneous costs")
    other_cost_description: Optional[str] = Field(None, description="Description of other costs")
    
    items: List[PurchaseItemCreate] = Field(..., min_length=1)

class Purchase(BaseModel):
    id: int
    branch_id: int
    supplier_name: Optional[str]
    subtotal: float = Field(default=0)
    vat_amount: float = Field(default=0)
    
    # Additional costs
    shipping_cost: float = Field(default=0)
    labour_cost: float = Field(default=0)
    labour_cost_description: Optional[str] = None
    other_cost: float = Field(default=0)
    other_cost_description: Optional[str] = None
    
    total_amount: float
    created_at: datetime
    items: List[PurchaseItem] = []
    
    class Config:
        from_attributes = True


# ==================== PURCHASE ORDER SCHEMAS ====================
class PurchaseOrderItemBase(BaseModel):
    product_id: int
    quantity_ordered: Decimal = Field(gt=0)
    unit_cost: Decimal = Field(gt=0)
    notes: Optional[str] = None

class PurchaseOrderItemCreate(PurchaseOrderItemBase):
    pass

class PurchaseOrderItemResponse(PurchaseOrderItemBase):
    id: int
    quantity_received: Decimal
    total_cost: Decimal
    received_at: Optional[datetime] = None
    product_name: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class PurchaseOrderBase(BaseModel):
    supplier: str
    expected_delivery_date: Optional[date] = None
    vat_rate: Optional[float] = Field(default=None, ge=0, le=100)
    tax_amount: Decimal = Field(default=0, ge=0)
    
    # Additional costs for purchase orders
    shipping_cost: Decimal = Field(default=0, ge=0, description="Shipping cost")
    labour_cost: Decimal = Field(default=0, ge=0, description="Labour cost")
    labour_cost_description: Optional[str] = Field(None, description="Description of labour work")
    other_cost: Decimal = Field(default=0, ge=0, description="Other miscellaneous costs")
    other_cost_description: Optional[str] = Field(None, description="Description of other costs")
    
    notes: Optional[str] = None
    
    bank_account_id: Optional[int] = None
    payment_reference: Optional[str] = None
    payment_date: Optional[date] = None

class PurchaseOrderCreate(PurchaseOrderBase):
    items: List[PurchaseOrderItemCreate]
    use_wallet_payment: bool = False
    wallet_id: Optional[int] = None

class PurchaseOrderUpdate(BaseModel):
    status: Optional[PurchaseStatus] = None
    actual_delivery_date: Optional[date] = None
    notes: Optional[str] = None
    bank_account_id: Optional[int] = None
    payment_reference: Optional[str] = None
    payment_date: Optional[date] = None
    
    # Allow updating costs
    shipping_cost: Optional[Decimal] = Field(None, ge=0)
    labour_cost: Optional[Decimal] = Field(None, ge=0)
    labour_cost_description: Optional[str] = None
    other_cost: Optional[Decimal] = Field(None, ge=0)
    other_cost_description: Optional[str] = None

class PurchaseOrderResponse(PurchaseOrderBase):
    id: int
    order_number: str
    branch_id: int
    order_date: datetime
    actual_delivery_date: Optional[datetime] = None
    status: PurchaseStatus
    subtotal: Decimal
    vat_rate: Decimal = Field(default=0)
    vat_amount: Decimal = Field(default=0)
    total_amount: Decimal
    items: List[PurchaseOrderItemResponse]
    created_by: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    bank_account_id: Optional[int] = None
    bank_account_name: Optional[str] = None
    bank_name: Optional[str] = None
    payment_reference: Optional[str] = None
    payment_date: Optional[datetime] = None
    
    use_wallet_payment: bool = False
    wallet_id: Optional[int] = None
    wallet_name: Optional[str] = None
    wallet_transaction_id: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)

class ReceivePurchaseItem(BaseModel):
    product_id: int
    quantity_received: Decimal = Field(gt=0)

class ReceivePurchaseOrder(BaseModel):
    items: List[ReceivePurchaseItem]
    actual_delivery_date: date


# ==================== LOAN SCHEMAS ====================
class LoanItemBase(BaseModel):
    product_id: int
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(gt=0)

class LoanItemCreate(LoanItemBase):
    pass

class LoanItemResponse(LoanItemBase):
    id: int
    line_total: Decimal
    product_name: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class LoanBase(BaseModel):
    customer_name: str = Field(min_length=2, max_length=255)
    customer_phone: Optional[str] = None
    customer_email: Optional[EmailStr] = None
    due_date: date
    interest_rate: Decimal = Field(default=0, ge=0, le=100)
    notes: Optional[str] = None

class LoanCreate(LoanBase):
    items: List[LoanItemCreate]

class LoanUpdate(BaseModel):
    due_date: Optional[date] = None
    interest_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    status: Optional[LoanStatus] = None
    notes: Optional[str] = None

class LoanPaymentBase(BaseModel):
    amount: Decimal = Field(gt=0)
    payment_method: LoanPaymentMethod
    reference_number: Optional[str] = None
    notes: Optional[str] = None
    bank_account_id: Optional[int] = None

class LoanPaymentCreate(LoanPaymentBase):
    sale_id: Optional[int] = None

class LoanPaymentResponse(LoanPaymentBase):
    id: int
    payment_number: str
    payment_date: datetime
    recorded_by: str
    sale_id: Optional[int] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class LoanResponse(LoanBase):
    id: int
    loan_number: str
    branch_id: int
    loan_date: datetime
    total_amount: Decimal
    paid_amount: Decimal
    remaining_amount: Decimal
    interest_amount: Decimal
    status: LoanStatus
    items: List[LoanItemResponse]
    payments: List[LoanPaymentResponse] = []
    created_by: str
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)

class LoanSettleRequest(BaseModel):
    amount: Decimal = Field(gt=0)
    payment_method: LoanPaymentMethod
    reference_number: Optional[str] = None
    notes: Optional[str] = None
    bank_account_id: Optional[int] = None

class LoanSummaryResponse(BaseModel):
    summary_date: date
    branch_id: int
    total_loans_issued: int
    total_loan_amount: Decimal
    total_repayments: Decimal
    total_outstanding: Decimal
    active_loans_count: int
    overdue_loans_count: int
    
    model_config = ConfigDict(from_attributes=True)

class LoanReport(BaseModel):
    date_range: DateRange
    total_loans: int
    total_loan_value: Decimal
    total_repayments: Decimal
    total_outstanding: Decimal
    average_loan_size: Decimal
    repayment_rate: float
    loans_by_status: dict
    daily_breakdown: List[dict]


# ==================== COMBINED SALES REPORT SCHEMA ====================
class CombinedSalesReport(BaseModel):
    date_range: DateRange
    total_sales: float
    total_cash_sales: float
    total_transfer_sales: float
    total_coupons_used: int
    total_tickets_used: int
    total_orders: int
    daily_breakdown: List[dict]
    top_coupon_items: List[dict] = []
    top_ticket_items: List[dict] = []
    ticket_summary: dict
    loan_summary: Optional[LoanReport] = None
    loan_repayments: float = 0
    payment_method_breakdown: dict = {}


# ==================== ALERT SCHEMAS ====================
class Alert(BaseModel):
    branch_id: int
    product_id: int
    message: str

class AlertResponse(BaseModel):
    id: int
    branch_id: int
    product_id: int
    product_name: Optional[str] = None
    branch_name: Optional[str] = None
    message: str
    created_at: datetime
    resolved: bool
    resolved_at: Optional[datetime]
    
    class Config:
        from_attributes = True


# ==================== AUTH SCHEMAS ====================
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None
    user_id: Optional[int] = None
    branch_id: Optional[int] = None

class LoginRequest(BaseModel):
    username: str
    password: str


# ==================== TEMP ITEM SCHEMAS ====================
class TempItemStatus(str, Enum):
    PENDING = "pending"
    RECEIVED = "received"
    CANCELLED = "cancelled"

class TempItemBase(BaseModel):
    item_name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    quantity: int = Field(default=1, ge=1)
    unit_price: Optional[float] = Field(None, gt=0)
    customer_name: Optional[str] = Field(None, max_length=255)
    customer_phone: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None

class TempItemCreate(TempItemBase):
    pass

class TempItemUpdate(BaseModel):
    status: Optional[TempItemStatus] = None
    notes: Optional[str] = None

class TempItemResponse(TempItemBase):
    id: int
    item_number: str
    status: TempItemStatus
    registered_by: str
    registered_at: datetime
    received_by: Optional[str] = None
    received_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# ==================== DAMAGED GOODS SCHEMAS ====================
class DamagedGoodsBase(BaseModel):
    product_id: int
    quantity: float = Field(..., gt=0)
    reason: str = Field(..., min_length=3)
    notes: Optional[str] = None

class DamagedGoodsCreate(DamagedGoodsBase):
    pass

class DamagedGoodsUpdate(BaseModel):
    status: Optional[DamagedGoodsStatus] = None
    notes: Optional[str] = None

class DamagedGoodsApprove(BaseModel):
    approved: bool = True
    notes: Optional[str] = None

class DamagedGoodsResponse(DamagedGoodsBase):
    id: int
    report_number: str
    branch_id: int
    branch_name: Optional[str] = None
    product_name: Optional[str] = None
    product_sku: Optional[str] = None
    quantity: float
    reason: str
    notes: Optional[str] = None
    reported_by: str
    reported_at: datetime
    status: DamagedGoodsStatus
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    processed_by: Optional[str] = None
    processed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# ==================== SETTINGS SCHEMAS ====================
class SystemSettingBase(BaseModel):
    category: str = Field(..., min_length=1, max_length=50)
    key: str = Field(..., min_length=1, max_length=100)
    value: Any

class SystemSettingCreate(SystemSettingBase):
    pass

class SystemSettingUpdate(BaseModel):
    value: Any

class SystemSettingResponse(SystemSettingBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class BackupRecordBase(BaseModel):
    name: str
    file_path: str
    size_mb: float = 0

class BackupRecordResponse(BackupRecordBase):
    id: int
    created_by: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class SystemLogBase(BaseModel):
    log_type: str
    message: str
    details: Optional[str] = None
    ip_address: Optional[str] = None

class SystemLogResponse(SystemLogBase):
    id: int
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# Settings update request models
class GeneralSettingsUpdate(BaseModel):
    system_name: str = Field(default="Inventory System")
    timezone: str = Field(default="Africa/Addis_Ababa")
    date_format: str = Field(default="YYYY-MM-DD")
    currency: str = Field(default="ETB")
    language: str = Field(default="en")
    default_tax_rate: float = Field(default=15, ge=0, le=100)

class CouponSettingsUpdate(BaseModel):
    auto_reset: bool = True
    reset_time: str = Field(default="00:00")
    low_stock_alert: bool = True
    alert_threshold: int = Field(default=20, ge=0, le=100)
    default_coupon: int = Field(default=100, ge=0)

class NotificationSettingsUpdate(BaseModel):
    low_stock_email: bool = True
    daily_report_email: bool = True
    sms_alerts: bool = False
    email_recipients: List[str] = []

class BackupSettingsUpdate(BaseModel):
    auto_backup: bool = True
    frequency: str = Field(default="daily", pattern="^(daily|weekly|monthly)$")
    backup_time: str = Field(default="23:00")
    location: str = Field(default="local", pattern="^(local|cloud)$")
    retention_days: int = Field(default=30, ge=1, le=365)


class SystemInfoResponse(BaseModel):
    version: str
    build_date: str
    database: str
    server_status: str
    total_users: int
    total_products: int
    total_branches: int
    recent_sales: int
    uptime_days: int
    last_backup: Optional[str] = None
    cache_size_mb: float


# ==================== USER PROFILE SCHEMA ====================
class UserProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)


# ==================== VAT TRACKING SCHEMAS ====================
class VATStatus(str, Enum):
    PENDING = "pending"
    FILED = "filed"
    PAID = "paid"
    CANCELLED = "cancelled"


class VATPurchaseBase(BaseModel):
    product_id: Optional[int] = None
    sku: Optional[str] = Field(None, max_length=100)
    quantity: float = Field(..., gt=0)
    unit_cost: float = Field(..., gt=0)
    vat_rate: float = Field(default=15.0, ge=0, le=100)
    supplier_name: Optional[str] = Field(None, max_length=255)
    invoice_number: Optional[str] = Field(None, max_length=100)
    purchase_date: datetime
    product_group: Optional[str] = Field(None, max_length=100)
    product_name: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class VATPurchaseCreate(VATPurchaseBase):
    purchase_order_id: Optional[int] = None
    use_wallet_payment: bool = False
    wallet_id: Optional[int] = None
    bank_account_id: Optional[int] = None
    payment_reference: Optional[str] = None


class VATPurchaseUpdate(BaseModel):
    status: Optional[VATStatus] = None
    notes: Optional[str] = None
    current_stock: Optional[float] = Field(None, ge=0)
    sold_quantity: Optional[float] = Field(None, ge=0)
    sold_value: Optional[float] = Field(None, ge=0)
    sold_vat: Optional[float] = Field(None, ge=0)


class VATPurchaseResponse(VATPurchaseBase):
    id: int
    vat_number: str
    branch_id: int
    branch_name: Optional[str] = None
    product_name: Optional[str] = None
    sku: Optional[str] = None
    total_cost: float
    vat_amount: float
    total_with_vat: float
    calculated_selling_price: Optional[float] = None
    calculated_selling_price_with_vat: Optional[float] = None
    current_stock: float
    sold_quantity: float
    sold_value: float
    sold_vat: float
    current_value: float
    current_vat: float
    status: VATStatus
    created_at: datetime
    updated_at: Optional[datetime] = None
    created_by: int
    created_by_name: Optional[str] = None
    
    # Payment fields
    use_wallet_payment: bool = False
    wallet_id: Optional[int] = None
    wallet_name: Optional[str] = None
    wallet_transaction_id: Optional[int] = None
    bank_account_id: Optional[int] = None
    payment_reference: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class VATPurchaseStockResponse(BaseModel):
    id: int
    vat_number: str
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    product_group: Optional[str]
    sku: Optional[str] = None
    current_stock: float
    unit_cost: float
    current_value: float
    purchase_date: datetime
    supplier_name: Optional[str]
    
    model_config = ConfigDict(from_attributes=True)


class VATSaleBase(BaseModel):
    sale_id: Optional[int] = None
    sale_item_id: Optional[int] = None
    vat_purchase_id: int
    quantity: float = Field(..., gt=0)
    selling_price: float = Field(..., gt=0)
    customer_name: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None


class VATSaleCreate(VATSaleBase):
    bank_account_id: Optional[int] = None
    payment_method: Optional[str] = "cash"


class VATSaleResponse(VATSaleBase):
    id: int
    vat_sale_number: str
    branch_id: int
    branch_name: Optional[str] = None
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    product_group: Optional[str] = None
    sku: Optional[str] = None
    unit_cost: float
    selling_price_with_vat: float
    vat_rate: float
    vat_amount: float
    total_amount: float
    total_amount_with_vat: float
    cost_of_goods_sold: float
    profit: float
    profit_margin: float
    invoice_number: Optional[str] = None
    sale_date: datetime
    created_at: datetime
    created_by: int
    created_by_name: Optional[str] = None
    wallet_transaction_id: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)


class VATSummaryBase(BaseModel):
    summary_month: str
    notes: Optional[str] = None


class VATSummaryCreate(VATSummaryBase):
    branch_id: int
    summary_year: int
    summary_month_num: int


class VATSummaryUpdate(BaseModel):
    status: Optional[VATStatus] = None
    filed_date: Optional[datetime] = None
    payment_date: Optional[datetime] = None
    payment_reference: Optional[str] = None
    notes: Optional[str] = None


class VATSummaryResponse(VATSummaryBase):
    id: int
    branch_id: int
    branch_name: Optional[str] = None
    summary_year: int
    summary_month_num: int
    
    total_purchases_excl_vat: float
    total_purchase_vat: float    
    total_purchases_incl_vat: float
    purchase_count: int
    purchase_by_group: Optional[dict] = None
    
    total_sales_excl_vat: float
    total_sale_vat: float
    total_sales_incl_vat: float
    sale_count: int
    sale_by_group: Optional[dict] = None
    
    vat_payable: float
    vat_receivable: float
    net_vat: float
    
    total_profit_excl_vat: float
    average_profit_margin: float
    
    status: VATStatus
    filed_date: Optional[datetime] = None
    payment_date: Optional[datetime] = None
    payment_reference: Optional[str] = None
    
    created_at: datetime
    updated_at: Optional[datetime] = None
    created_by: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)


class VATRateHistoryBase(BaseModel):
    vat_rate: float = Field(..., ge=0, le=100)
    effective_from: datetime
    effective_to: Optional[datetime] = None
    notes: Optional[str] = None


class VATRateHistoryCreate(VATRateHistoryBase):
    pass


class VATRateHistoryResponse(VATRateHistoryBase):
    id: int
    created_by: int
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ==================== VAT REPORT SCHEMAS ====================
class VATPeriodReport(BaseModel):
    period_start: date
    period_end: date
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None
    
    total_purchases: float
    total_purchase_vat: float
    purchases_by_group: dict
    
    total_sales: float
    total_sale_vat: float
    sales_by_group: dict
    
    vat_payable: float
    vat_receivable: float
    net_vat_due: float
    
    gross_profit: float
    profit_margin: float
    
    purchase_transactions: List[VATPurchaseResponse] = []
    sale_transactions: List[VATSaleResponse] = []


class VATProductGroupReport(BaseModel):
    product_group: str
    total_purchases_excl_vat: float
    total_purchase_vat: float
    total_sales_excl_vat: float
    total_sale_vat: float
    vat_contribution: float
    profit: float
    profit_margin: float
    quantity_purchased: float
    quantity_sold: float


class VATDashboardSummary(BaseModel):
    current_month_summary: Optional[VATSummaryResponse] = None
    previous_month_summary: Optional[VATSummaryResponse] = None
    year_to_date_purchases: float
    year_to_date_sales: float
    year_to_date_vat_payable: float
    pending_vat_returns: int
    current_vat_rate: float
    vat_rate_history: List[VATRateHistoryResponse] = []
    top_product_groups_by_vat: List[VATProductGroupReport] = []


# ==================== ENHANCED WALLET SCHEMAS ====================
class WalletBase(BaseModel):
    wallet_name: str = Field(..., min_length=1, max_length=100)
    wallet_type: WalletType
    wallet_purpose: WalletPurpose = Field(default=WalletPurpose.OTHER)
    currency: str = Field(default="ETB", min_length=3, max_length=3)
    description: Optional[str] = None

class WalletCreate(WalletBase):
    branch_id: int
    bank_account_id: Optional[int] = None
    initial_balance: float = Field(default=0, ge=0)
    requires_approval: bool = False
    max_balance: Optional[float] = Field(None, ge=0)
    min_balance: Optional[float] = Field(None, ge=0)
    daily_limit: Optional[float] = Field(None, ge=0)
    transaction_limit: Optional[float] = Field(None, ge=0)

class WalletUpdate(BaseModel):
    wallet_name: Optional[str] = Field(None, min_length=1, max_length=100)
    wallet_purpose: Optional[WalletPurpose] = None
    is_active: Optional[bool] = None
    bank_account_id: Optional[int] = None
    description: Optional[str] = None
    requires_approval: Optional[bool] = None
    max_balance: Optional[float] = Field(None, ge=0)
    min_balance: Optional[float] = Field(None, ge=0)
    daily_limit: Optional[float] = Field(None, ge=0)
    transaction_limit: Optional[float] = Field(None, ge=0)

class WalletResponse(WalletBase):
    id: int
    wallet_number: str
    branch_id: int
    branch_name: Optional[str] = None
    bank_account_id: Optional[int] = None
    bank_account_details: Optional[BankAccountResponse] = None
    balance: float
    is_active: bool
    requires_approval: bool
    max_balance: Optional[float] = None
    min_balance: Optional[float] = None
    daily_limit: Optional[float] = None
    transaction_limit: Optional[float] = None
    created_by: int
    created_by_name: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class WalletTransactionBase(BaseModel):
    amount: float = Field(..., gt=0)
    transaction_method: WalletTransactionMethod = Field(default=WalletTransactionMethod.CASH)
    description: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    reference_number: Optional[str] = None
    bank_reference: Optional[str] = None
    notes: Optional[str] = None

class WalletDeposit(WalletTransactionBase):
    wallet_id: int
    bank_account_id: Optional[int] = None

class WalletWithdrawal(WalletTransactionBase):
    wallet_id: int
    bank_account_id: Optional[int] = None

class WalletTransfer(BaseModel):
    from_wallet_id: int
    to_wallet_id: int
    amount: float = Field(..., gt=0)
    transaction_method: WalletTransactionMethod = Field(default=WalletTransactionMethod.INTERNAL_TRANSFER)
    description: Optional[str] = None
    notes: Optional[str] = None


class WalletTransactionResponse(WalletTransactionBase):
    id: int
    transaction_number: str
    wallet_id: int
    wallet_name: Optional[str] = None
    transaction_type: str
    amount: float
    balance_before: float
    balance_after: float
    status: str
    approval_status: str
    from_wallet_id: Optional[int] = None
    to_wallet_id: Optional[int] = None
    created_by: Optional[str] = None
    created_at: datetime
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class BankTransactionBase(BaseModel):
    transaction_date: datetime
    transaction_type: str = Field(..., pattern="^(credit|debit)$")
    amount: float = Field(..., gt=0)
    description: Optional[str] = None
    reference: Optional[str] = None
    statement_date: Optional[date] = None
    statement_balance: Optional[float] = None
    notes: Optional[str] = None

class BankTransactionCreate(BankTransactionBase):
    bank_account_id: int

class BankTransactionReconcile(BaseModel):
    wallet_transaction_id: int
    notes: Optional[str] = None

class BankTransactionResponse(BankTransactionBase):
    id: int
    bank_account_id: int
    is_reconciled: bool
    reconciled_at: Optional[datetime] = None
    reconciled_by: Optional[str] = None
    wallet_transaction_id: Optional[int] = None
    wallet_transaction_number: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class WalletBalanceResponse(BaseModel):
    wallet_id: int
    wallet_name: str
    wallet_type: str
    balance: float
    currency: str
    bank_account_name: Optional[str] = None
    last_transaction_at: Optional[datetime] = None


class BranchWalletSummaryResponse(BaseModel):
    branch_id: int
    branch_name: str
    wallets: List[WalletBalanceResponse]
    total_balance: float


class WalletSummaryResponse(BaseModel):
    id: int
    wallet_id: int
    wallet_name: Optional[str] = None
    branch_id: int
    branch_name: Optional[str] = None
    summary_date: date
    
    opening_balance: float
    
    total_deposits: float
    total_transfers_in: float
    total_income: float
    
    total_withdrawals: float
    total_transfers_out: float
    total_purchases: float
    total_restocks: float
    total_refunds: float
    total_expenses: float
    
    closing_balance: float
    
    transaction_count: int
    average_transaction_amount: float
    highest_transaction: float
    lowest_transaction: float
    
    bank_balance_at_date: Optional[float] = None
    is_reconciled: bool
    reconciled_at: Optional[datetime] = None
    
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class WalletPerformanceReport(BaseModel):
    period_start: date
    period_end: date
    wallet_id: Optional[int] = None
    wallet_name: Optional[str] = None
    branch_id: Optional[int] = None
    branch_name: Optional[str] = None
    
    opening_balance: float
    closing_balance: float
    net_change: float
    
    total_deposits: float
    total_withdrawals: float
    total_transfers_in: float
    total_transfers_out: float
    total_purchases: float
    total_restocks: float
    total_refunds: float
    
    transaction_count: int
    average_transaction_size: float
    largest_deposit: float
    largest_withdrawal: float
    
    daily_balances: List[dict] = []
    transaction_history: List[WalletTransactionResponse] = []


# ==================== VAT CALCULATION HELPERS ====================
def calculate_vat_amount(amount: float, vat_rate: float = 15.0) -> dict:
    vat_amount = amount * (vat_rate / 100)
    total_with_vat = amount + vat_amount
    return {
        "excl_vat": round(amount, 2),
        "vat_amount": round(vat_amount, 2),
        "incl_vat": round(total_with_vat, 2),
        "vat_rate": vat_rate
    }


def calculate_selling_price(unit_cost: float, markup_percentage: float = 15.0, vat_rate: float = 15.0) -> dict:
    if markup_percentage <= 0 or markup_percentage >= 100:
        markup_percentage = 15.0
    
    selling_price_excl_vat = unit_cost / (1 - (markup_percentage / 100))
    
    vat_amount = selling_price_excl_vat * (vat_rate / 100)
    selling_price_incl_vat = selling_price_excl_vat + vat_amount
    
    return {
        "unit_cost": round(unit_cost, 2),
        "markup_percentage": markup_percentage,
        "selling_price_excl_vat": round(selling_price_excl_vat, 2),
        "vat_rate": vat_rate,
        "vat_amount": round(vat_amount, 2),
        "selling_price_incl_vat": round(selling_price_incl_vat, 2),
        "profit_per_unit": round(selling_price_excl_vat - unit_cost, 2),
        "profit_margin": round(((selling_price_excl_vat - unit_cost) / selling_price_excl_vat) * 100, 2)
    }


def calculate_cogs_and_profit(quantity: float, unit_cost: float, selling_price_excl_vat: float) -> dict:
    cogs = quantity * unit_cost
    total_revenue = quantity * selling_price_excl_vat
    profit = total_revenue - cogs
    profit_margin = (profit / total_revenue * 100) if total_revenue > 0 else 0
    
    return {
        "quantity": quantity,
        "cogs": round(cogs, 2),
        "total_revenue": round(total_revenue, 2),
        "profit": round(profit, 2),
        "profit_margin": round(profit_margin, 2)
    }