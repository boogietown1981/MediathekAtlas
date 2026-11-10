"""Source-isolated scan state, bounded page windows and safe resume."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import portal_control as control
import portal_sources as portals
import catalog


class ScopeTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.c=sqlite3.connect(str(Path(self.tmp.name)/'test.sqlite'))
        self.c.row_factory=sqlite3.Row
        self.addCleanup(self.c.close)
        catalog.initialize(self.c)
        portals.initialize(self.c)
        control.initialize(self.c)
        self.c.commit()

    def test_default_all_scanners_are_off(self):
        d=control.source_status(self.c)
        self.assertEqual(d['active_platforms'],0)
        self.assertEqual(d['max_active_platforms'],3)
        self.assertEqual(len(d['platforms']),2)
        with self.assertRaisesRegex(ValueError,'keine automatische'):
            with self.c:control.set_controls(self.c,source='netzkino',enabled=True)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM portal_items').fetchone()[0],0)

    def test_source_scope_input_and_bounded_page_budget(self):
        with self.c:
            ident=control.add_scope(self.c,'item','https://archive.org/details/Film_1998',
                                    page_budget=2)
        self.assertIsInstance(ident,int)
        self.assertEqual(control.list_scopes(self.c)[0]['scope'],'Film_1998')
        for bad in ('http://archive.org/details/Film_1998',
                    'https://example.org/details/Film_1998',
                    'https://archive.org.evil.org/details/Film_1998',
                    'https://archive.org/details/../../x'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                control.normalize_scope('item',bad)
        for bad in (0,26,-1):
            with self.subTest(n=bad),self.assertRaises(ValueError):
                control.add_scope(self.c,'collection','Collection_2020',page_budget=bad)

    def test_only_active_enabled_source_claims_queue(self):
        with self.c:
            aid=control.add_scope(self.c,'collection','classic_films',page_budget=2)
            control.control_scope(self.c,aid,'start')
        with self.c:
            self.assertIsNone(control._claim(self.c))  # Platform disabled
        with self.c:control.set_controls(self.c,source='internet_archive',enabled=True,workers=2)
        with self.c:
            claimed=control._claim(self.c)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed['id'],aid)
        self.assertEqual(claimed['cursor'],1)
        with self.c:
            # Source isolation: no MediathekView offers, jobs or works mutated.
            control.finish(self.c,aid,[],more=True)
        row=control.list_scopes(self.c)[0]
        self.assertEqual((row['state'],row['cursor'],row['pages_done']),('queued',2,1))
        with self.c:claimed=control._claim(self.c)
        self.assertEqual(claimed['cursor'],2)
        with self.c:control.finish(self.c,aid,[],more=True)
        row=control.list_scopes(self.c)[0]
        self.assertEqual(row['state'],'paused')
        self.assertEqual((row['cursor'],row['run_pages']), (3,2))
        with self.c:control.control_scope(self.c,aid,'start')
        row=control.list_scopes(self.c)[0]
        self.assertEqual((row['cursor'],row['run_pages']), (3,0))
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM works').fetchone()[0],0)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM offers').fetchone()[0],0)

    def test_running_scope_recovers_without_resetting_cursor(self):
        with self.c:
            ident=control.add_scope(self.c,'uploader','@OfficialFilmArchive')
            control.set_controls(self.c,source='internet_archive',enabled=True)
            control.control_scope(self.c,ident,'start')
            self.c.execute("UPDATE portal_scopes SET state='running',cursor=7,pages_done=6 WHERE id=?",(ident,))
        with self.c:control.initialize(self.c)
        row=control.list_scopes(self.c)[0]
        self.assertEqual((row['state'],row['cursor'],row['pages_done']),('queued',7,6))

    def test_uploader_priority_before_collection(self):
        with self.c:
            col=control.add_scope(self.c,'collection','movie_collection')
            uploader=control.add_scope(self.c,'uploader','@Cinematheque')
            control.set_controls(self.c,source='internet_archive',enabled=True)
            control.control_scope(self.c,col,'start')
            control.control_scope(self.c,uploader,'start')
        with self.c:job=control._claim(self.c)
        self.assertEqual(job['id'],uploader)
        self.assertEqual(job['kind'],'uploader')
        self.assertIn('_uploader_useritem',control.archive_scope_query(job))
        self.assertNotIn('creator:',control.archive_scope_query(job))

    def test_scope_failure_is_backed_off_and_later_retryable(self):
        with self.c:
            sid=control.add_scope(self.c,'collection','movies_1980')
            control.set_controls(self.c,source='internet_archive',enabled=True)
            control.control_scope(self.c,sid,'start')
        with self.c:task=control._claim(self.c)
        with self.c:control.failure(self.c,sid,TimeoutError('Timed out'))
        state=control.list_scopes(self.c)[0]
        self.assertEqual(state['state'],'retry')
        self.assertEqual(state['failures'],1)
        self.assertEqual(state['cursor'],1)
        self.assertIn('TimeoutError',state['last_error'])
        with self.c:self.assertIsNone(control._claim(self.c))

    def test_platform_limit_is_distinct_from_workers(self):
        with self.c:
            control.set_controls(self.c,max_active=5)
            control.set_controls(self.c,source='internet_archive',workers=2)
        status=control.source_status(self.c)
        self.assertEqual(status['max_active_platforms'],5)
        self.assertEqual(status['active_platforms'],0)
        with self.assertRaisesRegex(ValueError,'1 bis 5'):
            with self.c:control.set_controls(self.c,max_active=6)


if __name__=='__main__':unittest.main()
