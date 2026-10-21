"""Mise en forme BibTeX d'une entrée du fr.json : valeurs de base, puis surcharges du .bib appliquées."""
from frlib import BIBSET


def bib_fields(entry):
    """{champ: valeur} telle qu'écrite dans le .bib (surcharge > valeur de base ; null supprime le champ)."""
    ov = entry.get('bibtex') or {}
    fields = {name: ov.get(name, base) for name, base in entry.items() if name in BIBSET}
    fields.update({n: v for n, v in ov.items() if n not in BIBSET and n != 'ENTRYTYPE'})
    return {n: v for n, v in fields.items() if v is not None}


def bib_text(entry):
    ov = entry.get('bibtex') or {}
    kind = (ov.get('ENTRYTYPE') or entry.get('ENTRYTYPE') or 'misc').lower()
    lines = [f'@{kind}{{{entry["key"]},']
    lines += [f'  {n} = {{{v}}},' for n, v in bib_fields(entry).items()]
    lines.append('}')
    return '\n'.join(lines) + '\n'
