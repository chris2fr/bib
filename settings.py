"""Réglages du site de gestion de fr.json.

Variables d'environnement :
  FR_DB          base SQLite produite par json2db.sh (défaut : ./fr.db)
  FR_TOOLS_LIB   dossier contenant frlib.py et json2db.py (défaut : ../outils/lib)
  FR_SYNONYMS    fichier de synonymes (défaut : ./synonyms.txt)
  FR_READONLY    1 = consultation seule (pas de création, modification ni suppression)
  DJANGO_SECRET_KEY, DJANGO_DEBUG (1 par défaut), DJANGO_ALLOWED_HOSTS (liste séparée par des virgules)
Ne lancez pas « manage.py migrate » : l'application n'a aucune migration et la base appartient aux scripts json2db / db2json.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

FR_TOOLS_LIB = Path(os.environ.get('FR_TOOLS_LIB', BASE_DIR.parent / 'outils' / 'lib')).resolve()
if str(FR_TOOLS_LIB) not in sys.path:
    sys.path.insert(0, str(FR_TOOLS_LIB))

FR_DB = Path(os.environ.get('FR_DB', BASE_DIR / 'fr.db')).resolve()
FR_SYNONYMS = Path(os.environ.get('FR_SYNONYMS', BASE_DIR / 'synonyms.txt'))
FR_READONLY = os.environ.get('FR_READONLY', '') == '1'

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'dev-only-change-me')
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]'] + [h for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h]

INSTALLED_APPS = [
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'pieces',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
]
MESSAGE_STORAGE = 'django.contrib.messages.storage.cookie.CookieStorage'
ROOT_URLCONF = 'frsite.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.messages.context_processors.messages',
        'pieces.context.site',
    ]},
}]
WSGI_APPLICATION = 'frsite.wsgi.application'

# Une seule base : celle de fr.json. Aucune table Django n'y est créée (pas de migrations, pas d'auth ni de sessions).
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': FR_DB, 'OPTIONS': {'timeout': 20}}}
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

LANGUAGE_CODE = 'fr'
TIME_ZONE = 'Europe/Paris'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024 * 1024        # un champ markdown peut dépasser 700 Ko
