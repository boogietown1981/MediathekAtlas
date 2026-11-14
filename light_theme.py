"""Helles Design (0.5.99), abgeleitet aus dem dunklen Stylesheet.

``web/style.css`` holds about 330 colours, written for the dark design, and several threads keep
editing that file. Instead of a second hand-written stylesheet (which would be out of date with
the next change) the light design is computed: every rule of ``style.css`` that sets a colour is
repeated under ``html[data-theme="light"]`` with the same declaration, the colour mirrored in
lightness (hue and saturation stay, so the green accent, warnings and tags keep their meaning).
``style.css`` itself is not touched and stays the only place where the interface is styled.

Kept dark on purpose: shadows, dialog backdrops, and everything that lies on a picture or belongs
to the player (``KEEP``) - white text on a poster must stay white.

The server builds the sheet when it is first asked for and again when ``style.css`` changes.
"""
from __future__ import annotations

import colorsys
import re
from pathlib import Path

PREFIX = 'html[data-theme="light"]'
# Rules whose selector matches stay as they are: surfaces on pictures, the player, overlays.
KEEP = re.compile(r'(?i)(::backdrop|player|backdrop|hero|overlay|-poster|poster-|\.art\b|badge-on|shade|scrim|video|-cover\b|live-now|atlas-title-top)')
SKIP_PROPERTIES = ('box-shadow', 'text-shadow', 'filter', 'backdrop-filter', '-webkit-backdrop-filter')
HEX = re.compile(r'#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b')
FUNC = re.compile(r'rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([0-9.]+)\s*)?\)')
WORD = re.compile(r'(?<![\w-])(white|black)(?![\w-])')
_CACHE = {}


def mirror(r, g, b):
    """The same hue on the other side of the lightness scale; dark surfaces end up a little brighter than plain inversion."""
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    light = 1 - l
    if l < 0.3:                      # backgrounds and panels of the dark design: near white, still distinguishable
        light = 1 - l * 0.62
    elif l > 0.6:                    # text and accents: a bit darker for contrast on white
        light = (1 - l) * 0.9
        s = min(1.0, s * 1.15)
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, light)), s)
    return round(r * 255), round(g * 255), round(b * 255)


def _hex(match):
    raw = match.group(1)
    if len(raw) in (3, 4):
        raw = ''.join(ch * 2 for ch in raw)
    r, g, b = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
    return '#%02x%02x%02x' % mirror(r, g, b) + raw[6:8].lower()


def _func(match):
    r, g, b = (min(255, int(match.group(i))) for i in (1, 2, 3))
    out = mirror(r, g, b)
    return 'rgba(%d,%d,%d,%s)' % (*out, match.group(4)) if match.group(4) else 'rgb(%d,%d,%d)' % out


def recolour(value):
    """One declaration value with every colour mirrored, or None if it holds no colour."""
    out = HEX.sub(_hex, value)
    out = FUNC.sub(_func, out)
    out = WORD.sub(lambda m: 'black' if m.group(1) == 'white' else 'white', out)
    return out if out != value else None


def _split(css):
    """Top-level pieces of a block: ('rule', prelude, body) and ('at', prelude, body). Comments are dropped."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    out, i, n = [], 0, len(css)
    while i < n:
        start = i
        depth, quote = 0, ''
        while i < n:
            ch = css[i]
            if quote:
                if ch == '\\':
                    i += 1
                elif ch == quote:
                    quote = ''
            elif ch in '"\'':
                quote = ch
            elif ch == '{':
                break
            elif ch == ';' and css[start:i].lstrip().startswith('@'):
                break
            i += 1
        if i >= n:
            break
        if css[i] == ';':            # @import, @charset: nothing to theme
            i += 1
            continue
        prelude = css[start:i].strip()
        i += 1
        body_start, depth = i, 1
        while i < n and depth:
            ch = css[i]
            if quote:
                if ch == '\\':
                    i += 1
                elif ch == quote:
                    quote = ''
            elif ch in '"\'':
                quote = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            i += 1
        out.append(('at' if prelude.startswith('@') else 'rule', prelude, css[body_start:i - 1]))
    return out


def _declarations(body):
    parts, depth, start, quote = [], 0, 0, ''
    for i, ch in enumerate(body):
        if quote:
            if ch == quote:
                quote = ''
        elif ch in '"\'':
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ';' and depth == 0:
            parts.append(body[start:i])
            start = i + 1
    parts.append(body[start:])
    for part in parts:
        name, colon, value = part.partition(':')
        if colon and name.strip():
            yield name.strip(), value.strip()


def _selectors(prelude):
    out, depth, start = [], 0, 0
    for i, ch in enumerate(prelude):
        if ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif ch == ',' and depth == 0:
            out.append(prelude[start:i])
            start = i + 1
    out.append(prelude[start:])
    return [s.strip() for s in out if s.strip()]


def _prefixed(selector):
    if selector.startswith(':root'):
        return PREFIX + selector[5:]
    if re.match(r'html(?![\w-])', selector):
        return PREFIX + selector[4:]
    return PREFIX + ' ' + selector


def _convert(css):
    out = []
    for kind, prelude, body in _split(css):
        if kind == 'at':
            name = re.match(r'@[a-zA-Z-]+', prelude).group(0).lower()
            if name in ('@media', '@supports', '@container', '@layer'):
                inner = _convert(body)
                if inner:
                    out.append(prelude + '{' + inner + '}')
            continue                 # @keyframes, @font-face: unchanged
        selectors = [s for s in _selectors(prelude) if not KEEP.search(s)]
        if not selectors:
            continue
        changed = []
        for name, value in _declarations(body):
            if name.lower() in SKIP_PROPERTIES or name.startswith('--') and not HEX.search(value):
                continue
            new = recolour(value)
            if new is not None:
                changed.append(name + ':' + new)
        if changed:
            out.append(','.join(_prefixed(s) for s in selectors) + '{' + ';'.join(changed) + '}')
    return ''.join(out)


def build(css):
    """The light sheet for one dark stylesheet."""
    return ('/* MediathekAtlas: helles Design, berechnet aus style.css (light_theme.py). Nicht von Hand ändern. */\n'
            + PREFIX + '{color-scheme:light}' + _convert(css) + '\n')


def sheet(path):
    """Light sheet of a stylesheet file, rebuilt only when the file changed."""
    path = Path(path)
    stamp = (path.stat().st_mtime_ns, path.stat().st_size)
    hit = _CACHE.get(str(path))
    if not hit or hit[0] != stamp:
        hit = (stamp, build(path.read_text(encoding='utf-8')).encode())
        _CACHE[str(path)] = hit
    return hit[1]
