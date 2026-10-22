"""Modification de plusieurs entrées à la fois : mots-clés (ajouter, retirer, remplacer) et quelques champs de classement.

Les mots-clés sont des listes « a, b, c » (virgule et espace). Comparaisons sans accents ni casse ; l'orthographe écrite est
celle déjà la plus utilisée dans la base (ou, à défaut, celle de la liste d'aide). Une entrée dont la liste ne change pas
n'est pas touchée (son texte d'origine, même séparé autrement, reste tel quel)."""
from collections import Counter
from dataclasses import dataclass, field

from frlib import check_braces, put_field

from . import helpers
from .helpers import split_multi
from .textutil import fold

# (champ, étiquette) ; ENTRYTYPE s'écrit entrytype dans le formulaire
BULK_FIELDS = [('entrytype', 'ENTRYTYPE'), ('xtheme', 'Thème'), ('type', 'Nature'), ('xacronym', 'Source'),
               ('language', 'Langue'), ('xtype', 'xtype'), ('organization', 'Organisation')]
ENTRY_KEY = {'entrytype': 'ENTRYTYPE'}
BULK_MAX = 2000


@dataclass
class Changes:
    kw_add: list = field(default_factory=list)
    kw_remove: list = field(default_factory=list)
    kw_replace: bool = False
    values: dict = field(default_factory=dict)       # champ -> nouvelle valeur
    clear: set = field(default_factory=set)          # champs à vider

    def __bool__(self):
        return bool(self.kw_add or self.kw_remove or self.kw_replace or self.values or self.clear)


def parse_changes(post):
    values = {n: post.get('bf_' + n, '').strip() for n, _ in BULK_FIELDS}
    values = {n: v for n, v in values.items() if v}
    clear = {n for n, _ in BULK_FIELDS if post.get('clear_' + n) and n != 'entrytype' and n not in values}
    return Changes(split_multi(post.get('kw_add', '')), split_multi(post.get('kw_remove', '')),
                   post.get('kw_replace') == '1', values, clear)


def vocabulary(corpus):
    """(orthographe usuelle par forme repliée, nombre d'entrées par mot-clé) d'après la base, complétés par la liste d'aide."""
    spellings = {}
    for d in corpus.docs:
        for kw in split_multi(d.v['keywords']):
            spellings.setdefault(fold(kw), Counter())[kw] += 1
    canon = {f: c.most_common(1)[0][0] for f, c in spellings.items()}
    for kw in helpers.choices('keywords'):
        canon.setdefault(fold(kw), kw)
    counts = Counter({canon[f]: sum(c.values()) for f, c in spellings.items()})
    return canon, counts


def new_keywords(old, changes, canon):
    """Liste de mots-clés après les opérations (ajout, retrait, remplacement), sans doublon."""
    items = [] if changes.kw_replace else split_multi(old)
    drop = {fold(k) for k in changes.kw_remove}
    items = [k for k in items if fold(k) not in drop]
    have = {fold(k) for k in items}
    for kw in changes.kw_add:
        kw = canon.get(fold(kw), kw)
        if fold(kw) not in have:
            items.append(kw)
            have.add(fold(kw))
    return items


def apply_to_entry(entry, changes, canon):
    """(nouvelle entrée, {champ: (avant, après)}, [erreurs])."""
    new, diff, errors = dict(entry), {}, []
    if changes.kw_add or changes.kw_remove or changes.kw_replace:
        before = split_multi(entry.get('keywords'))
        after = new_keywords(entry.get('keywords'), changes, canon)
        if after != before:
            text = ', '.join(after)
            diff['keywords'] = (entry.get('keywords') or '', text)
            if text:
                put_field(new, 'keywords', text)
            else:
                new.pop('keywords', None)
    for name, value in changes.values.items():
        key = ENTRY_KEY.get(name, name)
        if entry.get(key) == value:
            continue
        try:
            check_braces(entry['key'], name, value)
        except ValueError:
            errors.append(f'{name} : accolades {{ }} déséquilibrées')
            continue
        diff[name] = (entry.get(key) or '', value)
        put_field(new, key, value)
    for name in changes.clear:
        key = ENTRY_KEY.get(name, name)
        if entry.get(key):
            diff[name] = (entry[key], '')
            new.pop(key, None)
    return new, diff, errors


def plan(pieces, changes, canon):
    """[{'piece', 'entry', 'new', 'diff', 'errors'}] pour chaque entrée."""
    out = []
    for piece in pieces:
        entry = piece.to_entry()
        new, diff, errors = apply_to_entry(entry, changes, canon)
        out.append({'piece': piece, 'entry': entry, 'new': new, 'diff': diff, 'errors': errors})
    return out


def apply_plan(plans):
    """Enregistre les entrées modifiées sans erreur ; renvoie (modifiées, inchangées, refusées)."""
    done = same = refused = 0
    for p in plans:
        if p['errors']:
            refused += 1
        elif not p['diff']:
            same += 1
        else:
            changed = p['piece'].set_from_entry(p['new'])
            if changed:
                p['piece'].save(update_fields=changed)
                helpers.remember(p['piece'])
            done += 1
    return done, same, refused
