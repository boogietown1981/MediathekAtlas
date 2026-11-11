"""Netzkino series consolidation regression tests; no network or app data touched."""
import json, os, pathlib, tempfile, unittest, sys
from unittest.mock import patch
HERE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import netzkino, diagnostic_extensions

class NetzkinoGroupingTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=pathlib.Path(tmp.name)

    def test_episode_patterns_only_not_film_series(self):
        cases=[
            ('Acapulco H.E.A.T. Staffel 1 - 22. Happy Birthday','episode',1,22,'Acapulco H.E.A.T.'),
            ('Tiere rüsten auf - Folge 3: Ozeane','episode',None,3,'Tiere rüsten auf'),
            ('Muster S02E03 - Episodentitel','episode',2,3,'Muster'),
            ('Muster 2x03: Episodentitel','episode',2,3,'Muster'),
            ('Freitag der 13. Teil VI - Jason lebt','movie',None,None,''),
            ('Vera Brühne Teil 1','movie',None,None,''),
            ('Mary Higgins Clark: Das fremde Gesicht','movie',None,None,''),
            ('Trailer Park Boys','movie',None,None,'')]
        for title,kind,season,episode,show in cases:
            with self.subTest(title=title):
                got=netzkino.classify_media({'kind':'movie','title':title})
                self.assertEqual((got['media_type'],got['season'],got['episode'],got['series_title']),
                                 (kind,season,episode,show))
        self.assertEqual(netzkino.classify_media({'kind':'series','title':'Robocop die Serie'})['media_type'],'series')

    def test_har_snapshot_movies_and_episode_groups(self):
        with patch.dict(os.environ,{'MEDIATHEKATLAS_HOME':str(self.root)}):
            movie=netzkino.grouped_catalog(self.root,view='movies')
            series=netzkino.grouped_catalog(self.root,view='series')
            self.assertEqual(series['counts'],{'movies':418,'series':11,'episodes':22})
            self.assertEqual(movie['total'],418)
            self.assertEqual(series['total'],11)
            self.assertEqual(len(movie['items']),80)
            acapulco=next(r for r in series['items'] if r['title']=='Acapulco H.E.A.T.')
            self.assertEqual(acapulco['episode_count'],20)
            self.assertEqual(acapulco['seasons'],[1])
            self.assertEqual(acapulco['series_url'],'')  # no invented official show page
            ep=netzkino.grouped_catalog(self.root,view='episodes',series_key=acapulco['series_key'])
            self.assertEqual(ep['total'],20)
            self.assertEqual([r['episode'] for r in ep['items']][:3],[1,2,5])
            self.assertEqual(acapulco['numbering_gaps'],[{'season':1,'episodes':[3,4]}])
            self.assertEqual(ep['series']['title'],'Acapulco H.E.A.T.')
            self.assertTrue(all(r['url'].startswith('https://www.netzkino.de/details/') for r in ep['items']))
            self.assertFalse(any('Acapulco H.E.A.T.' in r['title'] for r in movie['items']))
            self.assertEqual(netzkino.count_links(self.root),449) # original storage unchanged
            diag=diagnostic_extensions.netzkino(self.root)
            self.assertEqual(diag['media_classification']['episodes'],22)
            self.assertEqual(diag['media_classification']['series_groups'],11)
            self.assertEqual(diag['media_classification']['movies'],418)
            self.assertFalse(diag['media_classification']['database_modified'])

    def test_group_persists_after_restart_and_manual_link_overrides(self):
        with patch.dict(os.environ,{'MEDIATHEKATLAS_HOME':str(self.root)}):
            original=netzkino.grouped_catalog(self.root,view='series')
            key=next(i['series_key'] for i in original['items'] if i['title']=='Tiere rüsten auf')
            row=netzkino.grouped_catalog(self.root,view='episodes',series_key=key)['items'][0]
            netzkino.add(self.root,'Tiere rüsten auf - Folge 1: Dschungel',row['url'])
            all_=netzkino.grouped_catalog(self.root,view='episodes',series_key=key)
            self.assertEqual(all_['total'],2)
            self.assertEqual(sum(i['origin']=='manual' for i in all_['items']),1)
            self.assertEqual(netzkino.grouped_catalog(self.root,view='series')['counts']['episodes'],22)
            self.assertEqual(netzkino.grouped_catalog(self.root,view='series')['counts']['series'],11)

    def test_search_and_pagination_and_input_validation(self):
        with patch.dict(os.environ,{'MEDIATHEKATLAS_HOME':str(self.root)}):
            group=netzkino.grouped_catalog(self.root,view='series',query='Acapulco')['items'][0]
            first=netzkino.grouped_catalog(self.root,view='episodes',series_key=group['series_key'],limit=5,offset=0)
            sixth=netzkino.grouped_catalog(self.root,view='episodes',series_key=group['series_key'],limit=5,offset=5)
            self.assertEqual(len(first['items']),5)
            self.assertEqual(sixth['items'][0]['episode'],8)
            self.assertEqual(netzkino.grouped_catalog(self.root,view='movies',query='Freitag der 13')['total'],5)
            self.assertEqual(netzkino.grouped_catalog(self.root,view='series',query='Happy Birthday')['total'],1)
            with self.assertRaises(ValueError):netzkino.grouped_catalog(self.root,view='episodes',series_key='123')
            with self.assertRaises(ValueError):netzkino.grouped_catalog(self.root,view='bad')

if __name__=='__main__':unittest.main()
