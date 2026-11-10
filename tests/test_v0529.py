"""Regression tests for the responsive 0.5.29 catalog dashboard."""
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CSS=(ROOT/'web'/'style.css').read_text(encoding='utf-8')
JS=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
HTML=(ROOT/'web'/'index.html').read_text(encoding='utf-8')


class ElementIds(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids={}
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if 'id' in d:self.ids[d['id']]=tag


class DashboardResponsiveTests(unittest.TestCase):
    def test_ten_metrics_form_two_equal_rows_at_full_width(self):
        fields=JS.split('const atlasStatusFields=[',1)[1].split('];',1)[0]
        self.assertEqual(len(re.findall(r"\['[a-z_]+','",fields)),10)
        self.assertRegex(CSS,r'\.atlas-status-grid\s*\{[^}]*grid-template-columns:repeat\(5,minmax\(0,1fr\)\)')
        self.assertNotRegex(CSS,r'@container\s*\(min-width:\s*1320px\)\s*\{\.atlas-status-grid\{grid-template-columns:repeat\(8,')

    def test_grid_changes_at_available_container_width(self):
        self.assertIn('container-type:inline-size',CSS)
        widths={'979':4,'779':3,'609':2,'419':1}
        for width,columns in widths.items():
            with self.subTest(width=width):
                # Avoid regexp escaping of CSS function parentheses.
                query='@container (max-width:'+width+'px)'
                self.assertIn(query,CSS)
                section=CSS.split(query,1)[1].split('}',1)[0]
                template=('repeat('+str(columns)+',minmax(0,1fr))'
                          if columns>1 else 'minmax(0,1fr)')
                self.assertIn('grid-template-columns:'+template,section)

    def test_cards_stretch_and_wrap_numeric_values(self):
        self.assertIn('grid-auto-rows:minmax(116px,1fr)',CSS)
        self.assertRegex(CSS,r'\.atlas-metric\s*\{[^}]*min-width:0;[^}]*overflow:hidden')
        self.assertRegex(CSS,r'\.atlas-metric-value\s*\{[^}]*overflow-wrap:anywhere')

    def test_panels_have_equal_columns_or_stack(self):
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))',CSS)
        self.assertRegex(CSS,r'@container\s*\(max-width:980px\)\s*\{[^}]*\.atlas-status-bottom\{grid-template-columns:minmax\(0,1fr\)\}')
        self.assertIn('align-items:stretch',CSS)

    def test_worker_status_is_split_into_dynamic_chips(self):
        for key in ('episode_queue_total','episode_queue_due','episode_workers_active',
                    'episode_workers_configured','recognition_workers_active','recognition_workers_configured',
                    'episode_matched_session'):
            self.assertIn('c.'+key,JS)
        self.assertIn("workers.replaceChildren()",JS)
        self.assertIn("'atlas-worker-chip'",JS)
        self.assertIn('#metadata-workers-status{display:grid',CSS)

    def test_dashboard_markup_retained(self):
        parser=ElementIds()
        parser.feed(HTML)
        for element in ('catalog-status','catalog-import-summary','metadata-status',
                        'metadata-workers-status','provider-status','imdb-dashboard-summary'):
            with self.subTest(element=element):
                self.assertIn(element,parser.ids)
        self.assertEqual(parser.ids['catalog-status'],'div')

    def test_search_bar_has_no_fixed_max_width(self):
        match=re.search(r'#discover #search\{([^}]+)\}',CSS)
        self.assertIsNotNone(match)
        self.assertNotIn('max-width:',match.group(1))
        self.assertIn('minmax(0,1fr)',match.group(1))


if __name__=='__main__':
    unittest.main()
