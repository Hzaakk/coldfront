from datetime import datetime
from django import template
from django.template.defaultfilters import stringfilter


register = template.Library()


@register.filter
@stringfilter
def iso8601_to_datetime(s):
    return datetime.fromisoformat(s)