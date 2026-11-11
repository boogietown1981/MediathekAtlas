"""0.5.31.11 preflight, complete patch application and non-destructive runtime tests.

The macOS app is assembled from pinned PRs; this suite verifies the new additive
patch against the prior preview's real Netzkino code plus exact legacy anchors.
"""
from __future__ import annotations
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import apply_053110,apply_053111

class IntegrationFixture(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=pathlib.Path(temp.name)
        for name in ('netzkino.py','diagnostic_extensions.py','netzkino_webplayer.swift',
                     'web/netzkino.js','web/netzkino_detail.js','web/unified_catalog.js'):
            dest=self.root/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,dest)
        for name in ('archive_companion.py','portal_control.py','netzkino_downloads.py',
                     'yt_dlp_probe.py','netzkino_enrichment.py','portal_sources.py',
                     'catalog.py','video_backfill.py'):
            (self.root/name).write_text('preserved module\n')
        # The 0.5.31.10 base builder checks the 0.5.31.9 API names.
        (self.root/'web/netzkino_detail.js').write_text((self.root/'web/netzkino_detail.js').read_text()+'\n// window.AtlasNetzkinoDownloads\n')
        (self.root/'server.py').write_text('''# /api/netzkino-downloads /api/archive-companion /api/netzkino-watch
# /api/netzkino-metadata-probe /api/video-audit /api/netzkino-enrich
# /api/netzkino-grouped
                diagnostics.event('netzkino_official_player',mode='official_browser')
                return self.send({'mode':'official_browser','page_url':page})
''')
        (self.root/'web/index.html').write_text('''<div id="archive-full-mode"></div>
<div id="atlas-nk-downloads"></div><div id="atlas-nk-reference"></div>
<button data-catalog-source="all"></button><summary>Download / Offline-Nutzung</summary>
<small id="metadata-workers-status" class="muted">Worker werden gestartet …</small>
''')
        (self.root/'version.py').write_text("VERSION='0.5.31.9'")
        (self.root/'build_macos.py').write_text("bundle={'CFBundleVersion':'519'}")
        (self.root/'CHANGELOG.md').write_text('# Changelog\n')
        (self.root/'web/style.css').write_text('.background-status{display:block;}')
        (self.root/'web/app.js').write_text('''function catalogProgress(c) {
   const workers=document.getElementById('metadata-workers-status');
   const chips=[];
   workers.replaceChildren();
   for(const [kind,label] of chips){
     const item=el('span',label,'atlas-worker-chip');
     item.dataset.kind=kind;
     workers.append(item);
   }
   workers.append(el('span','Externe Anbieteranfragen bleiben auf zwei gleichzeitig begrenzt.','atlas-worker-hint'));
}
function renderMetadata(m,settings,pauses){
const providers=[
  ['OMDb',pauses.omdb?.paused?'Pausiert · '+Math.ceil(pauses.omdb.remaining_seconds/60)+' Min.':settings.omdb_set?'Eingerichtet':'Kein Schlüssel',!!settings.omdb_set&&!pauses.omdb?.paused],
];}
''')
        (self.root/'catalog_service.py').write_text('''import json
class Service:
    def pick_episode(self,c):
        row=c.execute(query+scope+" ORDER BY q.next_try ASC LIMIT 1",
                         (now,now)+params).fetchone()
        return row

    def pick(self,c):
        return None
''')
        # Replace simplified picker with the exact tail from the repo.
        p=self.root/'catalog_service.py';p.write_text(p.read_text().replace('''        row=c.execute(query+scope+" ORDER BY q.next_try ASC LIMIT 1",
                         (now,now)+params).fetchone()
        return row''','''        return c.execute(query+scope+" ORDER BY q.next_try ASC LIMIT 1",
                         (now,now)+params).fetchone()'''))
        (self.root/'metadata.py').write_text('''def tmdb_candidates(row,meta,key,kind,title):
    import core, diagnostics
    d={'id':22}
    c={'episode_scan_complete':True,'episode_verified':False}
    seasons=[{'season_number':1},{'season_number':2}]
    episodes=[]
    epmeta={}
    def resolve_episode(meta,c,episodes):
        c['episode_verified']=True
    if kind=='series':
            for season in seasons[:24]:
                number=season.get('season_number')
                if number is None:continue
                episodes.extend(core.tmdb(f"tv/{d['id']}/season/{number}",key).get('episodes',[]))
            resolve_episode(epmeta,c,episodes)
            if not c['episode_scan_complete'] and meta.get('season') is None:c['episode_verified']=False
    return c
''')
        # Patch through the existing 0.5.31.10 stage to prove chain parity.
        apply_053110.patch(self.root)

    def test_preflight_does_not_change_any_file(self):
        watched=('netzkino.py','web/index.html','web/app.js','catalog_service.py',
                 'metadata.py','web/unified_catalog.js','version.py')
        before={n:(self.root/n).read_bytes() for n in watched}
        self.assertIn('catalog_service.py',apply_053111.patch(self.root,dry_run=True))
        self.assertEqual(before,{n:(self.root/n).read_bytes() for n in watched})

    def test_complete_patch_and_module_preservation(self):
        protected=['archive_companion.py','portal_sources.py','portal_control.py',
                   'netzkino_downloads.py','yt_dlp_probe.py','netzkino_enrichment.py','video_backfill.py']
        before={x:(self.root/x).read_bytes() for x in protected}
        apply_053111.patch(self.root)
        self.assertEqual(before,{x:(self.root/x).read_bytes() for x in protected})
        self.assertEqual((self.root/'version.py').read_text(),"VERSION='0.5.31.11'")
        self.assertIn('atlas-main-dashboard',(self.root/'web/unified_catalog.js').read_text())
        self.assertIn('atlas-worker-group',(self.root/'web/app.js').read_text())
        self.assertIn('tmdb_season_unavailable',(self.root/'metadata.py').read_text())
        self.assertIn('LIMIT 48',(self.root/'catalog_service.py').read_text())
        self.assertIn('category_over_20',(self.root/'netzkino.py').read_text())
        with self.assertRaises(RuntimeError):apply_053111.patch(self.root,dry_run=True)

    def test_category_31_does_not_count_as_twenty_item_limit(self):
        apply_053111.patch(self.root)
        spec=importlib.util.spec_from_file_location('netzkino_v053111_fixture',self.root/'netzkino.py')
        nk=importlib.util.module_from_spec(spec);spec.loader.exec_module(nk)
        def movie(i):return {'contentMovie':{'id':f'nk{i}','title':f'Titel {i}','slug':f'titel-{i}','flags':[]}}
        home={'parentCategory':{'title':'Home','subcategories':{'nodes':[
          {'title':'Deutsch','slug':'deutsche-filme-frontpage','content':{'nodes':[movie(0)]}}]}}}
        category={'category':{'title':'Deutsch','content':{'nodes':[movie(i) for i in range(31)]}}}
        out=nk.sync_graphql(self.root/'data',fetch=lambda op,vs:home if op=='AllContent' else category,now=1010)
        self.assertTrue(out['ok'])
        self.assertEqual(out['category_max_items'],31)
        self.assertEqual(out['category_over_20'],1)
        self.assertEqual(out['category_cap_hits'],1) # legacy label means >=20, not capped
        status=nk.state(self.root/'data')
        self.assertEqual(status['category_max_items'],31)
        self.assertEqual(status['coverage_status'],'startpage_only')

    def test_queue_evidence_priority_is_read_only(self):
        apply_053111.patch(self.root)
        spec=importlib.util.spec_from_file_location('queue053111',self.root/'catalog_service.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        mod.query='SELECT * FROM episode_queue WHERE next_try<=?'
        mod.scope='';mod.now=1;mod.params=()
        import json
        ordered=[{'id':'old','meta':json.dumps({'title':'Serie'})},
                 {'id':'numbered','meta':json.dumps({'season':2,'episode':3})},
                 {'id':'sender','meta':json.dumps({'sender_page_id':'abc'})}]
        class Cursor:
            def fetchall(self):return ordered
        class DB:
            def __init__(self):self.calls=[]
            def execute(self,sql,params):
                self.calls.append((sql,params));return Cursor()
        db=DB()
        selected=mod.Service().pick_episode(db)
        self.assertEqual(selected['id'],'numbered')
        self.assertIn('LIMIT 48',db.calls[0][0])
        self.assertEqual(len(db.calls),1)
        # No DB writes, existing order remains intact.
        self.assertEqual([r['id'] for r in ordered],['old','numbered','sender'])

    def test_tmdb_missing_season_retains_show_but_blocks_episode_verification(self):
        apply_053111.patch(self.root)
        import types
        fakecore=types.ModuleType('core')
        def tmdb(path,key):
            if path.endswith('season/1'):raise ValueError('Dienst antwortet mit HTTP 404')
            return {'episodes':[{'id':12,'name':'Test'}]}
        fakecore.tmdb=tmdb
        diagnostics=types.ModuleType('diagnostics')
        events=[];diagnostics.event=lambda event,**kwargs:events.append((event,kwargs))
        oldcore=sys.modules.get('core');olddiag=sys.modules.get('diagnostics')
        try:
            sys.modules['core']=fakecore;sys.modules['diagnostics']=diagnostics
            spec=importlib.util.spec_from_file_location('metadata053111',self.root/'metadata.py')
            mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
            out=mod.tmdb_candidates({}, {'kind':'series'},'test','series','Titel')
            self.assertFalse(out['episode_scan_complete'])
            self.assertFalse(out['episode_verified'])
            self.assertIn('Serienmetadaten erkannt',out['reason'])
            self.assertEqual(events[0][0],'tmdb_season_unavailable')
            # Real API outages other than isolated 404 must still propagate.
            fakecore.tmdb=lambda *a: (_ for _ in ()).throw(ValueError('HTTP 429'))
            with self.assertRaisesRegex(ValueError,'429'):
                mod.tmdb_candidates({}, {'kind':'series'},'test','series','Titel')
        finally:
            if oldcore is None:sys.modules.pop('core',None)
            else:sys.modules['core']=oldcore
            if olddiag is None:sys.modules.pop('diagnostics',None)
            else:sys.modules['diagnostics']=olddiag

    def test_javascript_and_shell_syntax(self):
        apply_053111.patch(self.root)
        if shutil.which('node'):
            for name in ('app.js','netzkino.js','unified_catalog.js'):
                subprocess.run(['node','--check',str(self.root/'web'/name)],check=True,capture_output=True)
        script=ROOT/'Netzkino-Testversion-bauen.command'
        subprocess.run(['bash','-n',str(script)],check=True,capture_output=True)
        body=script.read_text()
        self.assertIn('[12/16]',body)
        self.assertIn('apply_053111.py',body)
        self.assertIn('0.5.31.11-Integration-Test.app',body)
        self.assertIn('ArchiveMedia-PR24-Quelle',body)

    def test_unsafe_previous_version_blocks_changes(self):
        (self.root/'version.py').write_text("VERSION='0.5.31.8'")
        before=(self.root/'catalog_service.py').read_bytes()
        with self.assertRaises(RuntimeError):apply_053111.patch(self.root)
        self.assertEqual(before,(self.root/'catalog_service.py').read_bytes())

if __name__=='__main__':unittest.main()
