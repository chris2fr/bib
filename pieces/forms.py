import json
import re

from django import forms
from frlib import BIB, BIBSET, SPECIAL, check_braces, put_field, set_bibtex, sort_fields

from . import dups, files, helpers
from .dates import check_date, check_time, check_timezone, is_full_date, make_datetime, timezones
from .models import Piece

LONG = {'abstract': 6, 'note': 3, 'annote': 3, 'keywords': 2, 'file': 2}
COMPUTED_FIELDS = ('year', 'xdatetime')      # calculés (date, heure, fuseau), jamais saisis
KEY_RE = re.compile(r'^[\w][\w.+:-]*$')
DATE_HELP = 'AAAA-MM-JJ ; MM et JJ valent 00 si inconnus (1997-05-00, 1997-00-00). L\'année est calculée à partir de la date.'
TIME_HELP = 'HH:MM (00:00 à 23:59). xdatetime est calculé : date complète + heure (+ fuseau, s\'il est choisi).'


def _nl(v):
    return v.replace('\r\n', '\n').replace('\r', '\n') if isinstance(v, str) else v


class PieceForm(forms.Form):
    """Édition d'une entrée du fr.json « remonté » : champs BibTeX (valeurs de base), autres champs (JSON),
    surcharges du .bib (JSON) et markdown."""

    def __init__(self, *args, creating=False, current_key=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.creating = creating
        self.current_key = current_key            # clé actuelle de l'entrée éditée (None à la création)
        self.shorthand_synced = False
        self.file_names = files.names()
        self.xdup_candidates = []                 # (clé, titre) proposés pour xdup, fournis par la vue
        self.multi_values = {f: helpers.choices(f) for f in helpers.MULTI_FIELDS}
        self.fields['key'] = forms.CharField(
            label='Clé (ID)', strip=True,
            help_text='Identifiant de citation, aussi utilisé dans le .bib. Forme habituelle : AAAA-MM-JJ-acronyme-compteur. '
                      + ('' if creating else 'Si vous la modifiez, shorthand suit (sauf si vous l\'avez personnalisé).'))
        self.fields['entrytype'] = forms.CharField(label='ENTRYTYPE', initial='misc', strip=True)
        self._helper('entrytype', required=True)
        for f in sort_fields(BIB, 'bibtex'):            # ordre universel (paramètre BIBMAN_ORDER_BIBTEX, sinon alphabétique)
            if f in COMPUTED_FIELDS:          # calculés à partir de la date, de l'heure et du fuseau (voir build_entry)
                continue
            widget = forms.Textarea(attrs={'rows': LONG[f]}) if f in LONG else forms.TextInput()
            if f == 'date':
                widget = forms.TextInput(attrs={'placeholder': 'AAAA-MM-JJ', 'maxlength': 10, 'inputmode': 'numeric',
                                                'pattern': r'\d{4}-\d{2}-\d{2}', 'title': 'AAAA-MM-JJ, MM et JJ peuvent valoir 00'})
            if f in helpers.MULTI_FIELDS:         # complétion pendant la frappe (multi.js)
                widget = forms.Textarea(attrs={'rows': LONG.get(f, 2), 'data-multi': f, 'autocomplete': 'off'})
            if f == 'xdup':
                widget = forms.TextInput(attrs={'list': 'xdup-list', 'autocomplete': 'off', 'placeholder': 'clé de l\'entrée de référence'})
            if f == 'file':
                widget = forms.TextInput(attrs={'list': 'files-list', 'autocomplete': 'off', 'placeholder': 'par défaut : <clé>.pdf'})
            if f == 'xtime':
                widget = forms.TextInput(attrs={'placeholder': 'HH:MM', 'maxlength': 5, 'inputmode': 'numeric',
                                                'pattern': r'([01]\d|2[0-3]):[0-5]\d', 'title': 'HH:MM, de 00:00 à 23:59'})
            if f == 'xtimezone':
                widget = self._zone_widget()
            self.fields[f] = forms.CharField(label=f, required=False, strip=False, widget=widget,
                                             help_text={'date': DATE_HELP, 'xtime': TIME_HELP,
                                                        'xtimezone': 'Facultatif ; vide = heure sans fuseau.',
                        'xdup': 'Clé d\'une autre entrée dont celle-ci est le doublon (gardé car cité par d\'anciens documents). Vide : pas un doublon.',
                        'file': 'Nom du fichier dans BIBMAN_FILES, sans dossier. Vide : <clé>.pdf.',
                        'keywords': 'Séparés par une virgule et une espace (« mot, mot ») ; les mots-clés déjà connus sont proposés pendant la frappe.'}.get(f, ''))
            if f in helpers.HELPER_FIELDS:
                self._helper(f)
        self.fields['extra_json'] = forms.CharField(
            label='Autres champs (JSON)', required=False, strip=False, initial='{}',
            widget=forms.Textarea(attrs={'rows': 8, 'class': 'mono'}),
            help_text='Objet JSON des champs sans équivalent BibTeX (piece_fond, remarque, avis...).')
        self.fields['bibtex_json'] = forms.CharField(
            label='Surcharges du .bib (JSON)', required=False, strip=False,
            widget=forms.Textarea(attrs={'rows': 5, 'class': 'mono'}),
            help_text='Objet JSON {champ: valeur}. La valeur remplace celle de base dans le .bib ; null supprime le champ du .bib.')
        self.fields['markdown'] = forms.CharField(
            label='Markdown', required=False, strip=False,
            widget=forms.Textarea(attrs={'rows': 24, 'class': 'mono'}))

    def _zone_widget(self):
        zones = timezones()
        current = self.data.get('xtimezone') if self.is_bound else self.initial.get('xtimezone')
        if current and current not in zones:
            zones = [*zones, current]              # valeur héritée inconnue : conservée, signalée à l'enregistrement
        return forms.Select(choices=[('', '—')] + [(z, z) for z in zones])

    def _helper(self, name, required=False):
        """Champ à liste déroulante (table helper_values) suivi d'un champ « nouvelle valeur » qui l'emporte s'il est rempli."""
        values = helpers.choices(name)
        current = self.data.get(name) if self.is_bound else self.initial.get(name, self.fields[name].initial)
        if current and current not in values:
            values.append(current)            # valeur déjà utilisée mais absente de la liste : on la garde sélectionnée
        blank = [] if required else [('', '—')]
        field = self.fields[name]
        field.widget = forms.Select(choices=blank + [(v, v) for v in values])
        field.strip = False
        self.fields[name + '_new'] = forms.CharField(
            label=f'{name} : nouvelle valeur', required=False, strip=True,
            help_text='Si ce champ est rempli, il remplace le choix de la liste ci-dessus et la valeur est ajoutée à la liste.')

    @classmethod
    def from_entry(cls, entry, **kw):
        initial = {'key': entry['key'], 'entrytype': entry.get('ENTRYTYPE', 'misc'), 'markdown': entry.get('markdown', ''),
                   'extra_json': json.dumps({k: v for k, v in entry.items() if k not in SPECIAL and k not in BIBSET},
                                            ensure_ascii=False, indent=2),
                   'bibtex_json': json.dumps(entry['bibtex'], ensure_ascii=False, indent=2) if entry.get('bibtex') else ''}
        initial.update({f: entry[f] for f in BIB if f in entry and f not in COMPUTED_FIELDS})
        return cls(initial=initial, **kw)

    def clean_date(self):
        date = (self.cleaned_data.get('date') or '').strip()
        error = check_date(date) if date else None
        if error:
            raise forms.ValidationError(error)
        return date

    def clean_file(self):
        value = (self.cleaned_data.get('file') or '').strip()
        if value and not files.safe_name(value):
            raise forms.ValidationError('Nom de fichier seul, sans dossier (ni / ni \\) : le dossier est BIBMAN_FILES.')
        return value

    def clean_xdup(self):
        value = (self.cleaned_data.get('xdup') or '').strip()
        error = dups.xdup_error(self.cleaned_data.get('key') or self.current_key, value, self.current_key) if value else None
        if error:
            raise forms.ValidationError(error)
        return value

    def clean_xtime(self):
        value = (self.cleaned_data.get('xtime') or '').strip()
        error = check_time(value) if value else None
        if error:
            raise forms.ValidationError(error)
        return value

    def clean_xtimezone(self):
        value = (self.cleaned_data.get('xtimezone') or '').strip()
        error = check_timezone(value) if value else None
        if error:
            raise forms.ValidationError(error)
        return value

    def clean_key(self):
        key = self.cleaned_data['key']
        if not KEY_RE.match(key):
            raise forms.ValidationError('Clé invalide (lettres, chiffres, - _ . + : ; pas d\'espace ni de /).')
        if Piece.objects.filter(key=key).exclude(key=self.current_key).exists():
            raise forms.ValidationError('Cette clé existe déjà.')
        return key

    def clean(self):
        cd = super().clean()
        key = cd.get('key', '(nouvelle entrée)')
        if cd.get('xtime') and 'date' not in self.errors and not is_full_date(cd.get('date') or ''):
            self.add_error('xtime', 'Une heure exige une date complète (AAAA-MM-JJ sans 00).')
        for f in helpers.HELPER_FIELDS:
            if (cd.get(f + '_new') or '').strip():
                cd[f] = cd[f + '_new'].strip()
        for f in ['markdown', *BIB]:
            if f in cd:
                cd[f] = _nl(cd[f])
        for f in BIB:
            if cd.get(f):
                try:
                    check_braces(key, f, cd[f])
                except ValueError:
                    self.add_error(f, 'Accolades { } déséquilibrées : valeur impossible à écrire dans le .bib.')
        for name, label in (('extra_json', 'Autres champs'), ('bibtex_json', 'Surcharges')):
            raw = (cd.get(name) or '').strip()
            try:
                val = json.loads(raw) if raw else {}
            except ValueError as e:
                self.add_error(name, f'JSON invalide : {e}')
                continue
            if not isinstance(val, dict):
                self.add_error(name, f'{label} : un objet JSON {{...}} est attendu.')
                continue
            if name == 'extra_json':
                bad = [k for k in val if k in SPECIAL or k in BIBSET or k == 'ID']
                if bad:
                    self.add_error(name, 'Champs réservés (à saisir ailleurs ou à retirer) : ' + ', '.join(bad))
                cd['extra'] = val
            else:
                bad = [k for k, v in val.items() if v is not None and not isinstance(v, str)]
                if bad:
                    self.add_error(name, 'Les valeurs doivent être du texte ou null : ' + ', '.join(bad))
                for k, v in val.items():
                    if isinstance(v, str):
                        try:
                            check_braces(key, k, v)
                        except ValueError:
                            self.add_error(name, f'{k} : accolades déséquilibrées.')
                cd['overrides'] = val
        return cd

    def build_entry(self, old=None):
        """Entrée fr.json résultant du formulaire; l'ordre des champs existants est conservé."""
        cd = self.cleaned_data
        entry = dict(old) if old else {'key': cd['key']}
        entry['key'] = cd['key']
        put_field(entry, 'ENTRYTYPE', cd['entrytype'])
        for f in BIB:
            v = cd.get(f)
            if f == 'year':
                if cd.get('date'):
                    v = cd['date'][:4]
                elif old and old.get('date'):
                    v = None                  # date effacée : l'année calculée disparaît avec elle
                else:
                    continue                  # pas de date : année héritée, laissée telle quelle
            elif f == 'xdatetime':
                new = make_datetime(cd.get('date'), cd.get('xtime'), cd.get('xtimezone'))
                if new:
                    v = new
                elif old and old.get('date') and old.get('xtime'):
                    v = None                  # date ou heure effacée : xdatetime calculé disparaît
                else:
                    continue                  # rien à calculer : valeur héritée laissée telle quelle
            elif f == 'keywords' and v:
                # liste « mot, mot » : réécrite avec virgule et espace seulement si les mots ont changé
                if old and helpers.split_multi(v) == helpers.split_multi(old.get('keywords')):
                    v = old.get('keywords')
                else:
                    v = ', '.join(helpers.split_multi(v))
            if not v:
                entry.pop(f, None)
            elif entry.get(f) != v:
                put_field(entry, f, v)
        if old and cd['key'] != old['key']:
            # clé renommée : shorthand (= clé par défaut) suit, sauf s'il a été personnalisé ou modifié dans ce formulaire
            before = old.get('shorthand') or ''
            if (cd.get('shorthand') or '') == before and before in ('', old['key']):
                put_field(entry, 'shorthand', cd['key'])
                self.shorthand_synced = True
        new_extra = cd['extra']
        for k in [k for k in entry if k not in SPECIAL and k not in BIBSET and k not in new_extra]:
            del entry[k]
        for k, v in new_extra.items():
            put_field(entry, k, v)
        if 'markdown' in entry or cd['markdown'] or not old:
            entry['markdown'] = cd['markdown']
        set_bibtex(entry, cd['overrides'])
        return entry


_TERM = re.compile(r'"[^"]*"|\S+')
HAS_FIELDS = [('url', 'adresse (url)'), ('file', 'fichier'), ('note', 'note'), ('abstract', 'résumé'), ('keywords', 'mots-clés'),
              ('override', 'surcharges du .bib')]


class AdvancedSearchForm(forms.Form):
    """Recherche avancée : les champs sont traduits en requête de la syntaxe habituelle (voir l'aide), affichée ensuite
    dans la barre de recherche."""
    all = forms.CharField(label='Tous ces mots', required=False)
    phrase = forms.CharField(label='Cette expression exacte', required=False)
    exclude = forms.CharField(label='Aucun de ces mots', required=False)
    title = forms.CharField(label='Dans le titre', required=False)
    author = forms.CharField(label='Auteur', required=False)
    organization = forms.CharField(label='Organisation', required=False)
    keywords = forms.CharField(label='Mot-clé', required=False)
    year_from = forms.IntegerField(label='Année : de', required=False, min_value=1, max_value=9999)
    year_to = forms.IntegerField(label='à', required=False, min_value=1, max_value=9999)
    date_from = forms.CharField(label='Date : du', required=False, max_length=10,
                                widget=forms.TextInput(attrs={'placeholder': 'AAAA-MM-JJ', 'maxlength': 10}),
                                help_text='AAAA, AAAA-MM ou AAAA-MM-JJ ; une date partielle couvre toute sa période.')
    date_to = forms.CharField(label='au', required=False, max_length=10, widget=forms.TextInput(attrs={'placeholder': 'AAAA-MM-JJ', 'maxlength': 10}))
    sort = forms.ChoiceField(label='Tri', required=False, choices=[])

    # liste déroulante (champ de recherche, étiquette, requête de la forme champ:valeur)
    SELECTS = [('entrytype', 'ENTRYTYPE', 'entrytype'), ('xtheme', 'Thème', 'theme'), ('type', 'Nature', 'nature'),
               ('xacronym', 'Source', 'acr'), ('language', 'Langue', 'lang')]

    def __init__(self, *args, choices=None, sorts=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = choices or {}
        self.fields['sort'].choices = [('', 'Pertinence')] + [(v, label) for v, label in sorts if v != 'rel']
        for name, label, _ in self.SELECTS:
            self.fields[name] = forms.ChoiceField(label=label, required=False, choices=[('', '—')] + [(v, v) for v in choices.get(name, [])])
        for name, label in HAS_FIELDS:
            self.fields['has_' + name] = forms.ChoiceField(
                label=label, required=False, choices=[('', '—'), ('has', 'avec'), ('no', 'sans')])
        self.order = ['all', 'phrase', 'exclude', 'title', 'author', 'organization', 'keywords',
                      *[n for n, _, _ in self.SELECTS], 'year_from', 'year_to', 'date_from', 'date_to',
                      *['has_' + n for n, _ in HAS_FIELDS], 'sort']
        self.fields = {n: self.fields[n] for n in self.order}

    def clean(self):
        cd = super().clean()
        for f in ('date_from', 'date_to'):
            v = (cd.get(f) or '').strip()
            if v and not re.fullmatch(r'\d{4}(-\d{2}(-\d{2})?)?', v):
                self.add_error(f, 'Format attendu : AAAA, AAAA-MM ou AAAA-MM-JJ.')
            elif v:
                from .search import _span
                if not _span(v):
                    self.add_error(f, 'Date invalide.')
        a, b = cd.get('year_from'), cd.get('year_to')
        if a and b and a > b:
            self.add_error('year_to', "L'année de fin précède celle de début.")
        return cd

    def build_query(self):
        """Requête (syntaxe de la barre de recherche) équivalente aux champs remplis."""
        cd = self.cleaned_data
        parts = []
        if cd.get('all'):
            parts.append(cd['all'].strip())
        if cd.get('phrase'):
            parts.append('"%s"' % cd['phrase'].replace('"', ' ').strip())
        parts += ['-' + t.lstrip('-') for t in _TERM.findall(cd.get('exclude') or '') if t.lstrip('-')]

        def value(v):
            v = v.replace('"', ' ').strip()
            return f'"{v}"' if re.search(r'\s', v) else v
        for name, key in (('title', 'titre'), ('author', 'auteur'), ('organization', 'org'), ('keywords', 'kw')):
            if cd.get(name):
                parts.append(f'{key}:{value(cd[name])}')
        for name, _, key in self.SELECTS:
            if cd.get(name):
                parts.append(f'{key}:{value(cd[name])}')
        a, b = cd.get('year_from'), cd.get('year_to')
        if a and b:
            parts.append(f'year:{a}..{b}')
        elif a:
            parts.append(f'year:>={a}')
        elif b:
            parts.append(f'year:<={b}')
        lo, hi = (cd.get('date_from') or '').strip(), (cd.get('date_to') or '').strip()
        if lo or hi:
            parts.append(f'date:{lo}..{hi}')
        for name, _ in HAS_FIELDS:
            if cd.get('has_' + name):
                parts.append(f'{cd["has_" + name]}:{name}')
        return ' '.join(parts)
