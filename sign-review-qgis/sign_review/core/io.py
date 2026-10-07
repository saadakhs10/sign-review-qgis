# SPDX-License-Identifier: GPL-2.0-or-later
"""Downloading and caching the photos behind the image links.

Only real images are kept: a reply that is not a JPEG / PNG / WebP / GIF / BMP / TIFF
(for example an error message sent when the server is busy) is never cached, and a bad
file already in the cache is deleted and downloaded again. Failed downloads are retried
a few times, and tried again later instead of being given up for the whole session."""

import os
import time
import hashlib
import threading
import urllib.request

from qgis.PyQt.QtGui import QImageReader

from ..config import CACHE

RETRIES = 3
TIMEOUT_S = 30
RETRY_AFTER_S = 60

_FAILED = {}
_SIZES = {}
_VALID = set()
_LOCK = threading.Lock()


def cache_path(url):
    return os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + '.img')


def is_image_bytes(head):
    """True if the first bytes are those of an image file."""
    return (head.startswith(b'\xff\xd8\xff')
            or head.startswith(b'\x89PNG\r\n\x1a\n')
            or (head[:4] == b'RIFF' and head[8:12] == b'WEBP')
            or head.startswith((b'GIF87a', b'GIF89a', b'BM', b'II*\x00', b'MM\x00*')))


def _forget(path):
    with _LOCK:
        _VALID.discard(path)
        _SIZES.pop(path, None)


def cached(url):
    """Path of the already-downloaded photo, or None. Never touches the network.
    A cached file that is not an image is deleted, so it will be downloaded again."""
    if not url:
        return None
    p = cache_path(str(url))
    if p in _VALID:
        return p
    try:
        with open(p, 'rb') as f:
            head = f.read(16)
    except OSError:
        return None
    if is_image_bytes(head):
        _VALID.add(p)
        return p
    try:
        os.remove(p)
    except OSError:
        pass
    _forget(p)
    return None


def fetch(url):
    """Download an image once and keep it in the cache. Returns path or None.
    Call from worker threads (ThreadPoolExecutor), never in a loop on the GUI thread."""
    if not url:
        return None
    url = str(url)
    p = cached(url)
    if p:
        return p
    last = _FAILED.get(url)
    if last and time.time() - last < RETRY_AFTER_S:
        return None
    error = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                data = r.read()
            if not is_image_bytes(data[:16]):
                raise ValueError('reply is not an image (%d bytes, starts %r)' % (len(data), data[:20]))
            path = cache_path(url)
            tmp = '%s.%d.part' % (path, threading.get_ident())
            with open(tmp, 'wb') as f:
                f.write(data)
            os.replace(tmp, path)
            _forget(path)
            _VALID.add(path)
            _FAILED.pop(url, None)
            return path
        except Exception as e:
            error = e
            time.sleep(1.5 * (attempt + 1))
    _FAILED[url] = time.time()
    print('Download failed:', url, error)
    return None


def image_size(path):
    """(width, height) from the file header only (no decoding), cached."""
    if not path:
        return None, None
    if path not in _SIZES:
        sz = QImageReader(path).size()
        if sz.width() <= 0:
            return None, None
        _SIZES[path] = (sz.width(), sz.height())
    return _SIZES[path]


def image_width(path):
    return image_size(path)[0]
