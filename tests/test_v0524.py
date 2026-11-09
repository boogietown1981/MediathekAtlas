"""0.5.24: targeted news bypass, film-first unknown hints and exact statistics."""
import json,sqlite3,threading,unittest
from pathlib import Path
import catalog,catalog_service

def offer(title,topic,duration=1800,desc='Eine neue Ausgabe der Sendung',
          channel='ZDF',tag=None):
    return {'title':title,'topic':topic,'duration':duration,'description':desc,
            'channel':channel,'url_video':'https://media.example.org/'+(tag or title.replace(' ','-'))+'.mp4'}

class V0524Tests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript(catalog.SCHEMA)
        self.stop=threading.Event()
    def tearDown(self):self.c.close()
    def work(self,title):
        return self.c.execute('SELECT * FROM works WHERE title=?',(title,)).fetchone()
    def service(self,priority='movies_first'):
        return catalog_service.Service(None,lambda:{'scan_priority':priority,'complete_series':False},
                                       self.stop,Path('.'))
    def test_news_format_before_any_provider_call(self):
        rows=[
            offer('heute journal vom Montag','heute journal',1200,tag='h1'),
            offer('heute in Europa: Schlagzeilen','heute – in Deutschland',1200,tag='h2'),
            offer('hallo deutschland vom Freitag','hallo deutschland',1800,tag='h3')]
        catalog.ingest(self.c,rows)
        for row in self.c.execute('SELECT * FROM works').fetchall():
            item=catalog.item(self.c,row)
            self.assertTrue(catalog.mark_news_format(self.c,row,item['source']))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM works WHERE state='format'").fetchone()[0],3)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM works WHERE kind='series'").fetchone()[0],3)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM metadata_priority").fetchone()[0],0)
    def test_external_identification_of_news_is_no_reason_for_further_series_lookups(self):
        catalog.ingest(self.c,[offer('Nachrichtenausgabe 18 Uhr','heute journal',1500)])
        w=self.c.execute('SELECT * FROM works').fetchone()
        m=json.loads(w['meta']);m.update(kind='series',provider='TMDB',title='heute journal',reference_id='999')
        self.c.execute("UPDATE works SET kind='series',state='identified',meta=? WHERE id=?",(json.dumps(m),w['id']))
        w=self.c.execute('SELECT * FROM works').fetchone()
        self.assertTrue(catalog.mark_news_format(self.c,w,catalog.item(self.c,w)['source']))
        m=json.loads(self.c.execute('SELECT meta FROM works').fetchone()[0])
        self.assertEqual(m['provider'],'TMDB')
        self.assertEqual(m['format_grouping'],'news')
    def test_verified_episode_manual_or_user_priority_are_not_overwritten(self):
        catalog.ingest(self.c,[offer('heute journal Spezial','heute journal')])
        row=self.c.execute('SELECT * FROM works').fetchone()
        catalog.prioritize(self.c,ids=[row['id']])
        row=self.c.execute('SELECT * FROM works').fetchone()
        self.assertFalse(catalog.mark_news_format(self.c,row,catalog.item(self.c,row)['source']))
        self.assertEqual(row['state'],'pending')
        self.c.execute('DELETE FROM metadata_priority')
        m=json.loads(row['meta']);m['episode_verified']=True;m.pop('scan_requested',None)
        self.c.execute('UPDATE works SET meta=? WHERE id=?',(json.dumps(m),row['id']))
        row=self.c.execute('SELECT * FROM works').fetchone()
        self.assertFalse(catalog.mark_news_format(self.c,row,catalog.item(self.c,row)['source']))
        self.c.execute("UPDATE works SET state='matched' WHERE id=?",(row['id'],))
        row=self.c.execute('SELECT * FROM works').fetchone()
        self.assertFalse(catalog.mark_news_format(self.c,row,catalog.item(self.c,row)['source']))
    def test_similar_movie_and_satire_titles_are_not_news(self):
        catalog.ingest(self.c,[
            offer('heute journal','Film',6600,'Spielfilm von 2021',tag='movie'),
            offer('heute-show Folge 1','heute-show',2600,'Politische Comedy',tag='satire'),
            offer('Heute in Europa – Dokumentarfilm','Dokumentation',5400,'Ein Dokumentarfilm',tag='doc')
        ])
        for row in self.c.execute('SELECT * FROM works').fetchall():
            self.assertFalse(catalog.is_news_contribution(row,catalog.item(self.c,row)['source']))
    def test_news_format_upgrade_can_reclassify_old_identified_news(self):
        catalog.ingest(self.c,[offer('heute journal','heute journal',1400,tag='old')])
        w=self.c.execute('SELECT * FROM works').fetchone()
        m=json.loads(w['meta']);m.update(kind='series',provider='TVDB',title='heute journal',reference_id='80')
        self.c.execute("UPDATE works SET kind='series',state='identified',meta=? WHERE id=?",(json.dumps(m),w['id']))
        self.assertEqual(catalog.assign_formats(self.c,limit=100)[1],1)
        self.assertEqual(self.c.execute('SELECT state FROM works').fetchone()[0],'format')
    def test_film_hint_promotes_unknown_rubric_without_marking_it_as_film(self):
        row=offer('Der unbekannte Abend','Spielfilme',7200,'Eine abendfüllende Geschichte',tag='film')
        catalog.ingest(self.c,[row,offer('Eine neue Folge','Ein ZDF Format',1600,tag='series')])
        films=self.c.execute("SELECT w.* FROM film_hints h JOIN works w ON w.id=h.work_id").fetchall()
        self.assertEqual(len(films),1)
        self.assertEqual(films[0]['kind'],'unknown')
        self.assertEqual(self.service().pick(self.c)['id'],films[0]['id'])
    def test_film_hint_keeps_news_and_short_magazines_out(self):
        self.assertEqual(catalog.film_likelihood(offer('News','heute journal',7200,'Spielfilm'))[0],0)
        self.assertEqual(catalog.film_likelihood(offer('Movie','Spielfilme',120,''))[0],0)
        self.assertEqual(catalog.film_likelihood(offer('Movie','Spielfilme',7200,''))[0],3)
        self.assertEqual(catalog.film_likelihood(offer('Movie','Unbekannt',7200,'Ein Spielfilm'))[0],2)
    def test_backfill_is_resumable_and_idempotent(self):
        catalog.ingest(self.c,[offer('Der unbekannte Abend','Spielfilme',7200,tag='film')])
        self.c.execute('DELETE FROM film_hints')
        a=catalog.backfill_film_hints(self.c,limit=1)
        b=catalog.backfill_film_hints(self.c,limit=1)
        self.assertEqual((a,b),(1,0))
        self.assertEqual(catalog.get_state(self.c,'film_hint_cursor_v0524'),'complete')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM film_hints').fetchone()[0],1)
    def test_grouped_dashboard_stats_remain_numerically_consistent(self):
        catalog.ingest(self.c,[offer('A','Spielfilme',7200,tag='a'),
                               offer('B','heute journal',1200,tag='b'),
                               offer('C','Fernsehserie',1800,desc='Eine Fernsehserie',tag='c')])
        stats=catalog.stats(self.c)
        self.assertEqual(stats['works'],sum(stats['types'].values()))
        self.assertEqual(stats['offers'],3)
        self.assertEqual(stats['first_pass_remaining'],3)
        self.assertEqual(stats['film_hints'],1)
        w=self.c.execute("SELECT * FROM works WHERE title='B'").fetchone()
        self.assertTrue(catalog.mark_news_format(self.c,w,catalog.item(self.c,w)['source']))
        newer=catalog.stats(self.c)
        self.assertEqual(newer['formats'],1)
        self.assertEqual(newer['first_pass_remaining'],2)
        self.assertEqual(newer['film_hints'],1)

if __name__=='__main__':unittest.main()
