import json
import tempfile
from pathlib import Path

import json2db
from django.db import connection
from django.test import Client, TestCase, override_settings
from frlib import BIBSET, SPECIAL

from . import search
from .audit import run_audit
from .corpus import bump
from .forms import PieceForm
from .models import Piece
from .similar import get_similarity
from .textutil import fold, osa, stem

ENTRIES = {
    '1997-05-00-brgmfr-39522': {
        'key': '1997-05-00-brgmfr-39522', 'ENTRYTYPE': 'misc', 'author': 'Ignatiadis, I. ; Cheradame, J.M.',
        'abstract': 'Traitement bactéricide du doublet géothermique de Coulommiers (Dogger).',
        'date': '1997-05-00', 'keywords': 'géothermie,corrosion', 'language': 'FR', 'number': 'R 39522',
        'title': "Optimisation de l'opération géothermique de Coulommiers", 'xacronym': 'brgmfr', 'xcounter': '39522',
        'xtheme': 'géothermie', 'year': '1997', 'piece_fond': 12, 'sha256': 'abc',
        'markdown': '# Rapport\n\nCorrosion des tubages par les sulfures.\n\n<!-- Page 2 -->\n\nSuite du texte.',
        'bibtex': {'xtheme': 'dogger', 'abstract': 'Résumé propre au .bib'}},
    '2015-00-00-sigesfr-dogger': {
        'key': '2015-00-00-sigesfr-dogger', 'ENTRYTYPE': 'misc', 'title': 'Le Dogger, aquifère géothermique du Bassin parisien',
        'date': '2015-00-00', 'year': '2015', 'xtheme': 'dogger', 'xacronym': 'sigesfr', 'xcounter': 'dogger',
        'markdown': "L'aquifère du Dogger se situe à 1 500 m de profondeur.", 'keywords': 'nappe'},
    '2014-04-08-cassationcrim-1283214': {
        'key': '2014-04-08-cassationcrim-1283214', 'ENTRYTYPE': 'misc', 'title': 'Cour de cassation, chambre criminelle, 8 avril 2014',
        'date': '2014-04-08', 'year': '2014', 'xtype': 'arrêt', 'markdown': 'Arrêt anonymisé.'},
    '2024-03-20-anteagroup-0001': {
        'key': '2024-03-20-anteagroup-0001', 'ENTRYTYPE': 'misc', 'title': 'Réalisation d’un doublet géothermique au Dogger',
        'date': '2024-03-20', 'year': '2024', 'markdown': 'Le doublet géothermique capte le Dogger. Corrosion et dépôts.'},
    '2024-03-20-anteagroup-0002': {
        'key': '2024-03-20-anteagroup-0002', 'ENTRYTYPE': 'misc', 'title': 'Réalisation d’un doublet géothermique au Dogger',
        'date': '2024-03-20', 'year': '2024', 'markdown': 'Le doublet géothermique capte le Dogger. Corrosion et dépôts.'},
    '2008-00-00-acparisorg-0003': {
        'key': '2008-00-00-acparisorg-0003', 'ENTRYTYPE': 'misc', 'title': 'Constitution and Bylaws', 'date': '2008-00-00',
        'year': '2008', 'language': 'EN', 'markdown': 'Bylaws of the church.'},
    '2020-01-01-foo-0001': {
        'key': '2020-01-01-foo-0001', 'ENTRYTYPE': 'misc', 'title': 'Incohérente', 'date': '2020-01-01', 'year': '2021',
        'xacronym': 'bar', 'markdown': ''},
}


class FrTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        connection.ensure_connection()
        raw = connection.connection
        if not raw.execute("SELECT 1 FROM sqlite_master WHERE name='pieces'").fetchone():
            json2db.create_schema(raw)                      # la table n'est pas gérée par Django : on la crée comme json2db
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        for e in ENTRIES.values():
            Piece.from_entry(e).save(force_insert=True)

    def setUp(self):
        bump()


class TextTests(TestCase):
    def test_fold_stem_distance(self):
        self.assertEqual(fold('Géothermie à l’œuvre'), "geothermie a l'oeuvre")
        self.assertEqual(stem('géothermie'.replace('é', 'e')), 'geothermi')
        self.assertEqual(osa('doger', 'dogger', 2), 1)
        self.assertEqual(osa('abcd', 'acbd', 2), 1)            # transposition
        self.assertGreater(osa('abcdef', 'uvwxyz', 2), 2)


class ParseTests(TestCase):
    def test_dates_fields_units(self):
        it = search.parse('entre 1990 et 2000 theme:dogger -corrosion "nappe du dogger" 8 avril 2014 brgmfr-39522 R39522')
        self.assertEqual(it.year, (1990, 2000))
        self.assertEqual(it.prefixes, ['2014-04-08'])
        self.assertEqual(it.fields, [('xtheme', 'dogger', False)])
        kinds = [(u.kind, u.text, u.neg) for u in it.units]
        self.assertIn(('term', 'corrosion', True), kinds)
        self.assertIn(('phrase', 'nappe du dogger', False), kinds)
        self.assertIn(('key', 'brgmfr-39522', False), kinds)
        self.assertTrue(any(u.ident and u.text == 'r39522' for u in it.units))

    def test_year_and_open_ranges(self):
        self.assertEqual(search.parse('1997').year, (1997, 1997))
        self.assertEqual(search.parse('avant 2010').year, (None, 2009))
        self.assertEqual(search.parse('depuis 2015').year, (2015, None))
        self.assertEqual(search.parse('year:1990..2000 doublet').year, (1990, 2000))
        self.assertEqual(search.parse('year:>2000').year, (2001, None))

    def test_stopwords_dropped_only_with_other_words(self):
        self.assertEqual([u.text for u in search.parse("l'aquifère du dogger").units], ['aquifere', 'dogger'])
        self.assertEqual([u.text for u in search.parse('du').units], ['du'])


class SearchTests(FrTestCase):
    def keys(self, q, **kw):
        return [d.key for d, _, _ in search.search(q, **kw).ranked]

    def test_accent_insensitive_and_and(self):
        self.assertIn('1997-05-00-brgmfr-39522', self.keys('geothermie corrosion'))
        self.assertNotIn('2008-00-00-acparisorg-0003', self.keys('geothermie'))

    def test_fuzzy_and_stem(self):
        out = search.search('geotermie')
        self.assertEqual(out.interp['units'][0]['level'], 'approchant')
        self.assertIn('1997-05-00-brgmfr-39522', [d.key for d, _, _ in out.ranked])
        self.assertEqual(search.search('geothermiques').interp['units'][0]['level'], 'racine')

    def test_synonyms_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(FR_SYNONYMS=Path(tmp) / 'absent.txt'):
                self.assertEqual(self.keys('statuts'), [])                 # sans fichier : aucun synonyme
            f = Path(tmp) / 'syn.txt'
            f.write_text('# commentaire\nstatuts = bylaws = reglement interieur\n', encoding='utf-8')
            with override_settings(FR_SYNONYMS=f):
                out = search.search('statuts')
                self.assertEqual([d.key for d, _, _ in out.ranked], ['2008-00-00-acparisorg-0003'])
                self.assertIn('bylaws', out.interp['units'][0]['detail'])

    def test_key_ident_and_title_boost(self):
        self.assertEqual(self.keys('brgmfr-39522'), ['1997-05-00-brgmfr-39522'])
        self.assertEqual(self.keys('R39522'), ['1997-05-00-brgmfr-39522'])
        ranked = self.keys('dogger')
        self.assertEqual(ranked[0], '2015-00-00-sigesfr-dogger')          # « dogger » dans le titre et la clé

    def test_dates_filters_override_values(self):
        self.assertEqual(self.keys('mai 1997'), ['1997-05-00-brgmfr-39522'])
        self.assertEqual(self.keys('8 avril 2014'), ['2014-04-08-cassationcrim-1283214'])
        self.assertEqual(self.keys('avant 2000'), ['1997-05-00-brgmfr-39522'])
        # thème : valeur de base « géothermie » OU surcharge « dogger »
        self.assertIn('1997-05-00-brgmfr-39522', self.keys('theme:geothermie'))
        self.assertIn('1997-05-00-brgmfr-39522', self.keys('theme:dogger'))
        self.assertEqual(self.keys('has:override'), ['1997-05-00-brgmfr-39522'])
        self.assertNotIn('1997-05-00-brgmfr-39522', self.keys('sans:number'))

    def test_negation_phrase_partial_and_ignored_words(self):
        self.assertNotIn('1997-05-00-brgmfr-39522', self.keys('dogger -corrosion'))
        self.assertEqual(self.keys('"chambre criminelle"'), ['2014-04-08-cassationcrim-1283214'])
        out = search.search('dogger corrosion bylaws')                   # aucun document ne contient les trois
        self.assertIn('partiels', out.interp['relaxed'])
        out = search.search('dogger zzzzqqq')
        self.assertTrue(out.ranked and any('zzzzqqq' in n for n in out.interp['notes']))

    def test_fts_mode_and_errors(self):
        self.assertTrue(self.keys('dogger NEAR(corrosion tubages, 10)', mode='fts'))
        self.assertIn('invalide', search.search('dogger AND (', mode='fts').error)

    def test_facets_and_sort(self):
        out = search.search('', facets={'xtheme': ['dogger']}, sort='date')
        self.assertEqual([d.key for d, _, _ in out.ranked], ['1997-05-00-brgmfr-39522', '2015-00-00-sigesfr-dogger'])
        self.assertTrue(any(f['name'] == 'decade' for f in out.facets))

    def test_snippets_are_escaped(self):
        n = Piece.objects.get(key='2015-00-00-sigesfr-dogger').n
        out = search.snippets([n], '"dogger"')
        self.assertIn('<mark>Dogger</mark>', str(out[n]))


class SimilarAuditTests(FrTestCase):
    def test_duplicates_and_similar(self):
        pairs = get_similarity().duplicates(0.85)
        keys = {frozenset([p['a'].key, p['b'].key]) for p in pairs if p['b']}
        self.assertIn(frozenset(['2024-03-20-anteagroup-0001', '2024-03-20-anteagroup-0002']), keys)
        sim = get_similarity().similar(Piece.objects.get(key='2024-03-20-anteagroup-0001').n, 3, 0.01)
        self.assertEqual(sim[0][0].key, '2024-03-20-anteagroup-0002')

    def test_audit(self):
        found = {c['id']: [d.key for d, _ in c['items']] for c in run_audit()}
        self.assertIn('2020-01-01-foo-0001', found['year'])
        self.assertIn('2020-01-01-foo-0001', found['acronym'])
        self.assertNotIn('1997-05-00-brgmfr-39522', found['year'])


class ViewTests(FrTestCase):
    def setUp(self):
        super().setUp()
        self.c = Client()
        self.key = '1997-05-00-brgmfr-39522'

    def test_pages(self):
        for url in ['/', '/?q=dogger', '/?q=geotermie&broad=1', '/audit/', '/doublons/', f'/p/{self.key}/', f'/p/{self.key}/bib/',
                    '/nouvelle/', f'/p/{self.key}/modifier/', '/export/fr.json', '/export/fr.bib']:
            self.assertEqual(self.c.get(url).status_code, 200, url)
        self.assertEqual(self.c.get('/p/nope/').status_code, 404)

    def test_detail_shows_origins_and_sanitizes(self):
        html = self.c.get(f'/p/{self.key}/').content.decode()
        self.assertIn('surcharge', html)
        self.assertIn('class="page"', html)                  # <!-- Page 2 --> transformé en séparateur
        piece = Piece.objects.get(key='2008-00-00-acparisorg-0003')
        piece.markdown = 'ok <script>alert(1)</script> <img src=x onerror=alert(1)>'
        piece.save(update_fields=['markdown'])
        html = self.c.get(f'/p/{piece.key}/').content.decode().split('<main>')[1]
        self.assertNotIn('<script', html)
        self.assertNotIn('onerror', html)

    def _post_data(self, entry, **changes):
        data = dict(PieceForm.from_entry(entry).initial)
        data = {k: v.replace('\n', '\r\n') if isinstance(v, str) else v for k, v in data.items()}
        data.update(changes)
        return data

    def test_edit_noop_then_change(self):
        entry = Piece.objects.get(key=self.key).to_entry()
        r = self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry), follow=True)
        self.assertIn('Aucun changement', r.content.decode())          # CRLF du navigateur normalisés
        r = self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, title='Titre zzyzx', note='une note'), follow=True)
        self.assertIn('Entrée enregistrée', r.content.decode())
        new = Piece.objects.get(key=self.key).to_entry()
        self.assertEqual(new['title'], 'Titre zzyzx')
        self.assertEqual(new['note'], 'une note')
        self.assertEqual(new['markdown'], entry['markdown'])
        self.assertEqual(new['bibtex'], entry['bibtex'])
        self.assertEqual(new['piece_fond'], 12)                       # champs « autres » intacts
        self.assertIn(self.key, [d.key for d, _, _ in search.search('zzyzx').ranked])   # FTS et cache à jour
        self.assertEqual(list(new)[:3], list(entry)[:3])               # l'ordre des champs est conservé

    def test_edit_validation(self):
        entry = Piece.objects.get(key=self.key).to_entry()
        for field, value, msg in [('abstract', 'x { y', 'déséquilibrées'), ('bibtex_json', '[1]', 'objet JSON'),
                                  ('extra_json', '{"title": "x"}', 'réservés'), ('bibtex_json', '{"year": 5}', 'texte ou null')]:
            r = self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, **{field: value}))
            self.assertEqual(r.status_code, 200)
            self.assertIn(msg, r.content.decode(), field)

    def test_override_null_and_removal(self):
        entry = Piece.objects.get(key=self.key).to_entry()
        r = self.c.post(f'/p/{self.key}/modifier/',
                        self._post_data(entry, bibtex_json=json.dumps({'xtheme': None}), abstract=''), follow=True)
        new = Piece.objects.get(key=self.key).to_entry()
        self.assertNotIn('abstract', new)
        self.assertEqual(new['bibtex'], {'xtheme': None})
        self.assertIn('supprimé du .bib', self.c.get(f'/p/{self.key}/').content.decode())

    def test_create_delete_and_exports(self):
        data = {'key': '2026-10-21-test-0001', 'entrytype': 'misc', 'title': 'Pièce de test', 'markdown': 'a\r\nb', 'extra_json': '{"remarque": "ok"}'}
        self.assertIn('Entrée créée', self.c.post('/nouvelle/', data, follow=True).content.decode())
        self.assertIn('existe déjà', self.c.post('/nouvelle/', data).content.decode())
        e = Piece.objects.get(key='2026-10-21-test-0001').to_entry()
        self.assertEqual(list(e), ['key', 'ENTRYTYPE', 'title', 'remarque', 'markdown'])
        self.assertEqual(e['markdown'], 'a\nb')
        exported = json.loads(self.c.get('/export/fr.json').content)
        self.assertIn('2026-10-21-test-0001', exported)
        self.assertEqual(exported[self.key]['bibtex']['xtheme'], 'dogger')
        for k, entry in exported.items():                              # la structure reste celle de frlib
            self.assertTrue(set(entry) - {'key', 'ENTRYTYPE', 'markdown', 'bibtex'} - BIBSET or True)
        self.assertIn('@misc{2026-10-21-test-0001,', self.c.get('/export/fr.bib').content.decode())
        self.c.post('/p/2026-10-21-test-0001/supprimer/')
        self.assertFalse(Piece.objects.filter(key='2026-10-21-test-0001').exists())

    @override_settings(FR_READONLY=True)
    def test_readonly(self):
        self.assertEqual(self.c.get(f'/p/{self.key}/modifier/').status_code, 403)
        self.assertEqual(self.c.post('/nouvelle/', {}).status_code, 403)
        self.assertEqual(self.c.post(f'/p/{self.key}/supprimer/').status_code, 403)
        self.assertNotIn('Nouvelle entrée', self.c.get('/').content.decode())
