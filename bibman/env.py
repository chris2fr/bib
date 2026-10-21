"""Chargement du fichier .env (facultatif) : un fichier de lignes CLÉ=valeur à la racine du projet, ou celui que désigne
BIBMAN_ENV_FILE. Les variables déjà présentes dans l'environnement l'emportent sur le fichier."""
import os
from pathlib import Path

from dotenv import load_dotenv


def load_env(base_dir):
    """Charge le .env s'il existe ; renvoie son chemin, ou None."""
    path = Path(os.environ.get('BIBMAN_ENV_FILE') or Path(base_dir) / '.env')
    if path.is_file() and load_dotenv(path, override=False, encoding='utf-8') is not None:
        return path
    return None
