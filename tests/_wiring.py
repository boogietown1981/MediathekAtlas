"""Shared check for the wiring tests (0.5.84).

Until 0.5.82 every platform's routes and threads were written out in server.py and the tests looked
for that text. Since 0.5.84 the common ones come from platform_registry; ``wired`` accepts either:
the text in server.py, or the same route, thread or call provided by the registry.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import platform_registry as registry  # noqa: E402

SERVER = (ROOT / 'server.py').read_text(encoding='utf-8')


def wired(needle):
    if needle in SERVER:
        return True
    route = re.search(r"'(/api/[a-z]+(?:-[a-z-]+)?)'", needle)
    if route:
        return any(path == route.group(1) for _, path in registry.routes())
    loop = re.fullmatch(r'([a-z]+)_enrichment\.loop', needle)
    if loop:
        return loop.group(1) + '_auto_enrichment' in registry.thread_names()
    loop = re.fullmatch(r'([a-z]+)\.loop', needle)
    if loop:
        return loop.group(1) + '_catalog_scheduler' in registry.thread_names()
    if needle in registry.thread_names():
        return True
    call = re.fullmatch(r"portal_page\('([a-z]+)',\1,q\)", needle)
    if call:
        return registry.BY_KEY[call.group(1)].page
    call = re.fullmatch(r'([a-z]+)_enrichment\.enrich\(ROOT,item_id,settings\(\)\)', needle)
    if call:      # reference check before an offline download
        p = registry.BY_KEY.get(call.group(1))
        return bool(p and p.add and p.offline)
    call = re.fullmatch(r'([a-z]+)_downloads\.enqueue\(c,ROOT,', needle)
    if call:
        p = registry.BY_KEY.get(call.group(1))
        return bool(p and p.add and p.offline and hasattr(p.offline, 'enqueue'))
    return False
