"""Contrôles de cohérence : la clé AAAA-MM-JJ-acronyme-compteur doit s'accorder avec year, date, xacronym, xcounter, shorthand."""
import re
from collections import OrderedDict

from . import files
from .corpus import get_corpus
from .dates import check_time, check_timezone, make_datetime

KEY_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})-([a-z0-9]+)-(.+)$')
DATE_RE = re.compile(r'^\d{4}-(0\d|1[0-2])-\d{2}$')
CHECKS = OrderedDict([
    ('key-format', 'Clé hors format AAAA-MM-JJ-acronyme-compteur'),
    ('year', 'Année du champ year différente de celle de la clé'),
    ('date', 'Date différente de celle de la clé'),
    ('year-date', 'Année (year) différente de celle de la date'),
    ('acronym', 'xacronym différent de l\'acronyme de la clé'),
    ('counter', 'xcounter différent du compteur de la clé'),
    ('shorthand', 'shorthand différent de la clé'),
    ('date-format', 'Date mal formée (attendu AAAA-MM-JJ, MM et JJ pouvant valoir 00)'),
    ('time-format', 'Heure xtime mal formée (attendu HH:MM)'),
    ('timezone', 'Fuseau xtimezone inconnu'),
    ('datetime', 'xdatetime différent de date + xtime + xtimezone'),
    ('file-path', 'Champ file avec un dossier (attendu : nom de fichier seul)'),
    ('file-missing', 'Fichier du champ file absent du dossier BIBMAN_FILES'),
    ('xdup', 'xdup invalide (clé introuvable, soi-même ou doublon d\'un doublon)'),
    ('missing-title', 'Titre absent'),
    ('missing-date', 'Date absente'),
])


def run_audit():
    corpus = get_corpus()
    folder_ok = files.folder().is_dir()
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
                if v['year'] and v['year'] != d.date[:4]:
                    found['year-date'].append((d, f'date {d.date}, year {v["year"]}'))
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
        if v['xtime'] and check_time(v['xtime']):
            found['time-format'].append((d, v['xtime']))
        if v['xtimezone'] and check_timezone(v['xtimezone']):
            found['timezone'].append((d, v['xtimezone']))
        expected = make_datetime(d.date, v['xtime'], v['xtimezone'])
        if expected and v['xdatetime'] != expected:
            found['datetime'].append((d, f'attendu {expected}, xdatetime {v["xdatetime"] or "(vide)"}'))
        if v['file'] and not files.safe_name(v['file'].strip()):
            found['file-path'].append((d, v['file']))
        elif v['file'] and folder_ok and not files.locate(d.key, v['file']):
            found['file-missing'].append((d, v['file']))
        if v['xdup']:
            target = corpus.by_key.get(v['xdup'])
            if v['xdup'] == d.key:
                found['xdup'].append((d, 'doublon de lui-même'))
            elif target is None:
                found['xdup'].append((d, f'clé introuvable : {v["xdup"]}'))
            elif target.v['xdup']:
                found['xdup'].append((d, f'{v["xdup"]} est lui-même un doublon de {target.v["xdup"]}'))
        if not v['title']:
            found['missing-title'].append((d, ''))
        if not d.date:
            found['missing-date'].append((d, ''))
    return [{'id': k, 'label': CHECKS[k], 'items': items} for k, items in found.items()]
