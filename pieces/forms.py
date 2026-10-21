import calendar
import json
import re

from django import forms
from frlib import BIB, BIBSET, SPECIAL, check_braces, put_field, set_bibtex

from . import helpers
from .models import Piece

LONG = {'abstract': 6, 'note': 3, 'annote': 3, 'keywords': 2, 'file': 2}
KEY_RE = re.compile(r'^[\w][\w.+:-]*$')
DATE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
DATE_HELP = 'AAAA-MM-JJ ; MM et JJ valent 00 si inconnus (1997-05-00, 1997-00-00). L\'année est calculée à partir de la date.'


def check_date(value):
    """Message d'erreur si value n'est pas une date ISO AAAA-MM-JJ (MM ou JJ éventuellement 00), sinon None."""
    m = DATE_RE.match(value)
    if not m:
        return 'Format attendu : AAAA-MM-JJ (MM et JJ peuvent valoir 00).'
    y, mo, d = map(int, m.groups())
    if y < 1:
        return 'Année invalide.'
    if mo > 12:
        return 'Mois invalide (00 à 12).'
    if mo == 0 and d:
        return 'Un mois 00 impose un jour 00.'
    if d and d > calendar.monthrange(y, mo)[1]:
        return f'Jour invalide : {y:04d}-{mo:02d} n\'a pas {d} jours.'
    return None


def _nl(v):
    return v.replace('\r\n', '\n').replace('\r', '\n') if isinstance(v, str) else v


class PieceForm(forms.Form):
    """Édition d'une entrée du fr.json « remonté » : champs BibTeX (valeurs de base), autres champs (JSON),
    surcharges du .bib (JSON) et markdown."""

    def __init__(self, *args, creating=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.creating = creating
        if creating:
            self.fields['key'] = forms.CharField(label='Clé de citation', strip=True,
                                                 help_text='Forme habituelle : AAAA-MM-JJ-acronyme-compteur. Non modifiable ensuite.')
        self.fields['entrytype'] = forms.CharField(label='ENTRYTYPE', initial='misc', strip=True)
        self._helper('entrytype', required=True)
        for f in BIB:
            if f == 'year':                   # calculée à partir de la date (voir build_entry)
                continue
            widget = forms.Textarea(attrs={'rows': LONG[f]}) if f in LONG else forms.TextInput()
            if f == 'date':
                widget = forms.TextInput(attrs={'placeholder': 'AAAA-MM-JJ', 'maxlength': 10, 'inputmode': 'numeric',
                                                'pattern': r'\d{4}-\d{2}-\d{2}', 'title': 'AAAA-MM-JJ, MM et JJ peuvent valoir 00'})
            self.fields[f] = forms.CharField(label=f, required=False, strip=False, widget=widget,
                                             help_text=DATE_HELP if f == 'date' else '')
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
        initial = {'entrytype': entry.get('ENTRYTYPE', 'misc'), 'markdown': entry.get('markdown', ''),
                   'extra_json': json.dumps({k: v for k, v in entry.items() if k not in SPECIAL and k not in BIBSET},
                                            ensure_ascii=False, indent=2),
                   'bibtex_json': json.dumps(entry['bibtex'], ensure_ascii=False, indent=2) if entry.get('bibtex') else ''}
        initial.update({f: entry[f] for f in BIB if f in entry and f != 'year'})
        return cls(initial=initial, **kw)

    def clean_date(self):
        date = (self.cleaned_data.get('date') or '').strip()
        error = check_date(date) if date else None
        if error:
            raise forms.ValidationError(error)
        return date

    def clean_key(self):
        key = self.cleaned_data['key']
        if not KEY_RE.match(key):
            raise forms.ValidationError('Clé invalide (lettres, chiffres, - _ . + : ; pas d\'espace ni de /).')
        if Piece.objects.filter(key=key).exists():
            raise forms.ValidationError('Cette clé existe déjà.')
        return key

    def clean(self):
        cd = super().clean()
        key = cd.get('key', '(nouvelle entrée)')
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
            if not v:
                entry.pop(f, None)
            elif entry.get(f) != v:
                put_field(entry, f, v)
        new_extra = cd['extra']
        for k in [k for k in entry if k not in SPECIAL and k not in BIBSET and k not in new_extra]:
            del entry[k]
        for k, v in new_extra.items():
            put_field(entry, k, v)
        if 'markdown' in entry or cd['markdown'] or not old:
            entry['markdown'] = cd['markdown']
        set_bibtex(entry, cd['overrides'])
        return entry
