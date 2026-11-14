"""Route table of the web server (0.6.1, Phase B of the review of 14.11.2026).

Until 0.6.0 ``server.py`` answered every address from two long chains of ``if path=='/api/...':``
inside ``Handler.get`` and ``Handler.post`` (about 130 blocks sharing one function scope). Now each
address with a fixed path is a function of its own, registered here:

    ROUTES = routing.Table()

    @ROUTES.get('/api/tasks')
    def get_tasks(self, path): ...

    @ROUTES.post('/api/task-action')
    def post_task_action(self, path, d): ...

A route belongs to one stage, which says what the server has checked before the function runs:

- ``open``: nothing but the Host header (icon, style sheet, login state); never private data.
- ``signed``: the login (network mode); the page itself and addresses a ``<video>`` or ``<a>``
  element calls, which carry the page token in the query and check it themselves.
- ``api`` (default): login and the page token in the ``X-Atlas-Token`` header.

The table also lists every address (``listing``) for tests and the later API description.
Standard library only.
"""
from __future__ import annotations

STAGES = ('open', 'signed', 'api')
METHODS = ('GET', 'POST')


class Table:
    def __init__(self):
        self._routes = {method: {} for method in METHODS}

    def add(self, method, paths, stage='api'):
        if method not in METHODS:
            raise ValueError('Unbekannte Methode: %s' % method)
        if stage not in STAGES:
            raise ValueError('Unbekannte Stufe: %s' % stage)
        if not paths:
            raise ValueError('Route ohne Adresse')

        def register(fn):
            for path in paths:
                if not isinstance(path, str) or not path.startswith('/'):
                    raise ValueError('Ungültige Adresse: %r' % (path,))
                if path in self._routes[method]:
                    raise ValueError('Adresse doppelt vergeben: %s %s' % (method, path))
                self._routes[method][path] = (stage, fn)
            return fn
        return register

    def get(self, *paths, stage='api'):
        return self.add('GET', paths, stage)

    def post(self, *paths, stage='api'):
        return self.add('POST', paths, stage)

    def find(self, method, path, stage):
        """The function for this address, if it is registered for exactly this stage."""
        hit = self._routes.get(method, {}).get(path)
        return hit[1] if hit and hit[0] == stage else None

    def stage(self, method, path):
        hit = self._routes.get(method, {}).get(path)
        return hit[0] if hit else None

    def has(self, method, path):
        return path in self._routes.get(method, {})

    def listing(self):
        """[(method, path, stage, function name)], sorted."""
        return sorted((method, path, stage, fn.__name__) for method, table in self._routes.items()
                      for path, (stage, fn) in table.items())
