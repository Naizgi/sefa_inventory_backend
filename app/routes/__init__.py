from .auth import router as auth_router
from .branches import router as branches_router
from .products import router as products_router
from .users import router as users_router
from .stock import router as stock_router
from .sales import router as sales_router
from .purchase_routes import router as purchase_router
from .reports import router as reports_router
from .alerts import router as alerts_router
from .dashboard import router as dashboard_router
from .loan_routes import router as loan_router
from .temp_items_routes import router as temp_items_router
from .settings_router import router as settings_router
from .vat import router as vat_router  # NEW: VAT tracking router
from .damaged_goods import router as damaged_goods_router  # Add if you have this


# Export all routers
__all__ = [
    'auth_router',
    'branches_router', 
    'products_router',
    'users_router',
    'stock_router',
    'sales_router',
    'purchase_router',
    'reports_router',
    'alerts_router',
    'dashboard_router',
    'loan_router',
    'temp_items_router',
    'settings_router',
    'vat_router',  # NEW: Export VAT router
    'damaged_goods_router',  # Optional: if you have damaged goods router
]