"""Markdown -> HTML assaini (nh3). Les commentaires « <!-- Page N --> » deviennent des séparateurs de page."""
import re

import markdown
import nh3
from django.utils.safestring import mark_safe

_PAGE = re.compile(r'<!--\s*Page\s+(\d+)\s*-->', re.I)
_MARK = re.compile(r'<p>BIBMANPAGE(\d+)END</p>')


def render_markdown(text, limit=None):
    """(html sûr, tronqué?) ; limit = nombre maximal de caractères de markdown rendus (None = tout)."""
    text = text or ''
    truncated = bool(limit) and len(text) > limit
    if truncated:
        cut = text.rfind('\n', 0, limit)
        text = text[:cut if cut > limit // 2 else limit]
    text = _PAGE.sub(lambda m: f'\n\nBIBMANPAGE{m[1]}END\n\n', text)
    html = nh3.clean(markdown.markdown(text, extensions=['tables', 'fenced_code', 'sane_lists']))
    html = _MARK.sub(lambda m: f'<div class="page"><span>page {m[1]}</span></div>', html)
    return mark_safe(html), truncated
