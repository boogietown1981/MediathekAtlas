"""Resolution of an offline copy, chosen per title before the download (0.5.63).

Björn (12.11.2026): before a download the resolution and the provider should be selectable, e.g.
480p on a weak connection and the best one over night.

The wish is stored in the job as ``quality``: 'best' (as before) or a picture height such as '720',
meaning "at most 720p". Every source applies it with its own means:

* Pluto TV, JustWatch TV, Rakuten TV (HLS): one level of the provider's playlist (hls_variants)
* YouTube: format filter of yt-dlp
* Netzkino: the MP4 of that height when the provider publishes several
* ARD, ZDF & Co.: the broadcaster's HD / standard / small file
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

import hls_variants

HEIGHTS = (2160, 1080, 720, 480, 360)
LEGACY = {'best', 'hd', 'standard', 'low'}     # values of the Mediathek dialogue, kept as they are


def normalize(value):
    """'best', a legacy Mediathek value or a height between 144 and 4320 as text."""
    text = str(value or 'best').strip().lower()
    if text in LEGACY:
        return text
    if text == 'max':
        return 'best'
    if text.isdigit() and len(text) <= 4 and 144 <= int(text) <= 4320:
        return str(int(text))
    return 'best'


def height(quality):
    """Largest picture height for a wish; None for "best"."""
    text = normalize(quality)
    if text.isdigit():
        return int(text)
    return {'hd': 720, 'standard': 540, 'low': 360}.get(text)


def label(quality):
    limit = height(quality)
    return 'Beste verfügbare' if limit is None else 'höchstens %dp' % limit


def mediathek_key(quality):
    """Mediathek rows know three files (HD, standard, small)."""
    text = normalize(quality)
    if text in LEGACY:
        return text
    limit = int(text)
    return 'best' if limit >= 1080 else 'hd' if limit >= 720 else 'standard' if limit >= 480 else 'low'


def youtube_format(quality):
    """yt-dlp format filter: H.264 + AAC first (plays everywhere), up to the wished height.
    'best' stays at 1080p as before; 4K only when it is asked for."""
    limit = height(quality) or 1080
    return ('bv*[height<=%d][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<=%d]+ba/b[height<=%d]/'
            'wv*+ba/w' % (limit, limit, limit)) if height(quality) else \
        'bv*[height<=1080][vcodec^=avc1]+ba[acodec^=mp4a]/bv*[height<=1080]+ba/b[height<=1080]/b'


def hls_playlist(url, quality, folder, fetch=None):
    """Local playlist with the one level that fits the wish. Returns (path, level) or (None, None)
    when the address has no levels or the wish is "best" (ffmpeg then takes the largest itself)."""
    limit = height(quality)
    if limit is None:
        return None, None
    text, final, variants = hls_variants.load(url, fetch)
    chosen = hls_variants.choose(variants, str(limit))
    if not chosen:
        return None, None
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('levels-%s.m3u8' % secrets.token_hex(6))
    path.write_text(hls_variants.single(text, final, chosen), encoding='utf-8')
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path, {'label': hls_variants.label(chosen), 'height': chosen['height'], 'bandwidth': chosen['bandwidth']}


def pick_format(formats, quality):
    """Among direct MP4 formats (youtube-dl info) the largest that fits; None when nothing to choose."""
    limit = height(quality)
    usable = [f for f in formats or [] if isinstance(f, dict) and isinstance(f.get('url'), str)
              and f['url'].lower().split('?', 1)[0].endswith('.mp4') and isinstance(f.get('height'), int)]
    if limit is None or not usable:
        return None
    fitting = [f for f in usable if f['height'] <= limit]
    return max(fitting, key=lambda f: f['height']) if fitting else min(usable, key=lambda f: f['height'])


def set_job(c, result, wish):
    """Store the wish in a freshly created job (same transaction as the insert)."""
    import json
    quality = normalize(wish)
    if not isinstance(result, dict) or not result.get('created') or not result.get('id') or quality == 'best':
        return quality
    row = c.execute('SELECT payload FROM jobs WHERE id=?', (result['id'],)).fetchone()
    if row:
        job = json.loads(row[0])
        job['quality'] = quality
        c.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(job), result['id']))
        result['quality'] = quality
    return quality


def options(source, play_source=None, fetch=None):
    """What the dialogue shows for one offer: the levels the provider has, or why none are known."""
    if source in ('pluto', 'justwatch', 'rakuten'):
        try:
            found = play_source()
            if found.get('kind') == 'url' and found.get('hls'):
                levels = hls_variants.levels(hls_variants.load(found['url'], fetch)[2])
                if levels:
                    return {'levels': levels, 'note': ''}
            return {'levels': [], 'note': 'Der Anbieter liefert für diesen Titel nur eine Fassung.'}
        except Exception as exc:  # provider not reachable: the download itself reports the reason
            return {'levels': [], 'note': 'Die Stufen ließen sich gerade nicht abfragen (%s). '
                                          'MediathekAtlas nimmt die beste Stufe bis zur gewählten Grenze.' % str(exc)[:120]}
    if source == 'youtube':
        return {'levels': [], 'note': 'YouTube: die Stufe wird beim Laden gewählt; „Beste verfügbare“ lädt bis 1080p, 4K nur auf Wunsch.'}
    if source == 'netzkino':
        return {'levels': [], 'note': 'Netzkino stellt meist nur eine Fassung bereit; gibt es mehrere, gilt die gewählte Grenze.'}
    return {'levels': [], 'note': ''}
