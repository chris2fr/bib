import functools
import json
import mimetypes
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from frlib import BIBSET, SPECIAL, set_bibtex, sort_fields

from . import dups, files, helpers, search
from .audit import run_audit
from .bibfmt import bib_text
from .corpus import bump, get_corpus
from .forms import COMPUTED_FIELDS, AdvancedSearchForm, PieceForm
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
    du, au = request.GET.get('du', '').strip(), request.GET.get('au', '').strip()
    selected = {n: request.GET.getlist(n) for n in FACET_NAMES if request.GET.getlist(n)}
    out = search.search(q, mode=mode, facets=selected, sort=sort, broad=broad, date_from=du, date_to=au)
    page = Paginator(out.ranked, PER_PAGE).get_page(request.GET.get('page'))
    snips = search.snippets([d.n for d, _, _ in page], out.highlight)
    items = [{'doc': d, 'score': s, 'count': c, 'snippet': snips.get(d.n),
              'abstract': (d.v['abstract'] or '')[:260], 'has_file': bool(files.locate(d.key, d.v['file']))} for d, s, c in page]
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
        'q': q, 'du': du, 'au': au, 'mode': mode, 'broad': broad, 'sort': out.sort if out.sort in dict(search.SORTS) else 'rel',
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
                         'base': None if ov[name] is None else base, 'has_ov': True, 'to_base': name not in COMPUTED_FIELDS,
                         'origin': 'supprimé du .bib' if ov[name] is None else 'surcharge'})
        else:
            rows.append({'name': name, 'value': base, 'origin': 'base'})
    shown = {r['name'] for r in rows}
    rows += [{'name': n, 'value': ov[n], 'has_ov': True, 'to_base': n in BIBSET and n not in COMPUTED_FIELDS,
              'origin': 'surcharge, sans valeur de base' if n in BIBSET else 'bibtex seul'}
             for n in sort_fields([n for n, v in ov.items() if n not in shown and n != 'ENTRYTYPE' and v is not None], 'bibtex')]
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
        'has_ov': any(r.get('has_ov') for r in rows), 'size': len(piece.markdown), 'source': source_info(piece), 'dup_refs': dups.referrers(piece.key),
        'dup_of': Piece.objects.filter(key=piece.xdup).values('key', 'title').first() if piece.xdup else None, 'bib': bib_text(entry), 'similar': similar,
        'raw': json.dumps({k: v for k, v in entry.items() if k != 'markdown'}, ensure_ascii=False, indent=2),
    })


def source_info(piece):
    """Fichier source pour la fiche : trouvé (lien), introuvable dans le dossier, ou dossier absent."""
    loc = files.locate(piece.key, piece.file)
    if loc:
        return {'state': 'found', 'name': loc.name, 'via': loc.via, 'url': reverse('source_file', args=[piece.key])}
    return {'state': 'missing' if files.folder().is_dir() else 'nofolder', 'name': files.expected_name(piece.key, piece.file),
            'folder': files.folder()}


INLINE = ('application/pdf', 'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'text/plain')


def source_file(request, key):
    """Sert le fichier source (PDF affiché dans le navigateur ; les autres types sont téléchargés)."""
    piece = get_object_or_404(Piece, key=key)
    loc = files.locate(piece.key, piece.file)
    if not loc:
        raise Http404('Fichier source introuvable')
    ctype = mimetypes.guess_type(loc.name)[0] or 'application/octet-stream'
    return FileResponse(open(loc.path, 'rb'), content_type=ctype, filename=loc.name,
                        as_attachment=ctype not in INLINE or request.GET.get('download') == '1')


def warn_if_file_missing(request, piece):
    if piece.file and files.folder().is_dir() and not files.locate(piece.key, piece.file):
        messages.warning(request, f'Fichier « {piece.file} » introuvable dans le dossier BIBMAN_FILES.')


def dup_candidates(piece):
    """[(clé, titre)] des entrées proches de piece (texte ou titre), proposées pour xdup."""
    if piece is None:
        return []
    try:
        close = [d for d, _ in get_similarity().similar(piece.n, 10, 0.05)]
    except DatabaseError:
        close = []
    return [(d.key, d.title) for d in close]


@writable
def edit(request, key):
    piece = get_object_or_404(Piece, key=key)
    entry = piece.to_entry()
    if request.method == 'POST':
        form = PieceForm(request.POST, current_key=key)
        if form.is_valid():
            changed = piece.set_from_entry(form.build_entry(entry))
            if changed:
                piece.save(update_fields=changed)
                helpers.remember(piece)
                if 'key' in changed:                                  # les doublons déclarés suivent la clé renommée
                    Piece.objects.filter(xdup=key).update(xdup=piece.key)
                    bump()
                msg = 'Entrée enregistrée (modifié : ' + ', '.join(changed) + ').'
                if 'key' in changed:
                    msg += f' Clé renommée : {key} → {piece.key}.' + (' shorthand mis à jour.' if form.shorthand_synced else '')
                messages.success(request, msg)
                warn_if_file_missing(request, piece)
            else:
                messages.info(request, 'Aucun changement.')
            return redirect('detail', key=piece.key)
    else:
        form = PieceForm.from_entry(entry, current_key=key)
    form.xdup_candidates = dup_candidates(piece)
    return render(request, 'pieces/form.html', {'form': form, 'piece': piece, 'creating': False})


@writable
def override_move(request, key):
    """POST field (nom ou *) et action : bib2base (la surcharge du .bib devient la valeur de base, puis disparaît)
    ou base2bib (la valeur de base est gardée, la surcharge disparaît)."""
    piece = get_object_or_404(Piece, key=key)
    entry = piece.to_entry()
    ov = dict(entry.get('bibtex') or {})
    action, field = request.POST.get('action'), request.POST.get('field', '')
    names = list(ov) if field == '*' else [field]
    if request.method != 'POST' or action not in ('bib2base', 'base2bib') or not ov or any(n not in ov for n in names):
        messages.error(request, 'Rien à faire : surcharge introuvable.')
        return redirect('detail', key=key)
    label = 'toutes les surcharges' if field == '*' else f'la surcharge de « {field} »'
    new = dict(entry)
    if action == 'bib2base':
        movable = [n for n in names if n in BIBSET and n not in COMPUTED_FIELDS]
        if field != '*' and not movable:
            messages.error(request, f'« {field} » n\'a pas de valeur de base à remplacer (champ calculé ou propre au .bib) ; utilisez base2bib.')
            return redirect('detail', key=key)
        for n in movable:                                    # null supprimait le champ du .bib : il disparaît aussi de la base
            value = ov.pop(n)
            if value is None:
                new.pop(n, None)
            else:
                new[n] = value
        if field == '*':
            ov = {n: v for n, v in ov.items() if n not in movable}      # les surcharges non déplaçables restent
        set_bibtex(new, ov)
        # la nouvelle valeur de base passe par les mêmes contrôles que le formulaire (date, heure, fichier, xdup...)
        form = PieceForm({k: v for k, v in PieceForm.from_entry(new, current_key=key).initial.items()}, current_key=key)
        if not form.is_valid():
            messages.error(request, 'Valeur refusée : ' + ' ; '.join(f'{f} : {" ".join(e)}' for f, e in form.errors.items()))
            return redirect('detail', key=key)
        new = form.build_entry(entry)
        verb = f'{label} appliquée à la base'
    else:
        if field == '*':
            ov = {}
        else:
            ov.pop(field)
        set_bibtex(new, ov)
        verb = f'{label} supprimée (valeur de base gardée)'
    changed = piece.set_from_entry(new)
    if changed:
        piece.save(update_fields=changed)
        helpers.remember(piece)
    messages.success(request, verb[0].upper() + verb[1:] + '.')
    return redirect('detail', key=key)


@writable
def create(request):
    if request.method == 'POST':
        form = PieceForm(request.POST, creating=True)
        if form.is_valid():
            piece = Piece.from_entry(form.build_entry(None))
            piece.save(force_insert=True)
            helpers.remember(piece)
            messages.success(request, 'Entrée créée.')
            warn_if_file_missing(request, piece)
            return redirect('detail', key=piece.key)
    else:
        form = PieceForm(creating=True)
    return render(request, 'pieces/form.html', {'form': form, 'piece': None, 'creating': True})


@writable
def delete(request, key):
    piece = get_object_or_404(Piece, key=key)
    refs = dups.referrers(key)
    if refs:
        messages.error(request, 'Suppression impossible : déclarée comme référence de doublons (' + ', '.join(k for k, _ in refs)
                       + '). Retirez d\'abord leur champ xdup.')
        return redirect('detail', key=key)
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
    docs = get_corpus()
    declared = [(d, docs.by_key.get(d.v['xdup']), d.v['xdup']) for d in docs.docs if d.v.get('xdup')]
    return render(request, 'pieces/duplicates.html',
                  {'pairs': get_similarity().duplicates(threshold), 'threshold': threshold, 'declared': declared})


@writable
def declare_duplicate(request):
    """POST key, of : déclare l'entrée key doublon de l'entrée of (champ xdup)."""
    if request.method != 'POST':
        return redirect('duplicates')
    piece = get_object_or_404(Piece, key=request.POST.get('key', ''))
    target = request.POST.get('of', '').strip()
    error = dups.xdup_error(piece.key, target, piece.key)
    if error:
        messages.error(request, error)
    else:
        piece.xdup = target
        piece.save(update_fields=['xdup'])
        messages.success(request, f'{piece.key} déclaré doublon de {target}.')
    return redirect('duplicates')


@writable
def clear_duplicate(request, key):
    piece = get_object_or_404(Piece, key=key)
    if request.method == 'POST' and piece.xdup:
        messages.success(request, f'{key} n\'est plus déclaré doublon de {piece.xdup}.')
        piece.xdup = None
        piece.save(update_fields=['xdup'])
    return redirect('duplicates')


def advanced_search(request):
    """Formulaire de recherche avancée : traduit les champs en requête et renvoie à la liste de résultats."""
    try:
        docs = get_corpus().docs
    except DatabaseError as e:
        return render(request, 'pieces/setup.html', {'error': str(e), 'db': settings.DATABASES['default']['NAME']}, status=503)
    choices = {name: sorted({v for d in docs for v in d.values(name)}, key=lambda v: (v.lower(), v))
               for name, _, _ in AdvancedSearchForm.SELECTS}
    form = AdvancedSearchForm(request.GET or None, choices=choices, sorts=search.SORTS)
    if request.GET and form.is_valid():
        params = {}
        query = form.build_query()
        if query:
            params['q'] = query
        if form.cleaned_data.get('sort'):
            params['sort'] = form.cleaned_data['sort']
        return redirect(reverse('list') + ('?' + urlencode(params) if params else ''))
    return render(request, 'pieces/advanced.html', {'form': form})


HELP = [
    {'title': 'Mots', 'intro': "Tous les mots doivent être présents (ET). Accents et majuscules sont ignorés ; les mots vides (le, de, du…) sont ignorés dès qu'il reste d'autres mots.",
     'examples': [('géothermie dogger corrosion', 'trois mots'), ('"nappe du dogger"', 'expression exacte'),
                  ('dogger -corrosion', 'exclure un mot'), ('géotherm*', 'début de mot')]},
    {'title': 'Années', 'intro': "Une année seule filtre sur l'année de l'entrée (champ year, calculé à partir de la date).",
     'examples': [('1997', 'une année'), ('entre 1990 et 2000', 'période, bornes comprises'), ('de 1990 à 2000', 'idem'), ('1990..2000', 'idem'),
                  ('avant 2010', "jusqu'en 2009"), ('depuis 2015', "à partir de 2015"), ('après 2015', 'à partir de 2016'), ('year:1990..2000', 'filtre explicite'), ('year:>2000', 'après 2000')]},
    {'title': 'Plages de dates précises', 'intro': "Les dates s'écrivent AAAA-MM-JJ ou en toutes lettres (8 avril 2014, mai 1997). Une date partielle (jour ou mois à 00 dans la fiche) vaut toute sa période : "
     "1997-05-00 est « mai 1997 ». Une entrée correspond si sa date chevauche la plage demandée ; sans date, c'est l'année qui sert.",
     'examples': [('entre 1997-05-12 et 1998-03-01', 'du 12 mai 1997 au 1er mars 1998'), ('du 8 avril 2014 au 3 juin 2015', 'en toutes lettres'),
                  ('entre mai 1997 et mars 1998', 'de mai 1997 (début) à mars 1998 (fin)'), ('date:1997-05-12..1998-03-01', 'forme avec champ'),
                  ('date:1997-05..1997-09', 'de mai à septembre 1997'), ('date:1997-05-12..', "à partir d'un jour (borne ouverte)"), ('date:..1999-06', "jusqu'à fin juin 1999"),
                  ('date:>=2014-04-08', 'à partir du 8 avril 2014'), ('date:<2000-01-01', 'avant le 1er janvier 2000'),
                  ('avant 8 avril 2014', 'strictement avant'), ('après 8 avril 2014', 'strictement après'), ('depuis mai 1997', 'à partir du 1er mai 1997')]},
    {'title': 'Une date précise ou un mois', 'intro': "Une date seule filtre les entrées dont la date commence par elle.",
     'examples': [('8 avril 2014', 'ce jour'), ('mai 1997', 'ce mois'), ('2014-04-08', 'idem, forme ISO'), ('date:1997-05', 'idem avec champ')]},
    {'title': 'Champs', 'intro': "champ:valeur (guillemets si la valeur contient des espaces ; - devant pour exclure). Les listes (theme, type, org…) acceptent plusieurs valeurs séparées par des virgules.",
     'examples': [('theme:dogger', 'thème'), ('nature:email', 'nature (champ type) ; type:email est équivalent'), ('org:brgm', 'organisation'), ('auteur:dupont', 'auteur'), ('titre:"réseau de chaleur"', 'dans le titre'),
                  ('lang:fr', 'langue'), ('acr:brgmfr', 'source (acronyme)'), ('-theme:dogger', 'tout sauf ce thème')]},
    {'title': 'Présence', 'intro': 'has: / no: (ou sans:) testent la présence d’un champ.',
     'examples': [('has:url', 'avec une adresse'), ('no:note', 'sans note'), ('has:override', 'avec surcharges du .bib'), ('has:xdup', 'doublons déclarés'), ('no:xdup', 'hors doublons déclarés'), ('xdup:2015-00-00-sigesfr-dogger', 'doublons de cette entrée')]},
    {'title': 'Clés et identifiants', 'intro': "La clé de citation (ou un fragment) et les identifiants se cherchent tels quels : clé, number, xcounter, shorthand, file, url, note.",
     'examples': [('brgmfr-39522', 'clé ou fragment de clé'), ('39522', 'identifiant'), ('R39522', 'identifiant, espaces et tirets ignorés')]},
    {'title': 'FTS5 brut', 'intro': "Case « FTS5 brut » : la requête est transmise telle quelle à SQLite FTS5 (AND, OR, NOT, NEAR, colonne:mot). Les filtres de dates et les facettes restent utilisables par les champs « du / au » et les facettes.",
     'examples': [('dogger NEAR(corrosion tubage, 10)', 'proximité'), ('title:dogger NOT corrosion', 'colonne et exclusion')]},
]


def help_view(request):
    return render(request, 'pieces/help.html', {'sections': HELP})
