"""Normalisation du texte pour la recherche : sans accents ni casse, racines, distance d'édition, trigrammes."""
import re
import unicodedata

FR_STOP = frozenset("""
a au aux avec ce ces cet cette dans de des du elle en et eux il ils je la le les leur lui ma mais me meme mes moi mon
ne nos notre nous on ou par pas pour qu que qui sa se ses son sur ta te tes toi ton tu un une vos votre vous c d j l m n s t y
est sont ete etre ont avoir fait comme plus ni si aussi donc car or
""".split())
_APOS = str.maketrans({'’': "'", '‘': "'", 'ʼ': "'", '`': "'", '´': "'"})
_LIGATURES = str.maketrans({'œ': 'oe', 'æ': 'ae', 'Œ': 'oe', 'Æ': 'ae'})
_WORD = re.compile(r'[^\W_]+')
_ELISION = re.compile(r"^(?:[ldmtsnjc]|qu|jusqu|lorsqu|puisqu)'(?=.)")


def fold(s, lig=True):
    """Minuscules, sans accents, apostrophes droites. lig=False laisse œ et æ tels quels, comme l'index FTS5
    (tokenize unicode61 ne les décompose pas) ; lig=True les écrit oe et ae."""
    if not s:
        return ''
    s = s.translate(_APOS)
    if lig:
        s = s.translate(_LIGATURES)
    s = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()


def tokens(s, lig=True):
    """Mots (lettres et chiffres) du texte replié, comme le découpage de l'index FTS5."""
    return _WORD.findall(fold(s, lig))


def strip_elision(w):
    """« l'aquifère » -> « aquifère », « qu'il » -> « il »."""
    return _ELISION.sub('', w)


_SUFFIXES = sorted("""
issements issement atrices atrice ateurs ateur ations ation ements ement ologies ologie ques que ismes isme istes iste
ables able ibles ible eux euse euses ives ive ifs if ités ité aux al es s x e
""".split(), key=len, reverse=True)


def stem(w):
    """Racine légère (le mot est déjà replié) : géothermie, géothermique, géothermiques -> geothermi."""
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len(suf)]
    return w


def trigrams(t):
    """Ensemble des trigrammes de t (sans bourrage) : une faute de frappe en détruit au plus trois."""
    return {t[i:i + 3] for i in range(len(t) - 2)}


def osa(a, b, maxd=2):
    """Distance d'édition « optimal string alignment » (insertion, suppression, substitution, transposition).
    Renvoie maxd + 1 dès que la distance dépasse maxd."""
    if abs(len(a) - len(b)) > maxd:
        return maxd + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > maxd:
            return maxd + 1
        prev2, prev = prev, cur
    return min(prev[-1], maxd + 1)
