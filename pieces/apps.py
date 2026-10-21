from django.apps import AppConfig


class PiecesConfig(AppConfig):
    name = 'pieces'
    verbose_name = 'Pièces'

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from .corpus import bump
        from .models import Piece

        # le cache du corpus et des similarités suit toute écriture faite via l'ORM
        post_save.connect(lambda **kw: bump(), sender=Piece, weak=False, dispatch_uid='pieces-bump-save')
        post_delete.connect(lambda **kw: bump(), sender=Piece, weak=False, dispatch_uid='pieces-bump-delete')
