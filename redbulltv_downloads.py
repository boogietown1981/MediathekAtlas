"""Red Bull TV offline copies (0.6.54): the ServusTV download module (servustv_downloads.py) with the Red Bull TV
tenant. Same rules: films and episodes only, plain HLS without a key as released by the player right now, 30 days
offline, removed at the end of availability at the latest, never live channels.

Björn's Mac (20.11.2026, live network): api-player.redbull.com/tv?…&tenant=rbtv answers with ``videoUrl`` (HLS master,
avc1 up to 1080p, hvc1 up to 2160p, AAC, subtitles), no DRM and no EXT-X-KEY. A real download is still to be checked
there; the cloud build cannot reach the Red Bull hosts.
"""
from __future__ import annotations

import redbulltv
import servustv_downloads as base

T = redbulltv.T
OFFLINE_DAYS = base.OFFLINE_DAYS
LICENSE = base.license_kind(T)


def metadata(row, series=None):
    return base.metadata(row, series, T)


def build_job(root, download_dir, item_id, now=None, check=None):
    return base.build_job(root, download_dir, item_id, now, check, T)


def enqueue(c, root, download_dir, item_id, now=None, check=None):
    return base.enqueue(c, root, download_dir, item_id, now, check, T)


def resolve(row):
    return base.resolve(row, T)
