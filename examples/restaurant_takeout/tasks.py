from __future__ import annotations

from examples.restaurant_takeout.schemas import MenuCheck, Order, OrderTotal


_MENU = {
    "burger": 12.00,
    "fries": 5.00,
    "salad": 9.50,
    "soda": 3.00,
}


def create_order(customer_name: str, items: list[str]) -> Order:
    return Order(
        id="order_001",
        customer_name=customer_name,
        items=items,
    )


def check_menu_items(order: Order) -> MenuCheck:
    unavailable = [item for item in order.items if item not in _MENU]
    return MenuCheck(
        status="invalid" if unavailable else "valid",
        unavailable_items=unavailable,
    )


def calculate_total(order: Order) -> OrderTotal:
    subtotal = sum(_MENU[item] for item in order.items)
    tax = round(subtotal * 0.08875, 2)
    total = round(subtotal + tax, 2)
    return OrderTotal(
        subtotal=subtotal,
        tax=tax,
        total=total,
    )
