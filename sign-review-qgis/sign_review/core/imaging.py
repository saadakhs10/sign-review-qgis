# SPDX-License-Identifier: GPL-2.0-or-later
"""Image maths: look-alike fingerprint (dHash), sharpness (Tenengrad) and
the thumbnails with the red bounding box."""

import hashlib
import os

from qgis.PyQt.QtCore import Qt, QRect
from qgis.PyQt.QtGui import QImage, QImageReader, QPixmap, QPainter, QPen, QColor

from ..config import THUMB, PAD, THUMB_DIR, CACHE, CACHE_MAX_GB
from .io import fetch, image_size
from .parsing import largest_box


def read_region(path, rect):
    """Decode only `rect` (QRect, image pixels) of a photo - much faster than the whole
    1920 x 1080 frame. Returns (QImage, rect actually read) or (null image, None)."""
    if not path:
        return QImage(), None
    w, h = image_size(path)
    if not w:
        return QImage(), None
    r = rect.intersected(QRect(0, 0, w, h))
    if r.width() < 1 or r.height() < 1:
        return QImage(), None
    reader = QImageReader(path)
    reader.setClipRect(r)
    img = reader.read()
    return img, r


def box_rect(b):
    return QRect(b[0], b[1], b[2] - b[0], b[3] - b[1])


def dhash(path, boxes):
    """64-bit perceptual hash of the sign (largest box). Similar signs -> similar hash."""
    b = largest_box(boxes)
    if not b:
        return None
    img, r = read_region(path, box_rect(b))
    return None if img.isNull() else dhash_image(img)


def dhash_image(img, box=None):
    """Hash of the part of `img` inside box (x1, y1, x2, y2); whole image if no box."""
    if box:
        b = box
        r = QRect(b[0], b[1], b[2] - b[0], b[3] - b[1]).intersected(img.rect())
        if r.width() > 1 and r.height() > 1:
            img = img.copy(r)
    img = img.convertToFormat(QImage.Format.Format_Grayscale8).scaled(
        9, 8, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if img.pixelColor(x, y).red() > img.pixelColor(x + 1, y).red() else 0)
    return bits


def sharpness_image(img, box, width=64):
    """How clear the sign is: Tenengrad sharpness (Sobel gradient energy / contrast) of the sign crop
    (crop -> grey -> at most `width` px wide, small crops kept as they are).
    Only compare photos of a similar size at the SAME width (see Reviewer.near_set).  Blurry / motion-smeared / far-away signs score low,
    crisp signs score high.  Pure maths, no AI."""
    if img.isNull() or not box:
        return None
    r = QRect(box[0], box[1], box[2] - box[0], box[3] - box[1]).intersected(img.rect())
    if r.width() < 3 or r.height() < 3:
        return None
    g = img.copy(r).convertToFormat(QImage.Format.Format_Grayscale8)
    w = min(r.width(), width)
    h = max(3, int(round(r.height() * w / float(r.width()))))
    if w != r.width():
        g = g.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    else:
        h = r.height()
    px = [[g.pixelColor(x, y).red() for x in range(w)] for y in range(h)]
    flat = [v for row in px for v in row]
    mean = sum(flat) / len(flat)
    var = sum((v - mean) ** 2 for v in flat) / len(flat)
    if var < 25:
        return 0.0
    tot, n = 0.0, 0
    for y in range(1, h - 1):
        a, b, c = px[y - 1], px[y], px[y + 1]
        for x in range(1, w - 1):
            gx = (a[x + 1] + 2 * b[x + 1] + c[x + 1]) - (a[x - 1] + 2 * b[x - 1] + c[x - 1])
            gy = (c[x - 1] + 2 * c[x] + c[x + 1]) - (a[x - 1] + 2 * a[x] + a[x + 1])
            tot += gx * gx + gy * gy
            n += 1
    return (tot / n) / var if n else None


def fetch_and_hash(url, boxes):
    """Runs in a worker thread: download (cached), look-alike hash and sharpness."""
    p = fetch(url)
    b = largest_box(boxes)
    if not p or not b:
        return None, None
    img, r = read_region(p, box_rect(b))
    if img.isNull():
        return None, None
    whole = (0, 0, img.width(), img.height())
    return dhash_image(img), sharpness_image(img, whole)


def bit_distance(a, b):
    return bin(a ^ b).count('1')


def render(path, boxes, crop=True, size=THUMB):
    """Thumbnail with the red box (QPixmap - GUI thread only)."""
    img = render_image(path, boxes, crop, size)
    return QPixmap.fromImage(img) if img is not None else None


def render_image(path, boxes, crop=True, size=THUMB):
    """Thumbnail with the red box as a QImage. Safe in a worker thread (QPixmap is not), so
    the decoding and scaling happen while downloading, not in the window.
    With crop=True only the area around the box is decoded."""
    if not path:
        return None
    w, h = image_size(path)
    if not w:
        return None
    if crop and boxes:
        xs = [b[0] for b in boxes] + [b[2] for b in boxes]
        ys = [b[1] for b in boxes] + [b[3] for b in boxes]
        want = QRect(min(xs) - PAD, min(ys) - PAD,
                     max(xs) - min(xs) + 2 * PAD, max(ys) - min(ys) + 2 * PAD)
        img, r = read_region(path, want)
    else:
        img, r = QImage(path), QRect(0, 0, w, h)
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    p = QPainter(img)
    pen = QPen(QColor(255, 0, 0))
    pen.setWidth(max(3, w // 350))
    p.setPen(pen)
    for x1, y1, x2, y2 in boxes:
        p.drawRect(QRect(x1 - r.x(), y1 - r.y(), x2 - x1, y2 - y1))
    p.end()
    return img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


def thumb_path(url, boxes):
    key = f'{url}|{tuple(tuple(b) for b in boxes or ())}|{THUMB}|{PAD}'
    return os.path.join(THUMB_DIR, hashlib.md5(key.encode()).hexdigest() + '.jpg')


def load_thumb(key, url, boxes=None, thumb=True):
    """Worker-thread job of the photo loader: download (or take from cache) + thumbnail.
    thumb=False: only download into the cache (pages further ahead - no memory used).
    Every thumbnail is also kept on disk as a small JPEG (~10 KB): next time - also after
    closing QGIS - it appears at once, without downloading or decoding the photo again."""
    if thumb and url:
        tp = thumb_path(url, boxes)
        if os.path.exists(tp):
            img = QImage(tp)
            if not img.isNull():
                return img
    path = fetch(url)
    if not thumb:
        return None
    img = render_image(path, boxes, True)
    if img is not None and url:
        try:
            os.makedirs(THUMB_DIR, exist_ok=True)
            tmp = '%s.%d.part' % (tp, id(img))
            if img.save(tmp, 'JPG', 85):
                os.replace(tmp, tp)
        except OSError:
            pass
    return img


def trim_cache(max_gb=CACHE_MAX_GB):
    """Removes the oldest full photos (*.img) once the cache is bigger than max_gb.
    Thumbnails and photo sizes stay. Run in a worker thread."""
    try:
        files = []
        for name in os.listdir(CACHE):
            if name.endswith('.img'):
                p = os.path.join(CACHE, name)
                st = os.stat(p)
                files.append((max(st.st_atime, st.st_mtime), st.st_size, p))
        total = sum(f[1] for f in files)
        limit = max_gb * 1024 ** 3
        if total <= limit:
            return 0
        removed = 0
        for _, size, p in sorted(files):
            if total <= 0.8 * limit:
                break
            try:
                os.remove(p)
                total -= size
                removed += 1
            except OSError:
                pass
        return removed
    except OSError:
        return 0
