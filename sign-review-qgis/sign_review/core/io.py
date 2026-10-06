# SPDX-License-Identifier: GPL-2.0-or-later
"""Downloading and caching the photos behind the image links."""

import os
import hashlib
import urllib.request

from qgis.PyQt.QtGui import QImageReader

from ..config import CACHE


def cache_path(url):
    return os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + '.img')


_FAILED = set()
_SIZES = {}


def cached(url):
    """Path of the already-downloaded photo, or None. Never touches the network."""
    if not url:
        return None
    p = cache_path(str(url))
    return p if os.path.exists(p) and os.path.getsize(p) > 0 else None


def fetch(url):
    """Download an image once and keep it in the cache. Returns path or None.
    Call from worker threads (ThreadPoolExecutor), never in a loop on the GUI thread."""
    if not url:
        return None
    url = str(url)
    p = cached(url)
    if p:
        return p
    if url in _FAILED:
        return None
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        tmp = cache_path(url) + '.part'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, cache_path(url))
        return cache_path(url)
    except Exception as e:
        _FAILED.add(url)
        print('Download failed:', url, e)
        return None


def image_size(path):
    """(width, height) from the file header only (no decoding), cached."""
    if not path:
        return None, None
    if path not in _SIZES:
        sz = QImageReader(path).size()
        _SIZES[path] = (sz.width(), sz.height()) if sz.width() > 0 else (None, None)
    return _SIZES[path]


def image_width(path):
    return image_size(path)[0]
