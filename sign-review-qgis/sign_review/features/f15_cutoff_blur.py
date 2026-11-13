# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 15 - SEPARATE CUT-OFF AND BLURRY DETECTIONS
Plugins > Sign Review > Separate cut-off / blurry…

Click the detection layer (select points to check only those; nothing selected = whole layer).
New layers are added, each with all original fields + qa_reason and blur_score:
    "Cut-off boxes"   box closer than EDGE_PX to a photo border  -> the sign is cut off
    "Blurry"          sign crop sharpness < BLUR_RATIO x the median of signs of a similar size
    "Tiny boxes"      box narrower than TINY_PX                  -> too far away to judge
    "No box / photo"  no box, or the photo could not be read
    "Good"            everything else
Cut-off needs only the photo size: a sample of photos is read (first bytes only); if they all
have the same size, that size is used for every photo. Blur needs the photo itself: each photo
is downloaded once into the plugin's cache (shared with the review window).
"""

import random
from concurrent.futures import ThreadPoolExecutor

from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QProgressDialog
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsFeature, QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.utils import iface

from ..config import LINK_FIELD, BOX_FIELD, EDGE_PX, TINY_PX, THREADS
from ..core.io import cached, fetch, known_size, probe, save_sizes
from ..core.imaging import read_region, box_rect, sharpness_image
from ..core.parsing import parse_boxes, largest_box
from ..ui.widgets import wait_for

BLUR_RATIO = 0.5      # blurry = sharpness below this x the median of signs of a similar size
ASK_ABOVE = 2000      # ask before downloading more photos than this for the blur check
SAMPLE = 25           # photos read to check that all photos have the same size
SHARP_WIDTH = 48      # sign crops are compared at this width (px)

GROUPS = (('Cut-off boxes', ('cut off',)),
          ('Blurry', ('blurry',)),
          ('Tiny boxes', ('tiny',)),
          ('No box / photo', ('no box', 'no photo', 'photo not readable')),
          ('Good', (None,)))


# ── 15.1  photo_sizes() : W x H of every photo (a sample first) ──────────────────────────────
def photo_sizes(urls, pool, parent):
    sizes = {u: known_size(u) for u in urls}
    missing = [u for u in urls if not sizes[u]]
    if not missing:
        return sizes
    sample = random.sample(missing, min(SAMPLE, len(missing)))
    futs = {u: pool.submit(probe, u) for u in sample}
    if not wait_for(futs.values(), 'Reading photo sizes (sample)…', parent):
        return None
    for u, fu in futs.items():
        sizes[u] = fu.result()
    seen = {s for s in sizes.values() if s}
    if len(seen) == 1:
        common = next(iter(seen))
        for u in missing:
            if u not in futs:
                sizes[u] = common
    else:
        rest = [u for u in missing if u not in futs]
        futs2 = {u: pool.submit(probe, u) for u in rest}
        if not wait_for(futs2.values(), 'Reading photo sizes…', parent):
            return None
        for u, fu in futs2.items():
            sizes[u] = fu.result()
    save_sizes()
    return sizes


# ── 15.2  sharpness() : how clear the sign crop is ──────────────────────────────────────────
def sharpness(path, box):
    img, _ = read_region(path, box_rect(box))
    if img.isNull():
        return None
    return sharpness_image(img, (0, 0, img.width(), img.height()), SHARP_WIDTH)


def size_bucket(box_w):
    """Signs are compared only with signs of a similar size in the photo."""
    return 0 if box_w < 32 else 1 if box_w < 64 else 2 if box_w < 128 else 3


# ── 15.3  classify() : cut off / tiny / no box, then blur ─────────────────────────────────────
def classify(rows, sizes, pool, parent, check_blur=True):
    for r in rows:
        b = r['box']
        size = sizes.get(r['url']) if r['url'] else None
        if not b or not r['url']:
            r['reason'] = 'no box' if not b else 'no photo'
        elif not size:
            r['reason'] = 'photo not readable'
        elif (b[0] <= EDGE_PX or b[1] <= EDGE_PX or b[2] >= size[0] - EDGE_PX
              or b[3] >= size[1] - EDGE_PX):
            r['reason'] = 'cut off'
        elif b[2] - b[0] < TINY_PX:
            r['reason'] = 'tiny'

    todo = [r for r in rows if r['reason'] is None]
    if not check_blur or not todo:
        return
    new = len({r['url'] for r in todo if not cached(r['url'])})
    if new > ASK_ABOVE:
        ans = QMessageBox.question(
            parent, 'Blur check',
            f'The blur check has to download {new} photos (about {new} MB).\n'
            'Yes = download and check blur\nNo = skip blur (cut-off is done)')
        if ans != QMessageBox.StandardButton.Yes:
            return
    futs = {u: pool.submit(fetch, u) for u in {r['url'] for r in todo}}
    if not wait_for(futs.values(), 'Downloading photos for the blur check…', parent):
        return
    dlg = QProgressDialog('Measuring sharpness…', 'Cancel', 0, len(todo), parent)
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(300)
    for k, r in enumerate(todo):
        p = futs[r['url']].result()
        if p is None:
            r['reason'] = 'photo not readable'
        else:
            r['sharp'] = sharpness(p, r['box'])
        if k % 50 == 0:
            dlg.setValue(k)
            QApplication.processEvents()
            if dlg.wasCanceled():
                break
    dlg.close()
    groups = {}
    for r in todo:
        if r.get('sharp') is not None:
            groups.setdefault(size_bucket(r['box'][2] - r['box'][0]), []).append(r['sharp'])
    med = {g: sorted(v)[len(v) // 2] for g, v in groups.items() if v}
    for r in todo:
        s, m = r.get('sharp'), med.get(size_bucket(r['box'][2] - r['box'][0]))
        if s is not None and m:
            r['blur'] = round(s / m, 2)
            if r['blur'] < BLUR_RATIO and r['reason'] is None:
                r['reason'] = 'blurry'


# ── 15.4  make_layers() : one new layer per group ────────────────────────────────────────────
def make_layers(layer, rows):
    fl = layer.fields()
    wkb = QgsWkbTypes.displayString(layer.wkbType()) or 'Point'
    crs = layer.crs().authid() or layer.crs().toWkt()
    proj = QgsProject.instance()
    counts = {}
    for name, reasons in GROUPS:
        part = [r for r in rows if r['reason'] in reasons]
        counts[name] = len(part)
        for old in proj.mapLayersByName(name):
            proj.removeMapLayer(old.id())
        if not part:
            continue
        out = QgsVectorLayer(f'{wkb}?crs={crs}&field=qa_reason:string(30)&field=blur_score:double',
                             name, 'memory')
        dp = out.dataProvider()
        dp.addAttributes([x for x in fl.toList() if x.name() not in ('qa_reason', 'blur_score')])
        out.updateFields()
        src = [fl.indexOf(x.name()) for x in out.fields()][2:]
        feats = []
        for r in part:
            g = QgsFeature(out.fields())
            g.setGeometry(r['f'].geometry())
            g.setAttributes([r['reason'] or 'good', r['blur']] + [r['f'][i] if i >= 0 else None for i in src])
            feats.append(g)
        dp.addFeatures(feats)
        out.updateExtents()
        proj.addMapLayer(out)
    return counts


# ── 15.5  separate_cutoff_blur() : menu entry ────────────────────────────────────────────────
def separate_cutoff_blur(check_blur=True):
    parent = iface.mainWindow()
    layer = iface.activeLayer()
    if not isinstance(layer, QgsVectorLayer):
        iface.messageBar().pushWarning('Sign Review', 'Click your detection layer in the Layers panel first')
        return None
    fl = layer.fields()
    i_link, i_box = fl.indexOf(LINK_FIELD), fl.indexOf(BOX_FIELD)
    if i_link < 0 or i_box < 0:
        iface.messageBar().pushWarning('Sign Review', f'The layer needs the fields "{LINK_FIELD}" and "{BOX_FIELD}"')
        return None
    sel = layer.selectedFeatureCount() > 0
    rows = []
    for f in (layer.getSelectedFeatures() if sel else layer.getFeatures()):
        url = f[i_link]
        url = str(url) if url not in (None, '') and str(url) != 'NULL' else None
        rows.append({'f': f, 'url': url, 'box': largest_box(parse_boxes(f[i_box])),
                     'reason': None, 'blur': None})

    pool = ThreadPoolExecutor(THREADS)
    try:
        sizes = photo_sizes(sorted({r['url'] for r in rows if r['url'] and r['box']}), pool, parent)
        if sizes is None:
            return None
        classify(rows, sizes, pool, parent, check_blur)
    finally:
        pool.shutdown(wait=False)
    counts = make_layers(layer, rows)
    msg = (f'{len(rows)} points{" (selected)" if sel else ""}: ' +
           ', '.join(f'{k} {v}' for k, v in counts.items()))
    iface.messageBar().pushSuccess('Sign Review', msg)
    return counts
