import json
import tempfile
from pathlib import Path

import frlib
import json2db
from django.db import connection
from django.test import Client, TestCase, override_settings
from frlib import BIBSET, SPECIAL

from . import helpers, search
from .audit import run_audit
from .corpus import bump
from .forms import PieceForm
from .models import HelperValue, Piece
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


class DateRangeParseTests(TestCase):
    def ranges(self, q):
        it = search.parse(q)
        return it.ranges, it.prefixes, it.year

    def test_ranges(self):
        for q, want in [('entre 1997-05-12 et 1998-03-01', ('1997-05-12', '1998-03-01')),
                        ('du 8 avril 2014 au 3 juin 2015', ('2014-04-08', '2015-06-03')),
                        ('entre mai 1997 et mars 1998', ('1997-05-01', '1998-03-31')),
                        ('entre 1997-05-12 et 1999', ('1997-05-12', '1999-12-31')),
                        ('date:1997-05..1997-09', ('1997-05-01', '1997-09-30')),
                        ('date:1997-05-12..1998-03-01', ('1997-05-12', '1998-03-01')),
                        ('1997-05-12..1998-03-01', ('1997-05-12', '1998-03-01')),
                        ('date:1998..1997', ('1997-01-01', '1998-12-31')),                  # bornes inversées
                        ('date:1997-05-12..', ('1997-05-12', None)), ('date:..1999-06', (None, '1999-06-30')),
                        ('date:>=2014-04-08', ('2014-04-08', None)), ('date:>2014', ('2015-01-01', None)),
                        ('date:<2000-01-01', (None, '1999-12-31')), ('date:<=2000', (None, '2000-12-31')),
                        ('avant 8 avril 2014', (None, '2014-04-07')), ('après 8 avril 2014', ('2014-04-09', None)),
                        ('depuis mai 1997', ('1997-05-01', None))]:
            ranges, prefixes, year = self.ranges(q)
            self.assertEqual((ranges, prefixes, year), ([want], [], None), q)

    def test_unchanged_simple_forms(self):
        self.assertEqual(self.ranges('entre 1990 et 2000'), ([], [], (1990, 2000)))
        self.assertEqual(self.ranges('avant 2010'), ([], [], (None, 2009)))
        self.assertEqual(self.ranges('8 avril 2014'), ([], ['2014-04-08'], None))
        self.assertEqual(self.ranges('date:1997-05'), ([], ['1997-05'], None))
        self.assertEqual(self.ranges('date:1997-02-30..1998'), ([], ['1997-02-30..1998'], None))   # date impossible : pas une plage


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

    def test_date_ranges(self):
        B, S, C, A = '1997-05-00-brgmfr-39522', '2015-00-00-sigesfr-dogger', '2014-04-08-cassationcrim-1283214', '2008-00-00-acparisorg-0003'
        self.assertEqual(self.keys('date:1997-05-12..1997-05-20'), [B])               # 1997-05-00 = tout mai 1997 : chevauche
        self.assertEqual(self.keys('date:1997-06..1997-09'), [])
        self.assertEqual(self.keys('entre 2014-04-01 et 2014-04-30'), [C])
        self.assertEqual(self.keys('avant 8 avril 2014'), [B, A])                      # le 8 avril lui-même est exclu
        self.assertEqual(self.keys('après mai 1997 avant 2009'), [A])
        self.assertIn(B, self.keys('depuis mai 1997'))
        self.assertNotIn(B, self.keys('après mai 1997'))
        self.assertEqual(self.keys('dogger du 8 avril 2014 au 20 mars 2024'), [S, '2024-03-20-anteagroup-0001', '2024-03-20-anteagroup-0002'])
        self.assertEqual(self.keys('', date_from='2014-01-01', date_to='2014-12-31'), [C])    # champs du / au du formulaire
        self.assertEqual(self.keys('', date_from='2015-01-01'), [S, '2020-01-01-foo-0001', '2024-03-20-anteagroup-0001', '2024-03-20-anteagroup-0002'])
        self.assertEqual(self.keys('"chambre criminelle"', mode='fts', date_to='2013'), [])
        out = search.search('', date_from='2014-01-01', date_to='2014-12-31')
        self.assertIn('date du 2014-01-01 au 2014-12-31', out.interp['filters'])

    def test_nature_is_the_type_field(self):
        Piece.objects.filter(key='2014-04-08-cassationcrim-1283214').update(type='arrêt')
        bump()
        out = search.search('')
        facets = {f['name']: f for f in out.facets}
        self.assertEqual(facets['type']['label'], 'Nature')
        self.assertEqual(facets['type']['values'], [('arrêt', 1)])
        self.assertNotIn('xtype', facets)                                                   # plus de facette sur xtype
        self.assertEqual(self.keys('nature:arret'), ['2014-04-08-cassationcrim-1283214'])    # « nature » = champ type
        self.assertEqual(self.keys('type:arret'), ['2014-04-08-cassationcrim-1283214'])
        self.assertEqual(self.keys('xtype:arret'), ['2014-04-08-cassationcrim-1283214'])     # xtype reste filtrable explicitement
        self.assertEqual(self.keys('', facets={'type': ['arrêt']}), ['2014-04-08-cassationcrim-1283214'])

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


class FieldOrderTests(FrTestCase):
    key = '1997-05-00-brgmfr-39522'

    def setUp(self):
        super().setUp()
        self.c = Client()
        self.addCleanup(frlib.set_order)                       # retour aux variables d'environnement

    def messy(self):
        return {'key': 'k-1', 'ENTRYTYPE': 'misc', 'zeta': 1, 'title': 'T', 'Alpha': 2, 'year': '2000', 'author': 'A',
                'date': '2000-01-01', 'markdown': 'm', 'bibtex': {'title': 'X'}}

    def stored_order(self, entry):
        return list(frlib.row_to_entry(frlib.entry_to_row(entry)))

    def test_default_is_alphabetical_inside_each_group(self):
        self.assertEqual(self.stored_order(self.messy()),
                         ['key', 'ENTRYTYPE', 'author', 'date', 'title', 'year', 'Alpha', 'zeta', 'markdown', 'bibtex'])

    def test_parameter_then_alphabetical_for_the_rest(self):
        frlib.set_order(bibtex=['title', 'year'], other=['zeta'])
        self.assertEqual(self.stored_order(self.messy()),
                         ['key', 'ENTRYTYPE', 'title', 'year', 'author', 'date', 'zeta', 'Alpha', 'markdown', 'bibtex'])

    def test_environment_parameter(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {'BIBMAN_ORDER_BIBTEX': ' date , title ', 'BIBMAN_ORDER_OTHER': 'zeta'}):
            self.assertEqual(frlib.field_order('bibtex'), ['date', 'title'])
            self.assertEqual(self.stored_order(self.messy())[2:7], ['date', 'title', 'author', 'year', 'zeta'])

    def test_bib_export_form_and_detail_follow_the_order(self):
        def positions(html, *needles):
            return [html.index(n) for n in needles]
        page = lambda url: self.c.get(url).content.decode()
        form_needles = ('name="author"', 'name="date"', 'name="title"')
        bib_needles = ('author =', 'date =', 'title =')
        entry = Piece.objects.get(key=self.key).to_entry()
        self.assertEqual(positions(page(f'/p/{self.key}/modifier/'), *form_needles), sorted(positions(page(f'/p/{self.key}/modifier/'), *form_needles)))
        text = page(f'/p/{self.key}/bib/')
        self.assertEqual(positions(text, *bib_needles), sorted(positions(text, *bib_needles)))      # alphabétique par défaut
        frlib.set_order(bibtex=['title', 'date'])
        for url, needles in ((f'/p/{self.key}/modifier/', form_needles), (f'/p/{self.key}/bib/', bib_needles)):
            p = positions(page(url), *needles)
            self.assertLess(p[2], p[1], url)                                                         # title avant date
            self.assertLess(p[1], p[0], url)                                                         # date avant author
        self.assertEqual(list(self.c.get('/export/fr.json').json()[self.key])[:4], ['key', 'ENTRYTYPE', 'title', 'date'])
        # modifier sans rien changer reste « Aucun changement » quel que soit l'ordre
        data = {k: v.replace('\n', '\r\n') if isinstance(v, str) else v for k, v in PieceForm.from_entry(entry).initial.items()}
        self.assertIn('Aucun changement', self.c.post(f'/p/{self.key}/modifier/', data, follow=True).content.decode())

    def test_field_order_column_is_dropped_from_old_databases(self):
        from . import schema
        with connection.cursor() as c:
            c.execute("ALTER TABLE pieces ADD COLUMN field_order TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(field_order))")
            c.execute('''UPDATE pieces SET field_order = '["markdown","key","title"]' ''')
        schema._ok = False
        schema.ensure()
        with connection.cursor() as c:
            c.execute("SELECT COUNT(*) FROM pragma_table_info('pieces') WHERE name = 'field_order'")
            self.assertEqual(c.fetchone()[0], 0)
        entry = Piece.objects.get(key=self.key).to_entry()
        self.assertEqual(list(entry)[:2], ['key', 'ENTRYTYPE'])
        Piece.from_entry({'key': 'k-new-1', 'ENTRYTYPE': 'misc', 'markdown': ''}).save(force_insert=True)      # l'insertion marche sans la colonne
        self.assertNotIn('markdown', Piece.objects.get(key='k-new-1').to_entry())                             # champ vide = absent


class AdvancedSearchTests(FrTestCase):
    def setUp(self):
        super().setUp()
        self.c = Client()

    def query(self, **params):
        r = self.c.get('/recherche-avancee/', params)
        self.assertEqual(r.status_code, 302, r.content.decode()[:300] if r.status_code == 200 else '')
        from urllib.parse import parse_qs, urlparse
        qs = parse_qs(urlparse(r['Location']).query)
        return qs.get('q', [''])[0], qs.get('sort', [''])[0]

    def test_page_and_choices(self):
        html = self.c.get('/recherche-avancee/').content.decode()
        self.assertIn('name="phrase"', html)
        self.assertIn('<option value="dogger">', html)                  # listes alimentées par les valeurs du corpus
        self.assertIn('href="/recherche-avancee/"', self.c.get('/').content.decode())

    def test_builds_the_usual_syntax(self):
        q, sort = self.query(all='dogger corrosion', phrase='nappe du dogger', exclude='tubage "x y"', title='réseau de chaleur',
                             author='dupont', organization='brgm', keywords='nappe', xtheme='dogger', language='FR',
                             year_from='1990', year_to='2000', has_url='has', has_note='no', sort='date')
        self.assertEqual(q, 'dogger corrosion "nappe du dogger" -tubage -"x y" titre:"réseau de chaleur" auteur:dupont org:brgm kw:nappe '
                            'theme:dogger lang:FR year:1990..2000 has:url no:note')
        self.assertEqual(sort, 'date')
        self.assertEqual(self.query(year_from='2015')[0], 'year:>=2015')
        self.assertEqual(self.query(date_from='1997-05', date_to='1998-03-01')[0], 'date:1997-05..1998-03-01')
        self.assertEqual(self.query(date_from='2014-04-08')[0], 'date:2014-04-08..')
        self.assertEqual(self.query(all='  ')[0], '')

    def test_generated_query_finds_the_right_entries(self):
        for params, expected in [
                ({'author': 'ignatiadis', 'date_from': '1997-05-12', 'date_to': '1997-05-20'}, ['1997-05-00-brgmfr-39522']),
                ({'all': 'dogger', 'exclude': 'corrosion', 'year_from': '2015', 'year_to': '2024'},
                 ['2015-00-00-sigesfr-dogger']),
                ({'xtheme': 'dogger'}, ['1997-05-00-brgmfr-39522', '2015-00-00-sigesfr-dogger']),
                ({'language': 'EN', 'has_note': 'no'}, ['2008-00-00-acparisorg-0003'])]:
            q, _ = self.query(**params)
            self.assertEqual([d.key for d, _, _ in search.search(q, sort='date').ranked], expected, q)
        html = self.c.get('/', {'q': self.query(title='dogger', year_from='2015')[0]}).content.decode()
        self.assertIn('2015-00-00-sigesfr-dogger', html)

    def test_validation_errors_stay_on_the_form(self):
        for params, msg in [({'date_from': '1997-13'}, 'Date invalide'), ({'date_from': '1997/05'}, 'Format attendu'),
                            ({'year_from': '2000', 'year_to': '1990'}, 'précède'), ({'date_to': '1997-02-30'}, 'Date invalide')]:
            r = self.c.get('/recherche-avancee/', params)
            self.assertEqual(r.status_code, 200, params)
            self.assertIn(msg, r.content.decode(), params)


class EnvFileTests(TestCase):
    def test_env_file_is_loaded_without_overriding_the_environment(self):
        import os
        from unittest import mock

        from bibman.env import load_env
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'custom.env'
            f.write_text('# commentaire\nBIBMAN_TEST_A="deux mots"\nexport BIBMAN_TEST_B=fichier\nBIBMAN_TEST_C=fichier\n', encoding='utf-8')
            with mock.patch.dict(os.environ, {'BIBMAN_ENV_FILE': str(f), 'BIBMAN_TEST_C': 'environnement'}):
                self.assertEqual(load_env(tmp), f)
                self.assertEqual(os.environ['BIBMAN_TEST_A'], 'deux mots')
                self.assertEqual(os.environ['BIBMAN_TEST_B'], 'fichier')
                self.assertEqual(os.environ['BIBMAN_TEST_C'], 'environnement')            # l'environnement l'emporte
            for k in ('BIBMAN_TEST_A', 'BIBMAN_TEST_B'):
                os.environ.pop(k, None)
            (Path(tmp) / '.env').write_text('BIBMAN_TEST_D=racine\n', encoding='utf-8')
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop('BIBMAN_ENV_FILE', None)
                self.assertEqual(load_env(tmp), Path(tmp) / '.env')                      # par défaut : .env à la racine
                self.assertEqual(os.environ.pop('BIBMAN_TEST_D'), 'racine')
            empty = Path(tmp) / 'vide'
            empty.mkdir()
            self.assertIsNone(load_env(empty))                                           # pas de fichier : sans effet


class OverrideMoveTests(FrTestCase):
    key = '1997-05-00-brgmfr-39522'      # base : xtheme géothermie, surcharges : xtheme dogger, abstract « Résumé propre au .bib »

    def setUp(self):
        super().setUp()
        self.c = Client()

    def move(self, action, field):
        return self.c.post(f'/p/{self.key}/surcharge/', {'action': action, 'field': field}, follow=True)

    def piece(self):
        return Piece.objects.get(key=self.key)

    def test_buttons_on_the_detail_page(self):
        html = self.c.get(f'/p/{self.key}/').content.decode()
        self.assertIn('value="bib2base"', html)
        self.assertIn('value="base2bib"', html)
        Piece.objects.filter(key=self.key).update(bibtex=None)
        bump()
        html = self.c.get(f'/p/{self.key}/').content.decode()
        self.assertNotIn('bib2base', html)                                    # rien à déplacer sans surcharge

    def test_base2bib_deletes_only_the_override(self):
        self.assertIn('supprimée', self.move('base2bib', 'xtheme').content.decode())
        p = self.piece()
        self.assertEqual(p.xtheme, 'géothermie')                              # la base est gardée
        self.assertEqual(p.overrides, {'abstract': 'Résumé propre au .bib'})

    def test_bib2base_moves_the_value_into_the_base(self):
        self.assertIn('appliquée à la base', self.move('bib2base', 'abstract').content.decode())
        p = self.piece()
        self.assertEqual(p.abstract, 'Résumé propre au .bib')
        self.assertEqual(p.overrides, {'xtheme': 'dogger'})
        self.assertEqual(p.title, "Optimisation de l'opération géothermique de Coulommiers")        # le reste est intact
        self.assertIn(self.key, [d.key for d, _, _ in search.search('propre').ranked])               # FTS à jour

    def test_null_override_removes_the_base_value(self):
        Piece.objects.filter(key=self.key).update(bibtex=json.dumps({'xtheme': None}))
        bump()
        self.assertIn('<button name="action" value="bib2base"', self.c.get(f'/p/{self.key}/').content.decode())
        self.move('bib2base', 'xtheme')
        p = self.piece()
        self.assertIsNone(p.xtheme)
        self.assertIsNone(p.bibtex)

    def test_all_overrides_at_once(self):
        self.move('bib2base', '*')
        p = self.piece()
        self.assertEqual((p.xtheme, p.abstract, p.bibtex), ('dogger', 'Résumé propre au .bib', None))
        Piece.objects.filter(key=self.key).update(bibtex=json.dumps({'xtheme': 'autre', 'doi': '10.1/x'}))
        bump()
        self.move('bib2base', '*')
        p = self.piece()
        self.assertEqual((p.xtheme, p.overrides), ('autre', {'doi': '10.1/x'}))                      # champ propre au .bib : reste surcharge
        self.move('base2bib', '*')
        self.assertIsNone(self.piece().bibtex)

    def test_moved_value_goes_through_the_form_rules(self):
        Piece.objects.filter(key=self.key).update(bibtex=json.dumps({'date': '1997', 'xtime': '25:00'}))
        bump()
        r = self.move('bib2base', 'date')
        self.assertIn('Valeur refusée', r.content.decode())
        self.assertEqual(self.piece().date, '1997-05-00')                                            # rien n'a changé
        self.assertEqual(self.piece().overrides, {'date': '1997', 'xtime': '25:00'})
        Piece.objects.filter(key=self.key).update(bibtex=json.dumps({'date': '1998-01-02'}))
        bump()
        self.move('bib2base', 'date')
        p = self.piece()
        self.assertEqual((p.date, p.year, p.bibtex), ('1998-01-02', '1998', None))                   # year recalculée

    def test_refusals_and_readonly(self):
        Piece.objects.filter(key=self.key).update(bibtex=json.dumps({'year': '2001', 'doi': 'x'}))
        bump()
        self.assertIn('calculé', self.move('bib2base', 'year').content.decode())                   # year est calculée : pas de bib2base
        self.assertIn('introuvable', self.move('base2bib', 'title').content.decode())
        r = self.c.get(f'/p/{self.key}/surcharge/')                                                   # GET : retour à la fiche, sans rien changer
        self.assertEqual((r.status_code, r['Location']), (302, f'/p/{self.key}/'))
        self.move('base2bib', 'year')
        self.assertEqual(self.piece().overrides, {'doi': 'x'})
        with override_settings(FR_READONLY=True):
            self.assertEqual(self.move('base2bib', 'doi').status_code, 403)
            self.assertNotIn('base2bib', self.c.get(f'/p/{self.key}/').content.decode())

    def test_override_without_base_value_is_listed(self):
        Piece.objects.filter(key=self.key).update(bibtex=json.dumps({'publisher': 'Éditeur .bib'}))
        bump()
        html = self.c.get(f'/p/{self.key}/').content.decode()
        self.assertIn('Éditeur .bib', html)
        self.assertIn('sans valeur de base', html)
        self.move('bib2base', 'publisher')
        self.assertEqual(self.piece().publisher, 'Éditeur .bib')


class DeclaredDuplicateTests(FrTestCase):
    A, B = '2024-03-20-anteagroup-0001', '2024-03-20-anteagroup-0002'

    def setUp(self):
        super().setUp()
        self.c = Client()

    def declare(self, key, of):
        return self.c.post('/doublons/declarer/', {'key': key, 'of': of}, follow=True)

    def pair_keys(self):
        return {frozenset([p['a'].key, p['b'].key]) for p in get_similarity().duplicates(0.85) if p['b']}

    def test_declaring_removes_the_pair_and_shows_on_pages(self):
        self.assertIn(frozenset([self.A, self.B]), self.pair_keys())
        self.assertIn('declarer', self.c.get('/doublons/').content.decode())
        self.assertIn(f'{self.B} déclaré doublon de {self.A}', self.declare(self.B, self.A).content.decode())
        self.assertEqual(Piece.objects.get(key=self.B).xdup, self.A)
        self.assertNotIn(frozenset([self.A, self.B]), self.pair_keys())                       # n'est plus à examiner
        page = self.c.get('/doublons/').content.decode()
        self.assertIn(f'{self.B}</a> → <a href="/p/{self.A}/">{self.A}', page)               # listé parmi les déclarés
        self.assertIn('Doublon de', self.c.get(f'/p/{self.B}/').content.decode())
        self.assertIn('Doublons déclarés de cette entrée', self.c.get(f'/p/{self.A}/').content.decode())
        self.assertEqual([d.key for d, _, _ in search.search('has:xdup').ranked], [self.B])
        self.assertEqual([d.key for d, _, _ in search.search(f'xdup:{self.A}').ranked], [self.B])
        found = {c['id']: c['items'] for c in run_audit()}
        self.assertEqual(found['xdup'], [])
        self.c.post(f'/doublons/{self.B}/retirer/')
        self.assertIsNone(Piece.objects.get(key=self.B).xdup)
        self.assertIn(frozenset([self.A, self.B]), self.pair_keys())

    def test_rules(self):
        self.assertIn('Aucune entrée', self.declare(self.B, 'nope').content.decode())
        self.assertIn('propre doublon', self.declare(self.B, self.B).content.decode())
        self.declare(self.B, self.A)
        self.assertIn('est elle-même un doublon de', self.declare('2008-00-00-acparisorg-0003', self.B).content.decode())   # pas de chaîne
        self.assertIn('déjà la cible', self.declare(self.A, '2008-00-00-acparisorg-0003').content.decode())                  # A est cible de B
        self.assertIsNone(Piece.objects.get(key=self.A).xdup)

    def test_form_field_and_validation(self):
        page = self.c.get(f'/p/{self.B}/modifier/').content.decode()
        self.assertIn('name="xdup"', page)
        self.assertIn(f'<option value="{self.A}">', page)                                      # proposé d'après la similarité
        entry = Piece.objects.get(key=self.B).to_entry()
        data = lambda **kw: {k: v.replace('\n', '\r\n') if isinstance(v, str) else v for k, v in
                             {**PieceForm.from_entry(entry).initial, **kw}.items()}
        self.assertIn('Aucune entrée', self.c.post(f'/p/{self.B}/modifier/', data(xdup='nope')).content.decode())
        self.assertIn('propre doublon', self.c.post(f'/p/{self.B}/modifier/', data(xdup=self.B)).content.decode())
        r = self.c.post(f'/p/{self.B}/modifier/', data(xdup=self.A), follow=True)
        self.assertEqual(Piece.objects.get(key=self.B).xdup, self.A)
        self.assertIn(f'/p/{self.A}/', r.content.decode())

    def test_rename_follows_and_delete_is_refused(self):
        self.declare(self.B, self.A)
        entry = Piece.objects.get(key=self.A).to_entry()
        data = {k: v.replace('\n', '\r\n') if isinstance(v, str) else v for k, v in
                {**PieceForm.from_entry(entry).initial, 'key': '2024-03-20-anteagroup-0100'}.items()}
        self.c.post(f'/p/{self.A}/modifier/', data, follow=True)
        self.assertEqual(Piece.objects.get(key=self.B).xdup, '2024-03-20-anteagroup-0100')    # la cible renommée est suivie
        self.assertIn('Suppression impossible', self.c.post('/p/2024-03-20-anteagroup-0100/supprimer/', follow=True).content.decode())
        self.assertTrue(Piece.objects.filter(key='2024-03-20-anteagroup-0100').exists())
        self.assertEqual([d.key for d, _, _ in search.search('xdup:anteagroup-0100').ranked], [self.B])

    @override_settings(FR_READONLY=True)
    def test_readonly(self):
        self.assertEqual(self.declare(self.B, self.A).status_code, 403)
        self.assertEqual(self.c.post(f'/doublons/{self.B}/retirer/').status_code, 403)
        self.assertNotIn('declarer', self.c.get('/doublons/').content.decode())

    def test_audit_flags_broken_declarations(self):
        Piece.objects.filter(key=self.B).update(xdup='gone')
        Piece.objects.filter(key=self.A).update(xdup=self.A)
        bump()
        found = {c['id']: [d.key for d, _ in c['items']] for c in run_audit()}
        self.assertEqual(sorted(found['xdup']), sorted([self.A, self.B]))

    def test_xdup_column_added_to_old_database(self):
        from . import schema
        with connection.cursor() as c:
            c.execute('ALTER TABLE pieces DROP COLUMN xdup')
        schema._ok = False
        schema.ensure()
        self.assertIsNone(Piece.objects.get(key=self.A).xdup)


class SourceFilesTests(FrTestCase):
    key = '1997-05-00-brgmfr-39522'

    def setUp(self):
        super().setUp()
        self.c = Client()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        patcher = override_settings(BIBMAN_FILES=self.dir)
        patcher.enable()
        self.addCleanup(patcher.disable)

    def test_locate_prefers_file_property_then_key_pdf(self):
        from . import files
        self.assertIsNone(files.locate(self.key, None))
        (self.dir / f'{self.key}.pdf').write_bytes(b'%PDF-key')
        self.assertEqual((files.locate(self.key, None).name, files.locate(self.key, None).via), (f'{self.key}.pdf', 'key'))
        (self.dir / 'rapport.pdf').write_bytes(b'%PDF-prop')
        loc = files.locate(self.key, 'rapport.pdf')
        self.assertEqual((loc.name, loc.via), ('rapport.pdf', 'file'))
        self.assertEqual(files.locate(self.key, 'absent.pdf').via, 'key')           # champ file introuvable : repli sur <clé>.pdf
        for bad in ['../x.pdf', 'a/b.pdf', 'a\\b.pdf', '..', '/etc/passwd']:
            self.assertFalse(files.safe_name(bad), bad)
            self.assertIsNone(files.locate('zzz', bad))
        self.assertEqual(files.expected_name(self.key, '../x'), f'{self.key}.pdf')

    def test_serving_and_detail(self):
        html = self.c.get(f'/p/{self.key}/').content.decode()
        self.assertIn('introuvable dans', html)                                      # dossier présent, fichier absent
        self.assertEqual(self.c.get(f'/p/{self.key}/fichier/').status_code, 404)
        (self.dir / 'rapport.pdf').write_bytes(b'%PDF-prop')
        Piece.objects.filter(key=self.key).update(file='rapport.pdf')
        bump()                                                                        # update() ne passe pas par les signaux
        html = self.c.get(f'/p/{self.key}/').content.decode()
        self.assertIn(f'/p/{self.key}/fichier/', html)
        r = self.c.get(f'/p/{self.key}/fichier/')
        self.assertEqual((r.status_code, r['Content-Type'], b''.join(r.streaming_content)), (200, 'application/pdf', b'%PDF-prop'))
        self.assertTrue(r['Content-Disposition'].startswith('inline'))
        self.assertTrue(self.c.get(f'/p/{self.key}/fichier/?download=1')['Content-Disposition'].startswith('attachment'))
        self.assertIn('fichier</a>', self.c.get('/?q=brgmfr-39522').content.decode())     # lien dans la liste
        (self.dir / 'page.html').write_text('<script>alert(1)</script>')
        Piece.objects.filter(key=self.key).update(file='page.html')
        r = self.c.get(f'/p/{self.key}/fichier/')
        self.assertTrue(r['Content-Disposition'].startswith('attachment'))                # jamais de HTML affiché sur le site
        Piece.objects.filter(key=self.key).update(file='../secret.txt')
        self.assertEqual(self.c.get(f'/p/{self.key}/fichier/').status_code, 404)
        with override_settings(BIBMAN_FILES=self.dir / 'nope'):
            self.assertIn('BIBMAN_FILES', self.c.get(f'/p/{self.key}/').content.decode())

    def test_form_validation_datalist_and_warning(self):
        (self.dir / 'rapport.pdf').write_bytes(b'x')
        entry = Piece.objects.get(key=self.key).to_entry()
        page = self.c.get(f'/p/{self.key}/modifier/').content.decode()
        self.assertIn('<datalist id="files-list">', page)
        self.assertIn('<option value="rapport.pdf">', page)
        post = lambda **kw: self.c.post(f'/p/{self.key}/modifier/', {**dict(PieceForm.from_entry(entry).initial), **kw}, follow=True)
        self.assertIn('sans dossier', post(file='scans/rapport.pdf').content.decode())
        self.assertIn('sans dossier', post(file='..\\rapport.pdf').content.decode())
        self.assertNotIn('introuvable', post(file='rapport.pdf').content.decode())
        self.assertEqual(Piece.objects.get(key=self.key).file, 'rapport.pdf')
        self.assertIn('Fichier « absent.pdf » introuvable', post(file='absent.pdf').content.decode())

    def test_audit_file_checks(self):
        Piece.objects.filter(key=self.key).update(file='scans/rapport.pdf')
        Piece.objects.filter(key='2015-00-00-sigesfr-dogger').update(file='absent.pdf')
        bump()
        found = {c['id']: [d.key for d, _ in c['items']] for c in run_audit()}
        self.assertEqual(found['file-path'], [self.key])
        self.assertEqual(found['file-missing'], ['2015-00-00-sigesfr-dogger'])


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

    def test_help_page_and_date_form(self):
        html = self.c.get('/aide/').content.decode()
        self.assertIn('Plages de dates précises', html)
        self.assertIn('?q=date%3A1997-05-12..1998-03-01', html)
        self.assertIn('href="/aide/"', self.c.get('/').content.decode())
        r = self.c.get('/?du=2014-01-01&au=2014-12-31').content.decode()
        self.assertIn('2014-04-08-cassationcrim-1283214', r)
        self.assertNotIn('2015-00-00-sigesfr-dogger', r)
        self.assertIn('name="du" value="2014-01-01"', r)
        self.assertEqual(self.c.get('/?du=pas-une-date').status_code, 200)

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

    def test_detail_text_folded_by_default(self):
        self.assertIn('<details class="text">', self.c.get(f'/p/{self.key}/').content.decode())
        self.assertIn('<details class="text" open>', self.c.get(f'/p/{self.key}/?full=1').content.decode())

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

    def test_helper_lists_seeded_and_extended(self):
        self.assertEqual(helpers.choices('entrytype'), ['misc'])
        self.assertIn('géothermie', helpers.choices('xtheme'))
        self.assertIn('sigesfr', helpers.choices('xacronym'))
        page = self.c.get(f'/p/{self.key}/modifier/').content.decode()
        self.assertIn('<select name="xtheme"', page)
        self.assertIn('name="xtheme_new"', page)
        entry = Piece.objects.get(key=self.key).to_entry()
        self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, xtheme='dogger', xtheme_new=' sismique '), follow=True)
        self.assertEqual(Piece.objects.get(key=self.key).xtheme, 'sismique')
        self.assertIn('sismique', helpers.choices('xtheme'))
        self.c.post('/nouvelle/', {'key': '2026-01-01-new-0001', 'entrytype': 'misc', 'entrytype_new': 'techreport', 'markdown': ''})
        self.assertEqual(Piece.objects.get(key='2026-01-01-new-0001').entrytype, 'techreport')
        self.assertIn('techreport', helpers.choices('entrytype'))

    def test_date_validation_and_computed_year(self):
        entry = Piece.objects.get(key=self.key).to_entry()
        for bad in ['1997', '97-05-00', '1997-13-01', '1997-00-05', '1997-02-30', '1997-5-1', '0000-01-01']:
            r = self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, date=bad))
            self.assertEqual(r.status_code, 200, bad)
            self.assertTrue('Format attendu' in r.content.decode() or 'invalide' in r.content.decode() or 'impose' in r.content.decode(), bad)
        self.assertEqual(Piece.objects.get(key=self.key).date, '1997-05-00')
        for good, year in [('2024-02-29', '2024'), ('1998-00-00', '1998'), ('1999-12-00', '1999')]:
            self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, date=good, year='1111'), follow=True)
            p = Piece.objects.get(key=self.key)
            self.assertEqual((p.date, p.year), (good, year))          # le champ year envoyé est ignoré
        self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, date=''), follow=True)
        self.assertIsNone(Piece.objects.get(key=self.key).year)       # date effacée : année calculée supprimée
        legacy = Piece.objects.get(key='2008-00-00-acparisorg-0003')
        legacy.date = None
        legacy.save(update_fields=['date'])
        e = legacy.to_entry()
        self.c.post(f'/p/{legacy.key}/modifier/', self._post_data(e, title='Autre titre'), follow=True)
        self.assertEqual(Piece.objects.get(key=legacy.key).year, '2008')   # sans date : année héritée conservée
        self.assertIn('id="datepick"', self.c.get(f'/p/{self.key}/modifier/').content.decode())

    def test_rename_key_updates_shorthand(self):
        entry = Piece.objects.get(key=self.key).to_entry()
        page = self.c.get(f'/p/{self.key}/modifier/').content.decode()
        self.assertIn(f'name="key" value="{self.key}"', page)
        new = '1997-05-00-brgmfr-renamed'
        r = self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, key=new), follow=True)
        self.assertIn('Clé renommée', r.content.decode())
        self.assertEqual(r.redirect_chain[-1][0], f'/p/{new}/')
        self.assertFalse(Piece.objects.filter(key=self.key).exists())
        p = Piece.objects.get(key=new)
        self.assertEqual(p.shorthand, new)                                 # shorthand suit la clé
        self.assertEqual(p.to_entry()['key'], new)
        self.assertEqual(p.n, Piece.objects.get(key=new).n)
        self.assertIn(new, [d.key for d, _, _ in search.search('renamed').ranked])   # FTS et cache à jour
        self.assertEqual(self.c.get(f'/p/{self.key}/').status_code, 404)

    def test_rename_key_keeps_custom_shorthand_and_checks_uniqueness(self):
        entry = Piece.objects.get(key=self.key).to_entry()
        Piece.objects.filter(key=self.key).update(shorthand='Ignatiadis 1997')
        entry = Piece.objects.get(key=self.key).to_entry()
        self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, key='1997-05-00-brgmfr-x1'), follow=True)
        self.assertEqual(Piece.objects.get(key='1997-05-00-brgmfr-x1').shorthand, 'Ignatiadis 1997')   # personnalisé : conservé
        entry = Piece.objects.get(key='1997-05-00-brgmfr-x1').to_entry()
        self.c.post('/p/1997-05-00-brgmfr-x1/modifier/', self._post_data(entry, key='1997-05-00-brgmfr-x2', shorthand='Perso'), follow=True)
        self.assertEqual(Piece.objects.get(key='1997-05-00-brgmfr-x2').shorthand, 'Perso')              # modifié dans le formulaire : respecté
        r = self.c.post('/p/1997-05-00-brgmfr-x2/modifier/', self._post_data(entry, key='2015-00-00-sigesfr-dogger'))
        self.assertIn('existe déjà', r.content.decode())
        r = self.c.post('/p/1997-05-00-brgmfr-x2/modifier/', self._post_data(entry, key='a b/c'))
        self.assertIn('Clé invalide', r.content.decode())

    def test_time_timezone_and_xdatetime(self):
        entry = Piece.objects.get(key=self.key).to_entry()
        for bad in ['25:00', '9:5', '12:60', '1230']:
            r = self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, date='2014-04-08', xtime=bad))
            self.assertIn('Format attendu : HH:MM', r.content.decode(), bad)
        r = self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, xtime='14:30'))           # date 1997-05-00 incomplète
        self.assertIn('exige une date complète', r.content.decode())
        r = self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, date='2014-04-08', xtime='14:30', xtimezone='Mars/Olympus'))
        self.assertIn('Fuseau horaire inconnu', r.content.decode())

        def save(**kw):
            self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, **kw), follow=True)
            return Piece.objects.get(key=self.key)
        p = save(date='2014-04-08', xtime='14:30', xdatetime='ignoré')
        self.assertEqual((p.xtime, p.xtimezone, p.xdatetime), ('14:30', None, '2014-04-08T14:30'))   # sans fuseau : heure seule
        self.assertEqual(save(date='2014-04-08', xtime='14:30', xtimezone='Europe/Paris').xdatetime, '2014-04-08T14:30+02:00')
        self.assertEqual(save(date='2014-01-08', xtime='14:30', xtimezone='Europe/Paris').xdatetime, '2014-01-08T14:30+01:00')
        self.assertEqual(save(date='2014-01-08', xtime='00:00', xtimezone='America/New_York').xdatetime, '2014-01-08T00:00-05:00')
        self.assertEqual(save(date='2014-01-08', xtime='', xtimezone='Europe/Paris').xdatetime, None)  # heure effacée
        self.assertIn('<select name="xtimezone"', self.c.get(f'/p/{self.key}/modifier/').content.decode())
        self.assertIn('<option value="Europe/Paris"', self.c.get(f'/p/{self.key}/modifier/').content.decode())

    def test_xtimezone_column_added_to_old_database(self):
        from . import schema
        with connection.cursor() as c:
            c.execute('ALTER TABLE pieces DROP COLUMN xtimezone')
        schema._ok = False
        schema.ensure()
        with connection.cursor() as c:
            c.execute("SELECT name, dflt_value FROM pragma_table_info('pieces') WHERE name = 'xtimezone'")
            self.assertEqual(c.fetchall(), [('xtimezone', "'Europe/Paris'")])
            c.execute('SELECT COUNT(*) FROM pieces WHERE xtimezone IS NOT NULL')
            self.assertEqual(c.fetchone()[0], 0)                       # vide par défaut pour l'existant
        self.assertIsNone(Piece.objects.get(key=self.key).xtimezone)

    def test_raw_sql_under_debug_cursor(self):
        # DEBUG=True (runserver) formate la requête avec « sql % params » : un « ? » au lieu de « %s » y échoue
        connection.force_debug_cursor = True
        try:
            self.assertEqual(self.c.get(f'/p/{self.key}/modifier/').status_code, 200)
            HelperValue.objects.filter(field='keywords').delete()
            self.assertIn('nappe', helpers.choices('keywords'))
        finally:
            connection.force_debug_cursor = False

    def test_keywords_helper(self):
        self.assertEqual(helpers.choices('keywords'), ['corrosion', 'géothermie', 'nappe'])     # découpés sur « , » et « ; »
        page = self.c.get(f'/p/{self.key}/modifier/').content.decode()
        self.assertIn('data-multi="keywords"', page)
        self.assertIn('id="multi-values"', page)
        self.assertIn('multi.js', page)
        entry = Piece.objects.get(key=self.key).to_entry()
        self.c.post(f'/p/{self.key}/modifier/', self._post_data(entry, keywords='géothermie, corrosion;nouveau mot'), follow=True)
        self.assertEqual(Piece.objects.get(key=self.key).keywords, 'géothermie, corrosion;nouveau mot')   # texte saisi conservé tel quel
        self.assertIn('nouveau mot', helpers.choices('keywords'))
        HelperValue.objects.filter(field='keywords').delete()
        self.assertIn('nappe', helpers.choices('keywords'))                                       # champ multiple vide : rempli de nouveau

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
