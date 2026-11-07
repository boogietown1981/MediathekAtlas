"""0.5.21: movie identity reconciliation must not depend on genres."""
import json,sqlite3,time,unittest
import catalog

def row(title='Der Rausch',channel='ARD',description='Spielfilm mit einer ausführlichen Handlung A',duration=7000):
    return {'title':title,'topic':'Spielfilm','channel':channel,
            'description':description,'duration':duration,
            'url_video':'https://example.org/'+channel+'/'+title.replace(' ','-')+'.mp4'}

def meta(source,provider,reference,year,genres):
    m=catalog.seed(source)
    m.update(title='Der Rausch',kind='movie',year=year,provider=provider,
             reference_id=reference,genres=genres,genre_source=provider,
             runtime_agrees=True,similarity=1.0)
    return m

class FilmDedupTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript(catalog.SCHEMA)
        self.a=row()
        self.b=row(channel='ZDF',description='Spielfilm ganz anderer Wortlaut B',duration=7060)
        catalog.ingest(self.c,[self.a,self.b])
        self.ids=[r[0] for r in self.c.execute("SELECT id FROM works ORDER BY id")]
        self.assertEqual(len(self.ids),2)
    def tearDown(self):self.c.close()
    def fill(self,year=2020,provider_a='TMDB',provider_b='IMDb Offline',
             reference_a='72345',reference_b='tt10288566',duration_b=None):
        if duration_b is not None:
            self.c.execute("UPDATE offers SET payload=json_set(payload,'$.duration',?) WHERE json_extract(payload,'$.channel')='ZDF'",(duration_b,))
        a=catalog.save_metadata(self.c,self.ids[0],meta(self.a,provider_a,reference_a,year,['Komödie','Drama']),'matched')
        b=catalog.save_metadata(self.c,self.ids[1],meta(self.b,provider_b,reference_b,year,['Drama']),'matched')
        return a,b
    def test_two_provider_identities_become_one_film_and_keep_both_genres(self):
        a,b=self.fill()
        works=self.c.execute('SELECT * FROM works').fetchall()
        self.assertEqual(len(works),1)
        m=json.loads(works[0]['meta'])
        self.assertEqual(m['genres'],['Drama','Komödie'])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM offers').fetchone()[0],2)
        self.assertEqual(len(set(r[0] for r in self.c.execute('SELECT work_id FROM offers'))),1)
        self.assertEqual({r[0] for r in self.c.execute('SELECT genre FROM work_genres')},{'Drama','Komödie'})
        self.assertEqual(catalog.listing(self.c,kind='movie')['total'],1)
        self.assertEqual(catalog.listing(self.c,kind='movie',genre='Drama')['total'],1)
        self.assertEqual(catalog.listing(self.c,kind='movie',genre='Komödie')['total'],1)
        self.assertEqual(catalog.get_state(self.c,'movie_dedup_total_v0521'),1)
    def test_different_production_year_never_merges(self):
        catalog.save_metadata(self.c,self.ids[0],meta(self.a,'TMDB','1',2020,['Drama']),'matched')
        catalog.save_metadata(self.c,self.ids[1],meta(self.b,'IMDb Offline','tt2',2019,['Drama']),'matched')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM works').fetchone()[0],2)
    def test_conflicting_ids_from_same_provider_never_merge(self):
        self.fill(provider_a='TMDB',provider_b='TMDB',reference_a='10',reference_b='20')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM works').fetchone()[0],2)
    def test_incompatible_runtimes_never_merge(self):
        self.fill(duration_b=8600)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM works').fetchone()[0],2)
    def test_unverified_title_only_never_merges(self):
        catalog.save_metadata(self.c,self.ids[0],meta(self.a,'TMDB','10',2020,['Drama']),'identified')
        catalog.save_metadata(self.c,self.ids[1],meta(self.b,'IMDb Offline','tt2',2020,['Drama']),'matched')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM works').fetchone()[0],2)
    def test_manual_metadata_and_download_reference_preserved(self):
        first=catalog.save_metadata(self.c,self.ids[0],meta(self.a,'TMDB','10',2020,['Drama']),'manual')
        self.c.execute('INSERT INTO downloaded_items VALUES(?,?,?)',(self.ids[1],'/movie.mkv',time.time()))
        second=catalog.save_metadata(self.c,self.ids[1],meta(self.b,'IMDb Offline','tt2',2020,['Komödie']),'matched')
        w=self.c.execute('SELECT * FROM works').fetchone()
        self.assertEqual((w['id'],w['state']),(first,'manual'))
        self.assertEqual(json.loads(w['meta'])['genres'],['Drama'])
        self.assertIsNotNone(self.c.execute('SELECT path FROM downloaded_items WHERE identity=?',(first,)).fetchone())
        self.assertEqual(catalog.source(self.c,self.c.execute('SELECT id FROM offers WHERE work_id=? LIMIT 1',(first,)).fetchone()[0])['title'],'Der Rausch')
    def test_legacy_background_scan_persists_and_is_idempotent(self):
        for original,source,provider,ref,genre in [
            (self.ids[0],self.a,'TMDB','10',['Komödie','Drama']),
            (self.ids[1],self.b,'IMDb Offline','tt2',['Drama'])]:
            m=meta(source,provider,ref,2020,genre)
            self.c.execute("UPDATE works SET title=?,year=?,kind='movie',state='matched',meta=? WHERE id=?",
                           ('Der Rausch',2020,json.dumps(m),original))
        n,merged=catalog.deduplicate_movie_batch(self.c,limit=10)
        self.assertEqual((n,merged),(2,1))
        catalog.deduplicate_movie_batch(self.c,limit=10)
        self.assertEqual(catalog.get_state(self.c,'movie_dedup_cursor_v0521'),'complete')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM works').fetchone()[0],1)
        self.assertEqual(catalog.get_state(self.c,'movie_dedup_total_v0521'),1)
    def test_same_canonical_id_does_not_erase_richer_genre_list(self):
        a=catalog.save_metadata(self.c,self.ids[0],meta(self.a,'TMDB','10',2020,['Komödie','Drama']),'matched')
        catalog.save_metadata(self.c,self.ids[1],meta(self.b,'TMDB','10',2020,['Drama']),'matched')
        final=json.loads(self.c.execute('SELECT meta FROM works WHERE id=?',(a,)).fetchone()[0])
        self.assertEqual(final['genres'],['Drama','Komödie'])
        self.assertEqual(catalog.listing(self.c,kind='movie')['total'],1)

if __name__=='__main__':unittest.main()
