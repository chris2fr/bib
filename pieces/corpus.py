"""Corpus en mémoire (sans le markdown) et vocabulaire FTS5, recalculés quand la base change."""
import json
import os
import re
import threading
from collections import Counter, defaultdict

from django.conf import settings
from django.db import connection
from frlib import BIB

from .models import Piece
from .textutil import fold, osa, trigrams

SEARCH_FIELDS = ['title', 'author', 'organization', 'keywords', 'abstract', 'note',
                 'xtheme', 'xtype', 'xacronym', 'type', 'language']
CONTROLLED = ['xtheme', 'xtype', 'xacronym', 'type', 'language', 'entrytype']
IDENT_FIELDS = ['number', 'xcounter', 'shorthand', 'file', 'url', 'note', 'xduplicate', 'shorthand2']

_VERSION = 0
_lock = threading.RLock()
_cache = {'sig': None, 'corpus': None}


def bump():
    """Invalide les caches (appelé après toute écriture via l'ORM)."""
    global _VERSION
    _VERSION += 1


def signature():
    name = str(settings.DATABASES['default']['NAME'])
    stats = []
    for suffix in ('', '-wal'):
        try:
            s = os.stat(name + suffix)
            stats.append((s.st_mtime_ns, s.st_size))
        except OSError:
            pass
    return (_VERSION, tuple(stats))


class Doc:
    __slots__ = ('n', 'key', 'v', 'ov', 'extra', 'has_override', 'fold', 'idtext', 'idcompact', 'year', 'date', 'title_toks')

    def __init__(self, p):
        self.n, self.key = p.n, p.key
        self.v = {f: getattr(p, f) for f in BIB}
        self.v['entrytype'] = p.entrytype
        self.extra = json.loads(p.extra)
        ov = json.loads(p.bibtex) if p.bibtex else {}
        self.ov = {f: v for f, v in ov.items() if isinstance(v, str)}      # surcharges du .bib (valeurs texte)
        self.has_override = bool(ov)
        self.date = (self.v['date'] or '').strip()
        m = re.match(r'\d{4}', (self.v['year'] or '').strip() or self.date)
        self.year = int(m.group()) if m else None
        self.fold = {f: fold(' '.join(x for x in dict.fromkeys([self.v.get(f), self.ov.get(f)]) if x))
                     for f in SEARCH_FIELDS if self.v.get(f) or self.ov.get(f)}
        idvals = [fold(str(x)) for x in [p.key] + [self.v.get(f) for f in IDENT_FIELDS] if x]
        self.idtext = ' '.join(idvals)
        self.idcompact = ' '.join(re.sub(r'[^0-9a-z]', '', x) for x in idvals)     # « R 39522 » -> « r39522 »
        self.title_toks = None

    @property
    def title(self):
        return self.v['title'] or self.ov.get('title') or self.key

    def values(self, f):
        """Valeur de base et valeur surchargée d'un champ (sans doublon, sans vide)."""
        return [x for x in dict.fromkeys([self.v.get(f), self.ov.get(f)]) if x]


class Corpus:
    def __init__(self, docs):
        self.docs = docs
        self.by_n = {d.n: d for d in docs}
        self.by_key = {d.key: d for d in docs}
        self._vocab = None

    def vocab(self):
        if self._vocab is None:
            self._vocab = Vocab(load_vocabulary(self))
        return self._vocab


def get_corpus():
    with _lock:
        sig = signature()
        if _cache['corpus'] is None or _cache['sig'] != sig:
            docs = [Doc(p) for p in Piece.objects.defer('markdown').order_by('key')]
            _cache['corpus'], _cache['sig'] = Corpus(docs), sig
        return _cache['corpus']


def load_vocabulary(corpus):
    """terme -> nombre de documents, d'après l'index FTS5 (table fts5vocab temporaire); repli sur les métadonnées."""
    try:
        with connection.cursor() as c:
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.pieces_vocab USING fts5vocab(main, pieces_fts, 'row')")
            c.execute('SELECT term, doc FROM temp.pieces_vocab')
            return {t: df for t, df in c.fetchall()}
    except Exception:
        df = Counter()
        for d in corpus.docs:
            for t in {t for f in d.fold.values() for t in re.findall(r'[^\W_]+', f)}:
                df[t] += 1
        return dict(df)


class Vocab:
    """Termes de l'index + index de trigrammes pour retrouver rapidement les termes proches d'un mot mal orthographié."""

    def __init__(self, df):
        self.df = df
        self.index = defaultdict(list)
        for t in df:
            if len(t) >= 3 and not t.isdigit():
                for g in trigrams(t):
                    self.index[g].append(t)

    @staticmethod
    def max_distance(t):
        return 0 if len(t) <= 4 or t.isdigit() else 1 if len(t) <= 7 else 2

    def neighbors(self, t, limit=6):
        """Termes de l'index à distance d'édition <= 1 ou 2 de t, les plus fréquents d'abord. [(terme, distance, df)]"""
        maxd = self.max_distance(t)
        if not maxd:
            return []
        grams = trigrams(t)
        shared = Counter()
        for g in grams:
            for cand in self.index.get(g, ()):
                shared[cand] += 1
        need = max(1, len(grams) - 3 * maxd)
        out = []
        for cand, k in shared.items():
            if k < need or cand == t:
                continue
            d = osa(t, cand, maxd)
            if d <= maxd:
                out.append((cand, d, self.df[cand]))
        out.sort(key=lambda x: (x[1], -x[2], x[0]))
        if out:                                       # écarte le bruit : mots beaucoup plus rares que le meilleur candidat
            best = out[0][1]
            top = max(df for _, d, df in out if d == best)
            out = [x for x in out if x[1] == best and x[2] >= 0.2 * top or x[2] >= 0.5 * top]
        return out[:limit]
