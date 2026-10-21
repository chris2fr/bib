"""Documents proches (TF-IDF cosinus sur titre, mots-clés, résumé et début du texte) et doublons probables."""
import math
import threading
from collections import Counter, defaultdict

from django.db import connection

from .corpus import get_corpus, signature
from .textutil import FR_STOP, fold, tokens

BODY_CHARS = 6000
W = {'title': 3, 'keywords': 3, 'xtheme': 2, 'abstract': 2, 'author': 1, 'organization': 1}
_lock = threading.RLock()
_cache = {'sig': None, 'obj': None}


def get_similarity():
    with _lock:
        sig = signature()
        if _cache['obj'] is None or _cache['sig'] != sig:
            _cache['obj'], _cache['sig'] = Similarity(get_corpus()), sig
        return _cache['obj']


class Similarity:
    def __init__(self, corpus):
        self.corpus = corpus
        with connection.cursor() as c:
            c.execute('SELECT n, substr(markdown, 1, %s) FROM pieces', [BODY_CHARS])
            bodies = dict(c.fetchall())
        tf = {}
        for d in corpus.docs:
            cnt = Counter()

            def add(text, w):
                for t in tokens(text):
                    if len(t) >= 3 and not t.isdigit() and t not in FR_STOP:
                        cnt[t] += w
            for f, w in W.items():
                add(' '.join(d.values(f)), w)
            add(bodies.get(d.n), 1)
            tf[d.n] = cnt
        df = Counter()
        for cnt in tf.values():
            df.update(cnt.keys())
        N = len(corpus.docs)
        idf = {t: math.log((N + 1) / (c + 1)) + 1 for t, c in df.items() if 2 <= c <= 0.4 * N}
        self.vec, self.post = {}, defaultdict(list)
        for n, cnt in tf.items():
            v = {t: (1 + math.log(c)) * idf[t] for t, c in cnt.items() if t in idf}
            norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
            self.vec[n] = {t: x / norm for t, x in v.items()}
            for t, x in self.vec[n].items():
                self.post[t].append((n, x))

    def similar(self, n, k=8, min_score=0.05):
        acc = defaultdict(float)
        for t, x in self.vec.get(n, {}).items():
            for m, y in self.post[t]:
                if m != n:
                    acc[m] += x * y
        best = sorted(((m, s) for m, s in acc.items() if s >= min_score), key=lambda x: -x[1])[:k]
        return [(self.corpus.by_n[m], s) for m, s in best]

    def duplicates(self, threshold=0.85):
        """Paires probablement identiques : texte très proche, même titre, même empreinte sha256, ou champ xduplicate."""
        pairs = defaultdict(lambda: {'score': 0.0, 'reasons': []})
        for n in self.vec:
            for d, s in self.similar(n, k=5, min_score=threshold):
                if n < d.n:
                    p = pairs[(n, d.n)]
                    p['score'] = max(p['score'], s)
                    p['reasons'].append(f'texte proche ({s:.2f})')
        groups = defaultdict(list)
        for d in self.corpus.docs:
            t = ' '.join(tokens(d.v['title'] or ''))
            if len(t) > 12:
                groups[('titre', t)].append(d)
            sha = d.extra.get('sha256')
            if sha:
                groups[('sha256', sha)].append(d)
        for (kind, _), ds in groups.items():
            for i, a in enumerate(ds):
                for b in ds[i + 1:]:
                    p = pairs[(a.n, b.n)]
                    p['score'] = max(p['score'], 1.0 if kind == 'sha256' else 0.95)
                    p['reasons'].append('même empreinte sha256' if kind == 'sha256' else 'même titre')
        for d in self.corpus.docs:
            if d.v.get('xduplicate'):
                p = pairs[(d.n, d.n)]
                p['score'] = max(p['score'], 0.5)
                p['reasons'].append(f'xduplicate : {d.v["xduplicate"]}')
        out = []
        for (a, b), p in pairs.items():
            out.append({'a': self.corpus.by_n[a], 'b': self.corpus.by_n[b] if a != b else None,
                        'score': p['score'], 'reasons': list(dict.fromkeys(p['reasons']))})
        out.sort(key=lambda x: (-x['score'], x['a'].key))
        return out
