from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Get item from dictionary by key"""
    if dictionary is None:
        return None
    try:
        return dictionary.get(key, f"محصول {key}")
    except (AttributeError, TypeError):
        return f"محصول {key}"


