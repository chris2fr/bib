"""Passage entre une entrée du fr.json « remonté » et une ligne de la table `pieces` (voir json2db.py).

Une entrée est un dict ordonné :
  key, ENTRYTYPE, champs BibTeX (BIB, valeurs de base), autres champs (extra), markdown,
  bibtex = {champ: valeur} (surcharges du .bib ; None supprime le champ du .bib).
L'ordre des clés est conservé dans `field_order` pour que l'export redonne exactement la même entrée."""
import json

BIB = ['title', 'author', 'abstract', 'note', 'number', 'organization', 'type', 'xtype', 'keywords', 'xtheme',
       'date', 'year', 'language', 'xcounter', 'xacronym', 'shorthand', 'url', 'howpublished', 'xtime', 'xdatetime', 'xtimezone',
       'file', 'publisher', 'urldate', 'annote', 'volume', 'medium', 'issue', 'collection', 'archive', 'edition',
       'xduplicate', 'shorthand2']
BIBSET = frozenset(BIB)
SPECIAL = frozenset(['key', 'ENTRYTYPE', 'markdown', 'bibtex'])
_TAIL = ('markdown', 'bibtex')


def _dumps(v):
    return json.dumps(v, ensure_ascii=False)


def entry_to_row(entry):
    """Entrée -> dict de colonnes de `pieces` (id, entrytype, BIB..., extra, bibtex, markdown, field_order)."""
    extra = {k: v for k, v in entry.items() if k not in SPECIAL and k not in BIBSET}
    row = {'id': entry['key'], 'entrytype': entry.get('ENTRYTYPE')}
    for f in BIB:
        row[f] = entry.get(f)
    row['extra'] = _dumps(extra)
    row['bibtex'] = _dumps(entry['bibtex']) if entry.get('bibtex') else None
    row['markdown'] = entry.get('markdown') or ''
    row['field_order'] = _dumps(list(entry))
    return row


def row_to_entry(row):
    """Ligne de `pieces` -> entrée, avec les clés dans leur ordre d'origine."""
    extra = json.loads(row['extra'] or '{}')
    values = {'key': row['id'], 'ENTRYTYPE': row['entrytype'], 'markdown': row['markdown'],
              'bibtex': json.loads(row['bibtex']) if row['bibtex'] else None}
    values.update({f: row[f] for f in BIB})
    values.update(extra)
    order = json.loads(row['field_order'] or '[]')
    entry = {}
    for k in order:
        if k in values and (values[k] is not None):
            entry[k] = values[k]
    for k, v in values.items():                       # champs absents de field_order (base modifiée à la main)
        if k not in entry and v not in (None, '') and k != 'bibtex':
            put_field(entry, k, v)
    if values['bibtex'] and 'bibtex' not in entry:
        entry['bibtex'] = values['bibtex']
    return entry


def put_field(entry, name, value):
    """Affecte un champ; un nouveau champ s'insère avant markdown/bibtex, qui restent en fin d'entrée."""
    if name in entry:
        entry[name] = value
        return
    tail = [(k, entry.pop(k)) for k in [k for k in entry if k in _TAIL]]
    entry[name] = value
    entry.update(tail)


def set_bibtex(entry, overrides):
    """Définit (ou retire, si vide) les surcharges du .bib."""
    if overrides:
        entry['bibtex'] = dict(overrides)
    else:
        entry.pop('bibtex', None)


def check_braces(key, field, value):
    """Lève ValueError si les accolades de value sont déséquilibrées (db2bib échouerait)."""
    depth = 0
    for ch in value:
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                break
    if depth != 0:
        raise ValueError(f'{key}: {field}: accolades déséquilibrées')
