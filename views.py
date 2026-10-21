import functools
import json

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from frlib import BIBSET, SPECIAL

from . import search
from .audit import run_audit
from .bibfmt import bib_text
from .corpus import get_corpus
from .forms import PieceForm
from .models import Piece
from .render import render_markdown
from .similar import get_similarity

PER_PAGE = 40
MD_LIMIT = 40000
FACET_NAMES = search.FACETS + ['decade']


def writable(view):
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if settings.FR_READONLY:
            return HttpResponseForbidden('Mode consultation seule (FR_READONLY=1).')
        return view(request, *args, **kwargs)
    return wrapper


def _url(params, **changes):
    qd = params.copy()
    for k, v in changes.items():
        if v is None:
            qd.pop(k, None)
        else:
            qd[k] = v
    s = qd.urlencode()
    return '?' + s if s else '?'


def list_view(request):
    try:
        get_corpus()
    except DatabaseError as e:
        return render(request, 'pieces/setup.html', {'error': str(e), 'db': settings.DATABASES['default']['NAME']}, status=503)
    q = request.GET.get('q', '').strip()
    mode = 'fts' if request.GET.get('mode') == 'fts' else 'auto'
    broad = request.GET.get('broad') == '1'
    sort = request.GET.get('sort', 'rel')
    selected = {n: request.GET.getlist(n) for n in FACET_NAMES if request.GET.getlist(n)}
    out = search.search(q, mode=mode, facets=selected, sort=sort, broad=broad)
    page = Paginator(out.ranked, PER_PAGE).get_page(request.GET.get('page'))
    snips = search.snippets([d.n for d, _, _ in page], out.highlight)
    items = [{'doc': d, 'score': s, 'count': c, 'snippet': snips.get(d.n),
              'abstract': (d.v['abstract'] or '')[:260]} for d, s, c in page]
    params = request.GET.copy()
    params.pop('page', None)
    facets_ui, chips = [], []
    for f in out.facets:
        values = dict(f['values'])
        for v in selected.get(f['name'], []):
            values.setdefault(v, 0)
        ui = []
        for value, count in (f['values'] if f['name'] == 'decade' else sorted(values.items(), key=lambda x: (-x[1], x[0]))):
            active = value in selected.get(f['name'], [])
            qd = params.copy()
            vals = qd.getlist(f['name'])
            vals.remove(value) if active else vals.append(value)
            qd.setlist(f['name'], vals)
            ui.append({'value': value, 'count': count, 'active': active, 'url': '?' + qd.urlencode()})
            if active:
                chips.append({'label': f'{f["label"]} : {value}', 'url': '?' + qd.urlencode()})
        facets_ui.append({'label': f['label'], 'values': ui})
    return render(request, 'pieces/list.html', {
        'q': q, 'mode': mode, 'broad': broad, 'sort': out.sort if out.sort in dict(search.SORTS) else 'rel',
        'sorts': search.SORTS, 'out': out, 'interp': out.interp, 'page': page, 'items': items, 'total': len(out.ranked),
        'facets_ui': facets_ui, 'chips': chips, 'selected': selected,
        'hidden': [(n, v) for n, vs in selected.items() for v in vs],
        'broad_url': _url(request.GET, broad='1', page=None), 'clear_url': '?',
        'page_base': _url(request.GET, page=None) + ('&' if request.GET.urlencode().replace('page=', '') else ''),
    })


def detail(request, key):
    piece = get_object_or_404(Piece, key=key)
    entry = piece.to_entry()
    ov = entry.get('bibtex') or {}
    rows = []
    for name, base in entry.items():
        if name not in BIBSET:
            continue
        if name in ov:
            rows.append({'name': name, 'value': base if ov[name] is None else ov[name],
                         'base': None if ov[name] is None else base,
                         'origin': 'supprimé du .bib' if ov[name] is None else 'surcharge'})
        else:
            rows.append({'name': name, 'value': base, 'origin': 'base'})
    rows += [{'name': n, 'value': v, 'origin': 'bibtex seul'} for n, v in ov.items()
             if n not in BIBSET and n != 'ENTRYTYPE' and v is not None]
    extras = [{'name': k, 'value': json.dumps(v, ensure_ascii=False, indent=2) if isinstance(v, (dict, list)) else v}
              for k, v in entry.items() if k not in SPECIAL and k not in BIBSET]
    full = request.GET.get('full') == '1'
    body, truncated = render_markdown(piece.markdown, None if full else MD_LIMIT)
    try:
        similar = get_similarity().similar(piece.n, 8)
    except DatabaseError:
        similar = []
    return render(request, 'pieces/detail.html', {
        'piece': piece, 'entry': entry, 'rows': rows, 'extras': extras, 'body': body, 'truncated': truncated,
        'size': len(piece.markdown), 'bib': bib_text(entry), 'similar': similar,
        'raw': json.dumps({k: v for k, v in entry.items() if k != 'markdown'}, ensure_ascii=False, indent=2),
    })


@writable
def edit(request, key):
    piece = get_object_or_404(Piece, key=key)
    entry = piece.to_entry()
    if request.method == 'POST':
        form = PieceForm(request.POST)
        if form.is_valid():
            changed = piece.set_from_entry(form.build_entry(entry))
            if changed:
                piece.save(update_fields=changed)
                messages.success(request, 'Entrée enregistrée (modifié : ' + ', '.join(changed) + ').')
            else:
                messages.info(request, 'Aucun changement.')
            return redirect('detail', key=piece.key)
    else:
        form = PieceForm.from_entry(entry)
    return render(request, 'pieces/form.html', {'form': form, 'piece': piece, 'creating': False})


@writable
def create(request):
    if request.method == 'POST':
        form = PieceForm(request.POST, creating=True)
        if form.is_valid():
            piece = Piece.from_entry(form.build_entry(None))
            piece.save(force_insert=True)
            messages.success(request, 'Entrée créée.')
            return redirect('detail', key=piece.key)
    else:
        form = PieceForm(creating=True)
    return render(request, 'pieces/form.html', {'form': form, 'piece': None, 'creating': True})


@writable
def delete(request, key):
    piece = get_object_or_404(Piece, key=key)
    if request.method == 'POST':
        piece.delete()
        messages.success(request, f'Entrée {key} supprimée.')
        return redirect('list')
    return render(request, 'pieces/confirm_delete.html', {'piece': piece})


def export_json(request):
    """fr.json complet (même contenu et même mise en forme que db2json)."""
    data = {p.key: p.to_entry() for p in Piece.objects.order_by('n')}
    resp = HttpResponse(json.dumps(data, indent=2, ensure_ascii=False), content_type='application/json; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="fr.json"'
    return resp


def export_bib(request):
    """fr.bib « simple » (comme json2bib) ; pour un export sans perte vers la base, utilisez db2bib.sh."""
    text = '\n'.join(bib_text(p.to_entry()) for p in Piece.objects.order_by('n'))
    resp = HttpResponse(text, content_type='application/x-bibtex; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="fr.bib"'
    return resp


def piece_bib(request, key):
    piece = get_object_or_404(Piece, key=key)
    return HttpResponse(bib_text(piece.to_entry()), content_type='text/plain; charset=utf-8')


def audit_view(request):
    return render(request, 'pieces/audit.html', {'checks': run_audit()})


def duplicates_view(request):
    try:
        threshold = min(max(float(request.GET.get('seuil', '0.85')), 0.3), 0.99)
    except ValueError:
        threshold = 0.85
    return render(request, 'pieces/duplicates.html',
                  {'pairs': get_similarity().duplicates(threshold), 'threshold': threshold})
