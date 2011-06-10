from django.dispatch import Signal

invite = Signal(providing_args=['request','instance'])