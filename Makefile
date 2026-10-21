# bibman : tâches courantes.  `make help` liste les cibles.
PYTHON ?= python
VENV   ?= .venv
PIP    := $(VENV)/bin/pip
PY     := $(VENV)/bin/python
JSON   ?= biblio.json
PORT   ?= 8000

.DEFAULT_GOAL := help
.PHONY: help install load dump run test check static gunicorn clean

help:  ## affiche cette aide
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)

install: $(VENV)/bin/activate  ## crée .venv et installe les dépendances
	$(PIP) install -r requirements.txt

load:  ## construit biblio.db depuis $(JSON) (FORCE=1 pour remplacer)
	$(PY) manage.py loadjson $(JSON) $(if $(FORCE),--force)

dump:  ## réécrit $(JSON) depuis biblio.db
	$(PY) manage.py dumpjson $(JSON)

run:  ## serveur de développement sur http://127.0.0.1:$(PORT)
	$(PY) manage.py runserver $(PORT)

test:  ## lance les tests
	$(PY) manage.py test

check:  ## contrôles Django
	$(PY) manage.py check

static:  ## collecte les fichiers statiques (déploiement)
	$(PY) manage.py collectstatic --noinput

gunicorn: static  ## sert l'application avec gunicorn (DJANGO_DEBUG=0, voir README)
	$(PIP) install -q gunicorn
	$(VENV)/bin/gunicorn bibman.wsgi --bind 127.0.0.1:$(PORT)

clean:  ## supprime caches Python et fichiers statiques collectés
	find . -name __pycache__ -not -path './$(VENV)/*' -prune -exec rm -rf {} +
	rm -rf staticfiles
