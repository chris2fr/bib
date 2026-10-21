from django.db import DatabaseError

from . import schema


def schema_upgrade(get_response):
    """Met à niveau la base au premier accès (voir schema.py) ; une base absente ou en lecture seule est laissée à la page d'installation."""
    def middleware(request):
        try:
            schema.ensure()
        except DatabaseError:
            pass
        return get_response(request)
    return middleware
