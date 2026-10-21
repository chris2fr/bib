"""Fichiers sources : dossier BIBMAN_FILES, un fichier par entrée.

Le nom est de préférence celui du champ `file` (nom seul, sans dossier) ; à défaut ${CLÉ}.pdf."""
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


@dataclass
class Located:
    name: str
    path: Path
    via: str            # 'file' (champ file) ou 'key' (${CLÉ}.pdf)


def folder():
    return Path(settings.BIBMAN_FILES)


def safe_name(name):
    """Vrai pour un nom de fichier seul : ni dossier, ni '..', ni octet nul."""
    return bool(name) and name not in ('.', '..') and '\x00' not in name and '/' not in name and '\\' not in name


def expected_name(key, file_prop):
    """Nom attendu : champ file s'il est utilisable, sinon ${CLÉ}.pdf."""
    prop = (file_prop or '').strip()
    return prop if safe_name(prop) else f'{key}.pdf'


def locate(key, file_prop):
    """Fichier source existant de l'entrée (champ file d'abord, puis ${CLÉ}.pdf), ou None."""
    root = folder()
    for via, name in (('file', (file_prop or '').strip()), ('key', f'{key}.pdf')):
        if safe_name(name) and (root / name).is_file():
            return Located(name, root / name, via)
    return None


def names(limit=2000):
    """Noms des fichiers du dossier (pour les suggestions du formulaire)."""
    try:
        return sorted(p.name for p in folder().iterdir() if p.is_file() and not p.name.startswith('.'))[:limit]
    except OSError:
        return []
