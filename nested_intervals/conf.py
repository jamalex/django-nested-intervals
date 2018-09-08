from django.conf import settings

DECIMAL_PLACES = getattr(settings, "NESTED_INTERVALS_DECIMAL_PLACES", 30)