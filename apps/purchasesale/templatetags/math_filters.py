# apps/purchasesale/templatetags/math_filters.py
from django import template
from decimal import Decimal, InvalidOperation

register = template.Library()


@register.filter
def multiply(value, arg):
    """ضرب دو عدد"""
    try:
        return Decimal(str(value)) * Decimal(str(arg))
    except (ValueError, TypeError, InvalidOperation):
        return Decimal('0')


@register.filter
def subtract(value, arg):
    """تفریق"""
    try:
        return Decimal(str(value)) - Decimal(str(arg))
    except (ValueError, TypeError, InvalidOperation):
        return Decimal('0')