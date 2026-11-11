"""One-time idempotent local patch to bundle safe Netzkino diagnostic events."""
from pathlib import Path
p=Path(__file__).parent/'netzkino.py'
s=p.read_text()
s=s.replace('This module downloads *catalogue XML only* from a fixed first-party sitemap URL.',
'''This module indexes public catalogue metadata via observed first-party
GraphQL operations. Legacy sitemap parsing remains available to regression tests.''')
anchor='_LAST_THREAD = None\n'
insert='''_LAST_THREAD = None


def _notify(event, **details):
    """Technical counters only; never log URLs, media titles, GraphQL bodies or secrets."""
    try:
        import diagnostics
        diagnostics.event(event, **details)
    except ImportError:
        # Standalone provider tests intentionally do not import the app server.
        pass

'''
assert s.count(anchor)==1
s=s.replace(anchor,insert)
s=s.replace("            'categories_checked':int(_get(db,'categories_checked','0')),",
'''            'categories_checked':int(_get(db,'categories_checked','0')),
            'category_errors':int(_get(db,'category_errors','0')),
            'last_http_status':int(_get(db,'last_http_status','0')),''')
s=s.replace("    now=time.time() if now is None else float(now)\n    fetch=fetch or _fetch_graphql\n",
'''    now=time.time() if now is None else float(now)
    fetch=fetch or _fetch_graphql
    _notify('netzkino_sync_started',mode='public_graphql',live=True)
''')
s=s.replace("            _set(db,'categories_checked',0)\n            _set(db,'categories_total',0)",
"            _set(db,'categories_checked',0)\n            _set(db,'categories_total',0)\n            _set(db,'category_errors',0)\n            _set(db,'last_http_status',0)")
s=s.replace("            except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError,ValueError):\n                failures+=1",
'''            except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,OSError,ValueError) as exc:
                failures+=1
                _notify('netzkino_category_error',error_type=type(exc).__name__,
                        http_status=getattr(exc,'code',0),category_errors=failures)''')
s=s.replace("            try:\n                with db:_set(db,'categories_checked',checked)\n            finally:db.close()",
'''            try:
                with db:
                    _set(db,'categories_checked',checked)
                    _set(db,'category_errors',failures)
            finally:db.close()''')
s=s.replace("            return {'new':new,'changed':changed,'unchanged':unchanged,'count':len(found),\n                    'categories':len(cats),'category_errors':failures,'ok':True}",
'''            _notify('netzkino_sync_completed',count=len(found),new=new,changed=changed,
                    unchanged=unchanged,categories=len(cats),category_errors=failures)
            return {'new':new,'changed':changed,'unchanged':unchanged,'count':len(found),
                    'categories':len(cats),'category_errors':failures,'ok':True}''')
s=s.replace("                _set(db,'last_error',msg)\n                _set(db,'next_attempt',now+3600)",
"                _set(db,'last_error',msg)\n                _set(db,'last_http_status',getattr(exc,'code',0))\n                _set(db,'next_attempt',now+3600)")
s=s.replace("        return {'ok':False,'error':msg,'categories_checked':checked}",
'''        _notify('netzkino_sync_failed',error_type=type(exc).__name__,
                http_status=getattr(exc,'code',0),categories_checked=checked)
        return {'ok':False,'error':msg,'categories_checked':checked}''')
s=s.replace("        except urllib.error.HTTPError as exc:\n            if exc.code not in (429,500,502,503,504) or attempt>=2:raise",
'''        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt>=2:raise
            _notify('netzkino_request_retry',operation=operation,
                    attempt=attempt+1,http_status=exc.code)''')
assert "netzkino_sync_completed" in s and "category_errors" in s
p.write_text(s)
