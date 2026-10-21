import json as jsonlib
from pathlib import Path

import json2db
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = "Construit la base (FR_DB, défaut biblio.db) à partir d'un fichier JSON (défaut biblio.json)."

    def add_arguments(self, parser):
        parser.add_argument('json', nargs='?', default=str(settings.BASE_DIR / 'biblio.json'))
        parser.add_argument('--force', action='store_true', help='remplace une base existante')

    def handle(self, *args, json, force, **options):
        src, dst = Path(json), Path(settings.FR_DB)
        if not src.is_file():
            raise CommandError(f'Fichier introuvable : {src}')
        if dst.exists() and not force:
            raise CommandError(f'{dst} existe déjà (--force pour la remplacer).')
        try:
            with open(src, encoding='utf-8') as f:
                data = jsonlib.load(f)
        except ValueError as e:
            raise CommandError(f'JSON invalide : {e}')
        connections.close_all()
        n = json2db.build(data, str(dst))
        self.stdout.write(self.style.SUCCESS(f'{n} entrées -> {dst}'))
