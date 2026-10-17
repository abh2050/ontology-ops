"""The five permitted source files, their exact headers, and field parsers."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Exact source headers, including the source spelling "lenght".
SOURCES: dict[str, tuple[str, list[str]]] = {
    "customers": (
        "olist_customers_dataset.csv",
        ["customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city",
         "customer_state"],
    ),
    "sellers": (
        "olist_sellers_dataset.csv",
        ["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"],
    ),
    "products": (
        "olist_products_dataset.csv",
        ["product_id", "product_category_name", "product_name_lenght",
         "product_description_lenght", "product_photos_qty", "product_weight_g",
         "product_length_cm", "product_height_cm", "product_width_cm"],
    ),
    "orders": (
        "olist_orders_dataset.csv",
        ["order_id", "customer_id", "order_status", "order_purchase_timestamp",
         "order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date",
         "order_estimated_delivery_date"],
    ),
    "order_items": (
        "olist_order_items_dataset.csv",
        ["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price",
         "freight_value"],
    ),
}

# Load order respects foreign keys.
LOAD_ORDER = ["customers", "sellers", "products", "orders", "order_items"]

SOURCE_URL = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"
LICENSE = "CC BY-NC-SA 4.0"

_ID = re.compile(r"^[0-9a-f]{32}$")
_STATE = re.compile(r"^[A-Z]{2}$")
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"
_INT = re.compile(r"^\d+(\.0+)?$")


class FieldError(ValueError):
    def __init__(self, reason: str, field: str):
        super().__init__(f"{reason}:{field}")
        self.reason = reason
        self.field = field


def parse_id(value: str, field: str) -> str:
    if not _ID.match(value):
        raise FieldError("BAD_ID", field)
    return value


def parse_state(value: str, field: str) -> str:
    if not _STATE.match(value):
        raise FieldError("BAD_VALUE", field)
    return value


def parse_ts(value: str, field: str, *, required: bool) -> datetime | None:
    if value == "":
        if required:
            raise FieldError("BAD_TIMESTAMP", field)
        return None
    try:
        return datetime.strptime(value, _TS_FORMAT)
    except ValueError:
        raise FieldError("BAD_TIMESTAMP", field) from None


def parse_money_centavos(value: str, field: str) -> int:
    """Decimal reais to integer centavos, rounded half up. No floating point."""
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise FieldError("BAD_MONEY", field) from None
    if not amount.is_finite():
        raise FieldError("BAD_MONEY", field)
    if amount < 0:
        raise FieldError("NEG_MONEY", field)
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def check_optional_int(value: str, field: str) -> None:
    """Validate type only; physical dimensions are never persisted."""
    if value != "" and not _INT.match(value):
        raise FieldError("BAD_VALUE", field)


def parse_line_no(value: str, field: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise FieldError("BAD_VALUE", field)
    return int(value)
