"""Moteur de recherche : interprétation heuristique de la requête + FTS5.

Pipeline (mode « auto »)
 1. Interprétation de la requête (sur du texte sans accents ni majuscules) :
      - dates et périodes : « entre 1990 et 2000 », « avant 2010 », « depuis 2015 », « mai 1997 », « 8 avril 2014 », 2014-04-08,
        une année seule (1997) devient un filtre sur l'année ;
      - filtres par champ : theme:dogger, org:brgm, auteur:"jean dupont", year:1990..2000, has:url, no:note, -theme:acp ;
      - clés de citation ou fragments (brgmfr-39522) et identifiants (39522, R39522) : cherchés dans la clé, number, xcounter,
        shorthand, file, url, note ; « mot » entre guillemets = expression exacte ; -mot = exclusion ; mot* = préfixe.
 2. Chaque mot est résolu séparément, de plus en plus largement, jusqu'à obtenir des résultats :
      exact (+ synonymes du fichier synonyms.txt)  ->  racine (« géothermiques » -> geothermi*)  ->  approchant
      (termes proches de l'index à 1 ou 2 fautes de frappe).
 3. Les mots sont combinés en ET ; si le ET est vide, on relâche : documents contenant au moins la moitié des mots
    (« résultats partiels »), les mots sans aucun résultat sont ignorés et signalés.
 4. Classement : bm25 pondéré par colonne (titre > clé = mots-clés > auteur > résumé > note = organisation > texte), minoré pour les
    racines et les approchants, majoré pour les identifiants, les mots présents dans le titre et le nombre de mots trouvés.
Mode « fts » : la requête est transmise telle quelle à FTS5 (AND, OR, NOT, NEAR, "phrase", préfixe*, colonne:mot)."""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.conf import settings
from django.db import DatabaseError, connection
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .corpus import get_corpus
from .textutil import FR_STOP, fold, stem, strip_elision, tokens

BM25_WEIGHTS = '6, 10, 5, 4, 3, 6, 3, 1'          # id, title, author, abstract, note, keywords, organization, markdown
LEVEL_WEIGHT = {'exact': 1.0, 'mots séparés': 0.8, 'racine': 0.7, 'approchant': 0.5}
IDENT_SCORE, KEY_SCORE = 12.0, 20.0
FACETS = ['xtheme', 'xtype', 'xacronym', 'type', 'language']
FACET_LABELS = {'xtheme': 'Thème', 'xtype': 'Nature', 'xacronym': 'Source', 'type': 'Type', 'language': 'Langue',
                'decade': 'Décennie'}
SORTS = [('rel', 'Pertinence'), ('date', 'Chronologique'), ('date_desc', 'Plus récent d\'abord'), ('title', 'Titre')]

MONTHS = {m: i for i, m in enumerate('janvier fevrier mars avril mai juin juillet aout septembre octobre novembre decembre'.split(), 1)}
_MONTH_RE = '|'.join(MONTHS)
FIELD_ALIASES = {
    'title': 'title', 'titre': 'title', 'author': 'author', 'auteur': 'author',
    'org': 'organization', 'organisation': 'organization', 'organization': 'organization',
    'theme': 'xtheme', 'xtheme': 'xtheme', 'type': 'type', 'xtype': 'xtype', 'nature': 'xtype',
    'acr': 'xacronym', 'acronyme': 'xacronym', 'source': 'xacronym', 'xacronym': 'xacronym',
    'kw': 'keywords', 'mot': 'keywords', 'motcle': 'keywords', 'keyword': 'keywords', 'keywords': 'keywords',
    'lang': 'language', 'langue': 'language', 'language': 'language', 'entrytype': 'entrytype',
    'note': 'note', 'abstract': 'abstract', 'resume': 'abstract', 'url': 'url', 'file': 'file', 'fichier': 'file',
    'key': 'key', 'cle': 'key', 'id': 'key', 'year': 'year', 'annee': 'year', 'an': 'year', 'date': 'date',
    'avant': 'before', 'before': 'before', 'apres': 'after', 'after': 'after', 'depuis': 'since', 'since': 'since',
    'has': 'has', 'no': 'no', 'sans': 'no',
}
EQUALITY_FIELDS = {'xtheme', 'xtype', 'xacronym', 'type', 'language', 'entrytype'}

_TOKEN_RE = re.compile(r'(?P<neg>-)?(?:(?P<fld>[^\s:"]+):)?(?:"(?P<phrase>[^"]*)"|(?P<word>\S+))')
_KEYLIKE = re.compile(r'(?=.*\d)(?=.*[^\W\d_])[^\W_]+(?:-[^\W_]+)+')


# ---------------------------------------------------------------- structures
@dataclass
class Unit:
    kind: str                      # term | phrase | key
    toks: list
    text: str
    neg: bool = False
    prefix: bool = False
    ident: bool = False
    level: str = ''
    variants: list = field(default_factory=list)
    corrections: list = field(default_factory=list)
    hits: dict = field(default_factory=dict)
    exprs: list = field(default_factory=list)


@dataclass
class Interp:
    q: str
    units: list = field(default_factory=list)
    year: tuple = None             # (lo, hi), bornes incluses, None = ouvert
    prefixes: list = field(default_factory=list)
    fields: list = field(default_factory=list)      # (champ, valeur, négatif)
    has: list = field(default_factory=list)         # (nom, négatif)
    notes: list = field(default_factory=list)


@dataclass
class Outcome:
    ranked: list = field(default_factory=list)      # [(doc, score, nb de mots trouvés)]
    interp: dict = field(default_factory=dict)
    facets: list = field(default_factory=list)
    highlight: str = ''
    error: str = ''
    sort: str = 'rel'
    total_docs: int = 0


# ---------------------------------------------------------------- synonymes
_syn_cache = {'key': None, 'map': {}}


def synonyms():
    path = settings.FR_SYNONYMS
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return {}
    if _syn_cache['key'] != key:
        groups = {}
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.split('#', 1)[0].strip()
            if '=' not in line:
                continue
            members = [' '.join(tokens(m, lig=False)) for m in line.split('=')]
            members = [m for m in members if m]
            for m in members:
                groups.setdefault(m, [])
                groups[m] += [o for o in members if o != m and o not in groups[m]]
        _syn_cache.update(key=key, map=groups)
    return _syn_cache['map']


# ---------------------------------------------------------------- analyse de la requête
def _year_spec(s):
    s = s.strip()
    m = re.fullmatch(r'(\d{4})\s*(?:\.\.|-)\s*(\d{4})', s)
    if m: return (int(m[1]), int(m[2]))
    m = re.fullmatch(r'(>=|<=|>|<)?\s*(\d{4})', s)
    if m:
        op, y = m[1], int(m[2])
        return {None: (y, y), '>=': (y, None), '>': (y + 1, None), '<=': (None, y), '<': (None, y - 1)}[op]
    return None


def _intersect(a, b):
    if a is None: return b
    lo = max(x for x in (a[0], b[0]) if x is not None) if (a[0] is not None or b[0] is not None) else None
    hi = min(x for x in (a[1], b[1]) if x is not None) if (a[1] is not None or b[1] is not None) else None
    return (lo, hi)


def parse(q):
    it = Interp(q=q)
    s = ' ' + fold(q, lig=False).strip() + ' '

    def year(spec, note):
        it.year = _intersect(it.year, spec)
        it.notes.append(note)
        return ' '

    s = re.sub(r'\bentre\s+(\d{4})\s+et\s+(\d{4})\b', lambda m: year((int(m[1]), int(m[2])), f'période {m[1]}–{m[2]}'), s)
    s = re.sub(r'\bde\s+(\d{4})\s+a\s+(\d{4})\b', lambda m: year((int(m[1]), int(m[2])), f'période {m[1]}–{m[2]}'), s)
    s = re.sub(r'(?<![\w:-])(\d{4})(?:\.\.|-)(\d{4})(?![\w-])', lambda m: year((int(m[1]), int(m[2])), f'période {m[1]}–{m[2]}'), s)
    s = re.sub(r'\bavant\s+(\d{4})\b', lambda m: year((None, int(m[1]) - 1), f'avant {m[1]}'), s)
    s = re.sub(r'\bapres\s+(\d{4})\b', lambda m: year((int(m[1]) + 1, None), f'après {m[1]}'), s)
    s = re.sub(r'\bdepuis\s+(\d{4})\b', lambda m: year((int(m[1]), None), f'depuis {m[1]}'), s)

    def prefix(p, note):
        it.prefixes.append(p)
        it.notes.append(note)
        return ' '
    s = re.sub(rf'\b(\d{{1,2}}|1er)\s+({_MONTH_RE})\s+(\d{{4}})\b',
               lambda m: prefix(f'{m[3]}-{MONTHS[m[2]]:02d}-{int(m[1].replace("er", "")):02d}', f'date {m[0].strip()}'), s)
    s = re.sub(rf'\b({_MONTH_RE})\s+(\d{{4}})\b', lambda m: prefix(f'{m[2]}-{MONTHS[m[1]]:02d}', f'mois {m[0]}'), s)
    s = re.sub(r'(?<![\w:-])(\d{4})-(0[1-9]|1[0-2])(?:-(\d{2}))?(?![\w-])',
               lambda m: prefix(m[0].strip(), f'date {m[0]}'), s)

    for m in _TOKEN_RE.finditer(s):
        neg, fld, phrase, word = bool(m['neg']), m['fld'], m['phrase'], m['word']
        if fld:
            canon = FIELD_ALIASES.get(fld)
            value = phrase if phrase is not None else word
            if canon and value:
                _add_filter(it, canon, value.strip(), neg)
                continue
            word, phrase = m[0].lstrip('-'), None          # « http://x » ou « a:b » : simple texte
        if phrase is not None:
            toks = tokens(phrase, lig=False)
            if toks:
                it.units.append(Unit('phrase' if len(toks) > 1 else 'term', toks, ' '.join(toks), neg))
            continue
        w = strip_elision(word.strip('.,;:!?()[]{}«»\'"'))
        prefix_ = w.endswith('*')
        w = w.rstrip('*')
        if not w:
            continue
        if _KEYLIKE.fullmatch(w) and not neg:
            it.units.append(Unit('key', tokens(w, lig=False), w))
            continue
        toks = tokens(w, lig=False)
        if not toks:
            continue
        if len(toks) > 1:
            it.units.append(Unit('phrase', toks, ' '.join(toks), neg))
        elif re.fullmatch(r'(?:19|20)\d{2}', w) and not neg and not prefix_:
            it.year = _intersect(it.year, (int(w), int(w)))
            it.notes.append(f'« {w} » lu comme une année (mettez-le entre guillemets pour le chercher dans le texte)')
        else:
            it.units.append(Unit('term', toks, toks[0], neg, prefix_, ident=sum(c.isdigit() for c in w) >= 4))
    # mots vides : ignorés dès qu'il reste d'autres mots
    real = [u for u in it.units if not (u.kind == 'term' and u.toks[0] in FR_STOP and not u.prefix and not u.ident)]
    if real and len(real) != len(it.units):
        dropped = [u.text for u in it.units if u not in real]
        it.units = real
        it.notes.append('mots vides ignorés : ' + ', '.join(dropped))
    return it


def _add_filter(it, canon, value, neg):
    if canon in ('year', 'before', 'after', 'since'):
        spec = _year_spec(value)
        if spec and canon != 'year':
            y = spec[0] or spec[1]
            spec = {'before': (None, y - 1), 'after': (y + 1, None), 'since': (y, None)}[canon]
        if spec:
            it.year = _intersect(it.year, spec)
            return
    if canon == 'date':
        it.prefixes.append(value)
    elif canon in ('has', 'no'):
        it.has.append((value, neg != (canon == 'no')))     # (champ, doit être absent)
    else:
        it.fields.append((canon, value, neg))


# ---------------------------------------------------------------- filtres
def _present(doc, name):
    if name == 'override': return doc.has_override
    return bool(doc.v.get(name)) or name in doc.extra


def _field_text(doc, f):
    if f == 'key': return doc.key.lower()
    return doc.fold.get(f) or fold(doc.v.get(f))


def passes(doc, it, facets):
    for name, vals in facets.items():
        if name == 'decade':
            if doc.year is None or str(doc.year // 10 * 10) not in vals: return False
        elif not any(v in vals for v in doc.values(name)):
            return False
    if it.year:
        lo, hi = it.year
        if doc.year is None or (lo is not None and doc.year < lo) or (hi is not None and doc.year > hi): return False
    if it.prefixes and not any(doc.date.startswith(p) or (len(p) == 4 and doc.year == int(p)) for p in it.prefixes):
        return False
    for f, value, neg in it.fields:
        wanted = [fold(v) for v in value.split(',')] if f in EQUALITY_FIELDS else [fold(value)]
        if f in EQUALITY_FIELDS:
            have = {fold(v) for v in doc.values(f)}
            ok = any(w in have for w in wanted)
        else:
            text = _field_text(doc, f)
            ok = any(w in text for w in wanted)
        if ok == neg: return False
    for name, must_be_absent in it.has:
        if _present(doc, name) == must_be_absent: return False
    return True


# ---------------------------------------------------------------- FTS5
def _phrase(toks, prefix=False):
    return '"%s"%s' % (' '.join(toks), '*' if prefix else '')


def fts_hits(expr):
    with connection.cursor() as c:
        c.execute(f'SELECT rowid, bm25(pieces_fts, {BM25_WEIGHTS}) FROM pieces_fts WHERE pieces_fts MATCH %s', [expr])
        return {n: -s for n, s in c.fetchall()}


def _scaled(hits, k):
    return {n: s * k for n, s in hits.items()}


def eval_unit(u, corpus, syn, broad=False):
    """Calcule u.hits ({n: score}), u.level, u.variants et u.exprs (expressions FTS utilisées, pour les extraits)."""
    if u.neg:
        if u.kind == 'term' and u.toks:
            u.hits = fts_hits(_phrase(u.toks, u.prefix))
        elif u.kind == 'phrase':
            u.hits = fts_hits(_phrase(u.toks))
        return
    if u.kind == 'key':
        frag = u.text
        u.hits = {d.n: KEY_SCORE for d in corpus.docs if frag in d.idtext}
        if u.hits:
            u.level = 'exact'
            return
        u.kind = 'phrase'                                  # repli : « covid-19 » -> expression « covid 19 »
    if u.kind == 'phrase':
        ph = ' '.join(u.toks)
        group = syn.get(ph, [])
        expr = ' OR '.join(_phrase(v.split()) for v in [ph] + group)
        u.hits, u.exprs, u.variants = fts_hits(expr), [expr], group
        if u.hits:
            u.level = 'exact'
            return
        subs = [Unit('term', [t], t) for t in u.toks if t not in FR_STOP]
        for s in subs:
            eval_unit(s, corpus, syn)
        subs = [s for s in subs if s.hits]
        if subs:
            common = set.intersection(*(set(s.hits) for s in subs))
            u.hits = {n: sum(s.hits[n] for s in subs) * LEVEL_WEIGHT['mots séparés'] for n in common}
            u.exprs = [e for s in subs for e in s.exprs]
            if u.hits:
                u.level = 'mots séparés'
                return
        u.level = 'aucun'
        return
    # terme simple
    t = u.toks[0]
    group = syn.get(t, [])
    parts = [_phrase(v.split(), u.prefix and v == t) for v in [t] + group]
    expr = ' OR '.join(parts)
    hits, exprs = fts_hits(expr), [expr]
    if u.ident:
        for d in corpus.docs:
            if t in d.idtext or t in d.idcompact: hits[d.n] = max(hits.get(d.n, 0.0), IDENT_SCORE)
    if hits:
        u.level, u.variants = 'exact', group
    if (not hits or broad) and not u.ident:
        s = stem(t)
        if s != t and len(s) >= 4 and not u.prefix:
            h = fts_hits(_phrase([s], True))
            if h:
                exprs.append(_phrase([s], True))
                for n, v in _scaled(h, LEVEL_WEIGHT['racine']).items(): hits[n] = max(hits.get(n, 0.0), v)
                if not u.level: u.level = 'racine'
                u.variants = group + [s + '*']
    if not hits and not u.ident:
        near = corpus.vocab().neighbors(t)
        if near:
            e = ' OR '.join(_phrase([w]) for w, _, _ in near)
            h = fts_hits(e)
            if h:
                hits, exprs = _scaled(h, LEVEL_WEIGHT['approchant']), exprs + [e]
                u.level, u.corrections = 'approchant', [w for w, _, _ in near]
    u.hits, u.exprs = hits, exprs
    if not hits:
        u.level = 'aucun'


# ---------------------------------------------------------------- recherche
def search(q='', mode='auto', facets=None, sort='rel', broad=False):
    corpus = get_corpus()
    facets = facets or {}
    out = Outcome(sort=sort, total_docs=len(corpus.docs))
    q = (q or '').strip()
    if mode == 'fts' and q:
        it = Interp(q=q)
        cand = {d.n for d in corpus.docs if passes(d, it, facets)}
        try:
            hits = fts_hits(q)
        except DatabaseError as e:
            out.error = f'Requête FTS5 invalide : {e}'
            return out
        ids = {n for n in hits if n in cand}
        scores = {n: hits[n] for n in ids}
        counts = {n: 1 for n in ids}
        out.highlight = q
        out.interp = {'mode': 'FTS5 brut', 'filters': [], 'units': [], 'notes': [], 'relaxed': ''}
    else:
        it = parse(q) if q else Interp(q='')
        cand = {d.n for d in corpus.docs if passes(d, it, facets)}
        syn = synonyms()
        for u in it.units:
            eval_unit(u, corpus, syn, broad)
        pos = [u for u in it.units if not u.neg]
        scores, counts, relaxed = {}, {}, ''
        if not pos:
            ids = set(cand)
        else:
            active = [u for u in pos if u.hits]
            missing = [u for u in pos if not u.hits]
            if not active:
                ids = set()
            else:
                sets = [set(u.hits) & cand for u in active]
                ids = set.intersection(*sets)
                if missing and ids:
                    it.notes.append('sans résultat, ignoré : ' + ', '.join(u.text for u in missing))
                if not ids:
                    c = Counter(n for s in sets for n in s)
                    need = 2 if len(active) >= 3 else 1
                    ids = {n for n, k in c.items() if k >= need}
                    relaxed = f'résultats partiels : documents contenant au moins {need} des {len(active)} mots' if ids else ''
                for n in ids:
                    counts[n] = sum(1 for u in active if n in u.hits)
                    scores[n] = sum(u.hits.get(n, 0.0) for u in active) + 1000.0 * counts[n] * (1 if relaxed else 0)
                _title_boost(corpus, ids, scores, active)
        for u in it.units:
            if u.neg:
                ids -= set(u.hits)
        out.highlight = ' OR '.join(e for u in pos for e in u.exprs)
        out.interp = _describe(it, relaxed)
    docs = [corpus.by_n[n] for n in ids]
    ranked_query = bool(scores) or (mode == 'fts' and bool(q))
    if sort == 'rel' and ranked_query:
        docs.sort(key=lambda d: (-scores.get(d.n, 0.0), d.key))
    elif sort == 'date_desc':
        docs.sort(key=lambda d: d.key, reverse=True)
    elif sort == 'title':
        docs.sort(key=lambda d: (fold(d.title), d.key))
    else:
        out.sort = 'date' if sort in ('rel', 'date') else sort
        docs.sort(key=lambda d: d.key)
    out.ranked = [(d, scores.get(d.n, 0.0), counts.get(d.n, 0)) for d in docs]
    out.facets = _facets(docs, facets)
    return out


def _title_boost(corpus, ids, scores, active):
    singles = [u for u in active if u.kind == 'term']
    for n in ids:
        d = corpus.by_n[n]
        if d.title_toks is None:
            d.title_toks = set(tokens(d.v['title'], lig=False))
        found = [u for u in singles if u.toks[0] in d.title_toks or any(t.startswith(stem(u.toks[0])) for t in d.title_toks if len(stem(u.toks[0])) >= 4)]
        scores[n] += 3.0 * len(found) + (4.0 if singles and len(found) == len(singles) else 0.0)


def _facets(docs, selected):
    out = []
    for name in FACETS + ['decade']:
        c = Counter()
        for d in docs:
            for v in ([f'{d.year // 10 * 10}'] if name == 'decade' and d.year else d.values(name) if name != 'decade' else []):
                c[v] += 1
        if name == 'decade':
            vals = sorted(c.items())
        else:
            vals = sorted(c.items(), key=lambda x: (-x[1], x[0]))[:15]
        if vals or name in selected:
            out.append({'name': name, 'label': FACET_LABELS[name], 'values': vals})
    return out


def _describe(it, relaxed):
    filters = []
    if it.year:
        lo, hi = it.year
        filters.append('année ' + (f'{lo}' if lo == hi else f'{lo or "…"} – {hi or "…"}'))
    filters += [f'date commence par {p}' for p in it.prefixes]
    filters += [f'{"pas de " if neg else ""}{f} = {v}' if f in EQUALITY_FIELDS else f'{"pas de " if neg else ""}{f} contient « {v} »'
                for f, v, neg in it.fields]
    filters += [(f'sans {name}' if absent else f'avec {name}') for name, absent in it.has]
    units = []
    for u in it.units:
        label = {'exact': 'exact', 'racine': 'élargi à la racine', 'approchant': 'orthographe approchante',
                 'mots séparés': 'mots séparés', 'aucun': 'aucun résultat', '': ''}[u.level if not u.neg else '']
        extra = u.corrections or u.variants
        units.append({'text': ('-' if u.neg else '') + (f'« {u.text} »' if u.kind == 'phrase' else u.text),
                      'level': u.level, 'label': label, 'detail': ', '.join(extra), 'neg': u.neg})
    return {'mode': 'heuristique', 'filters': filters, 'units': units, 'notes': it.notes, 'relaxed': relaxed}


# ---------------------------------------------------------------- extraits
SNIPPET_COLUMNS = (7, 3, 4, 5)        # markdown, abstract, note, keywords : la clé et le titre sont déjà affichés


def snippets(ns, expr):
    """{n: extrait HTML sûr} pour les documents ns, avec les mots trouvés entourés de <mark>."""
    if not ns or not expr:
        return {}
    marks = ['\x02', '\x03', ' … ']
    cols = ', '.join(f'snippet(pieces_fts, {c}, %s, %s, %s, 24)' for c in SNIPPET_COLUMNS)
    sql = (f'SELECT rowid, {cols} FROM pieces_fts WHERE pieces_fts MATCH %s '
           f'AND rowid IN ({",".join(["%s"] * len(ns))})')
    try:
        with connection.cursor() as c:
            c.execute(sql, [*(marks * len(SNIPPET_COLUMNS)), expr, *ns])
            rows = c.fetchall()
    except DatabaseError:
        return {}
    out = {}
    for n, *texts in rows:
        text = next((t for t in texts if t and '\x02' in t), None)     # première colonne où un mot a été trouvé
        if text:
            out[n] = mark_safe(escape(text).replace('\x02', '<mark>').replace('\x03', '</mark>'))
    return out
