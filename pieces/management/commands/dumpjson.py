import json
from pathlib import Path

from django.core.management.base import BaseCommand

from pieces import schema
from pieces.models import Piece


class Command(BaseCommand):
    help = "Écrit la base en JSON (même contenu et même mise en forme que l'export du site) : fichier, ou sortie standard sans argument."

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', help='fichier à écrire (ex. biblio.json)')

    def handle(self, *args, path, **options):
        schema.ensure()
        data = {p.key: p.to_entry() for p in Piece.objects.order_by('n')}
        text = json.dumps(data, indent=2, ensure_ascii=False)
        if path:
            Path(path).write_text(text + '\n', encoding='utf-8')
            self.stderr.write(f'{len(data)} entrées -> {path}')
        else:
            self.stdout.write(text)
