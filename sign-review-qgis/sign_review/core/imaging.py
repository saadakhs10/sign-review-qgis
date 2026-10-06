# SPDX-License-Identifier: GPL-2.0-or-later
"""Image maths: look-alike fingerprint (dHash), sharpness (Tenengrad) and
the thumbnails with the red bounding box."""

from qgis.PyQt.QtCore import Qt, QRect
from qgis.PyQt.QtGui import QImage, QImageReader, QPixmap, QPainter, QPen, QColor

from ..config import THUMB, PAD
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
    """Thumbnail with the red box. With crop=True only the area around the box is decoded."""
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
    return QPixmap.fromImage(img).scaled(size, size,
                                         Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
