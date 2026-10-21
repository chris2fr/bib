#!/usr/bin/env python3
"""fr.json (remonté) -> fr.db (SQLite), sans perte.  Usage: json2db.py fr.json fr.db

Une ligne par entrée : colonnes pour ENTRYTYPE et chaque champ BibTeX (valeur de base), "extra" (JSON des
autres champs), "bibtex" (JSON des surcharges), markdown, et "field_order" (ordre des champs, pour un export
identique à l'octet près)."""
import json, os, sqlite3, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from frlib import BIB, entry_to_row


def create_schema(db):
    """Crée la table pieces, l'index FTS5 à contenu externe et les triggers (base vide)."""
    db.execute(f"""
CREATE TABLE pieces (
  n INTEGER PRIMARY KEY,                     -- numéro de ligne stable (garde l'index FTS valide après VACUUM)
  id TEXT NOT NULL UNIQUE,                   -- = clé de citation
  entrytype TEXT,
  {", ".join(f"{c} TEXT" for c in BIB)},     -- valeurs de base (ex-frontmatter, sinon ex-bibtex)
  extra TEXT NOT NULL CHECK (json_valid(extra)),                    -- champs sans équivalent BibTeX (JSON)
  bibtex TEXT CHECK (bibtex IS NULL OR json_valid(bibtex)),         -- surcharges du .bib (JSON), NULL si aucune
  markdown TEXT NOT NULL,
  -- colonnes en lecture seule, dérivées de "extra"
  xpiecefond INTEGER GENERATED ALWAYS AS (json_extract(extra,'$.piece_fond')) VIRTUAL,
  xsourcefile TEXT   GENERATED ALWAYS AS (json_extract(extra,'$.fichier_source')) VIRTUAL,
  xpages INTEGER     GENERATED ALWAYS AS (json_extract(extra,'$.pages')) VIRTUAL,
  xmentiontelerecours TEXT GENERATED ALWAYS AS (json_extract(extra,'$.mention_telerecours')) VIRTUAL,
  field_order TEXT NOT NULL CHECK (json_valid(field_order))         -- ordre des clés de l'entrée (JSON)
)""")
    # ---- recherche plein texte : FTS5 à contenu externe (pas de texte dupliqué), sans accents ni casse ----
    FTS = ['id','title','author','abstract','note','keywords','organization','markdown']
    cl = ', '.join(FTS)
    db.execute(f"""CREATE VIRTUAL TABLE pieces_fts USING fts5(
  {cl}, content='pieces', content_rowid='n',
  tokenize='unicode61 remove_diacritics 2')""")
    new = ', '.join(f'new.{c}' for c in FTS); old = ', '.join(f'old.{c}' for c in FTS)
    db.executescript(f"""
CREATE TRIGGER pieces_ai AFTER INSERT ON pieces BEGIN
  INSERT INTO pieces_fts(rowid, {cl}) VALUES (new.n, {new});
END;
CREATE TRIGGER pieces_ad AFTER DELETE ON pieces BEGIN
  INSERT INTO pieces_fts(pieces_fts, rowid, {cl}) VALUES ('delete', old.n, {old});
END;
CREATE TRIGGER pieces_au AFTER UPDATE OF {cl} ON pieces BEGIN
  INSERT INTO pieces_fts(pieces_fts, rowid, {cl}) VALUES ('delete', old.n, {old});
  INSERT INTO pieces_fts(rowid, {cl}) VALUES (new.n, {new});
END;
""")

def build(d, dst):
    """Construit une base neuve dst (remplacée si elle existe) à partir du dict fr.json."""
    if os.path.exists(dst): os.remove(dst)
    db = sqlite3.connect(dst)
    create_schema(db)
    for k, e in d.items():
        assert e['key'] == k, k
        row = entry_to_row(e)
        db.execute(f'INSERT INTO pieces ({",".join(row)}) VALUES ({",".join("?"*len(row))})', list(row.values()))
    db.execute("INSERT INTO pieces_fts(pieces_fts) VALUES ('rebuild')")
    db.commit(); db.close()
    return len(d)

if __name__ == '__main__':
    src, dst = sys.argv[1], sys.argv[2]
    n = build(json.load(open(src, encoding='utf-8')), dst)
    print(f'{n} rows -> {dst}')
