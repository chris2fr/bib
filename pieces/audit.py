"""Contrôles de cohérence : la clé AAAA-MM-JJ-acronyme-compteur doit s'accorder avec year, date, xacronym, xcounter, shorthand."""
import re
from collections import OrderedDict

from .corpus import get_corpus

KEY_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})-([a-z0-9]+)-(.+)$')
DATE_RE = re.compile(r'^\d{4}(-\d{2}(-\d{2})?)?$')
CHECKS = OrderedDict([
    ('key-format', 'Clé hors format AAAA-MM-JJ-acronyme-compteur'),
    ('year', 'Année du champ year différente de celle de la clé'),
    ('date', 'Date différente de celle de la clé'),
    ('acronym', 'xacronym différent de l\'acronyme de la clé'),
    ('counter', 'xcounter différent du compteur de la clé'),
    ('shorthand', 'shorthand différent de la clé'),
    ('date-format', 'Date mal formée (attendu AAAA, AAAA-MM ou AAAA-MM-JJ)'),
    ('missing-title', 'Titre absent'),
    ('missing-date', 'Date absente'),
])


def run_audit():
    corpus = get_corpus()
    found = OrderedDict((k, []) for k in CHECKS)
    for d in corpus.docs:
        v = d.v
        m = KEY_RE.match(d.key)
        if not m:
            found['key-format'].append((d, ''))
        else:
            y, mo, da, acr, cnt = m.groups()
            if v['year'] and v['year'] != y:
                found['year'].append((d, f'clé {y}, year {v["year"]}'))
            if d.date and DATE_RE.match(d.date):
                parts = d.date.split('-') + ['00', '00']
                for label, kv, dv in (('année', y, parts[0]), ('mois', mo, parts[1]), ('jour', da, parts[2])):
                    if kv != '00' and dv != '00' and kv != dv:
                        found['date'].append((d, f'{label} : clé {kv}, date {d.date}'))
                        break
            if v['xacronym'] and v['xacronym'] != acr:
                found['acronym'].append((d, f'clé {acr}, xacronym {v["xacronym"]}'))
            if v['xcounter'] and v['xcounter'] != cnt:
                found['counter'].append((d, f'clé {cnt}, xcounter {v["xcounter"]}'))
        if v['shorthand'] and v['shorthand'] != d.key:
            found['shorthand'].append((d, f'shorthand {v["shorthand"]}'))
        if d.date and not DATE_RE.match(d.date):
            found['date-format'].append((d, d.date))
        if not v['title']:
            found['missing-title'].append((d, ''))
        if not d.date:
            found['missing-date'].append((d, ''))
    return [{'id': k, 'label': CHECKS[k], 'items': items} for k, items in found.items()]
