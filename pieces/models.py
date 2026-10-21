"""Modèle non géré (managed = False) sur la table `pieces` créée par json2db.

Une ligne = une entrée du fr.json « remonté » (voir outils/lib/frlib.py) :
  colonnes BibTeX = valeurs de base ; extra = autres champs (JSON) ; bibtex = surcharges du .bib (JSON) ;
  field_order = ordre des clés de l'entrée (JSON). Les colonnes générées (xpiecefond...) sont absentes du modèle."""
import json

from django.db import models
from frlib import BIB, entry_to_row, row_to_entry

ROW_FIELDS = ['entrytype', *BIB, 'extra', 'bibtex', 'markdown', 'field_order']


class Piece(models.Model):
    n = models.AutoField(primary_key=True)
    key = models.CharField('clé', max_length=255, unique=True, db_column='id')
    entrytype = models.TextField(null=True, blank=True)
    title = models.TextField(null=True, blank=True)
    author = models.TextField(null=True, blank=True)
    abstract = models.TextField(null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    number = models.TextField(null=True, blank=True)
    organization = models.TextField(null=True, blank=True)
    type = models.TextField(null=True, blank=True)
    xtype = models.TextField(null=True, blank=True)
    keywords = models.TextField(null=True, blank=True)
    xtheme = models.TextField(null=True, blank=True)
    date = models.TextField(null=True, blank=True)
    year = models.TextField(null=True, blank=True)
    language = models.TextField(null=True, blank=True)
    xcounter = models.TextField(null=True, blank=True)
    xacronym = models.TextField(null=True, blank=True)
    shorthand = models.TextField(null=True, blank=True)
    url = models.TextField(null=True, blank=True)
    howpublished = models.TextField(null=True, blank=True)
    xtime = models.TextField(null=True, blank=True)
    xdatetime = models.TextField(null=True, blank=True)
    file = models.TextField(null=True, blank=True)
    publisher = models.TextField(null=True, blank=True)
    urldate = models.TextField(null=True, blank=True)
    annote = models.TextField(null=True, blank=True)
    volume = models.TextField(null=True, blank=True)
    medium = models.TextField(null=True, blank=True)
    issue = models.TextField(null=True, blank=True)
    collection = models.TextField(null=True, blank=True)
    archive = models.TextField(null=True, blank=True)
    edition = models.TextField(null=True, blank=True)
    xduplicate = models.TextField(null=True, blank=True)
    shorthand2 = models.TextField(null=True, blank=True)
    extra = models.TextField(default='{}')
    bibtex = models.TextField(null=True, blank=True)
    markdown = models.TextField(default='')
    field_order = models.TextField(default='[]')

    class Meta:
        managed = False
        db_table = 'pieces'
        ordering = ['key']

    def __str__(self):
        return self.key

    # -- passage entrée JSON <-> ligne, via frlib (une seule source de vérité) --
    def as_row(self):
        row = {'id': self.key}
        for f in ROW_FIELDS:
            row[f] = getattr(self, f)
        return row

    def to_entry(self):
        return row_to_entry(self.as_row())

    @classmethod
    def from_entry(cls, entry):
        row = entry_to_row(entry)
        return cls(**{('key' if k == 'id' else k): v for k, v in row.items()})

    def set_from_entry(self, entry):
        """Applique une entrée à l'instance; renvoie la liste des champs modifiés (pour save(update_fields=...))."""
        row = entry_to_row(entry)
        changed = []
        for f in ROW_FIELDS:
            if getattr(self, f) != row[f]:
                setattr(self, f, row[f])
                changed.append(f)
        return changed

    @property
    def extra_dict(self):
        return json.loads(self.extra)

    @property
    def overrides(self):
        return json.loads(self.bibtex) if self.bibtex else {}
