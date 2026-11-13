# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 15 - CUT-OFF PHOTOS GO TO THEIR OWN WINDOW / LAYER

cut off = the box is closer than EDGE_PX (config.py) to a photo border - the sign is only partly
          in the photo. Needs only the photo size (already known when the review opens), so it
          costs no downloads and no time.

A) IN THE REVIEW WINDOW (automatic)
   Every cut-off photo leaves the main grid and goes to the "✂ Cut-off (N)" window (button in the
   top row). That window opens at once; each photo fills in as it arrives. In it:
       ↩ Back (tile) or "↩ Back to review" (blue bar)  -> back to the main window
       Select all + Delete                               -> remove them from the layer

B) PLUGINS > SIGN REVIEW > SEPARATE CUT-OFF…   (whole layer, or the selected points)
   New layers in one group ("folder") of the Layers panel, GROUP_NAME, each with all original
   fields + qa_reason:
       "Cut-off boxes"   box closer than EDGE_PX to a photo border
       "No box / photo"  no box, or the photo could not be read
       "Good"            everything else
   The photo size is read from a sample of photos (first bytes only); if they all have the same
   size, that size is used for every photo - fast for any number of points.
"""

import random

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QPushButton
from qgis.core import QgsFeature, QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.utils import iface

from ..config import LINK_FIELD, BOX_FIELD, EDGE_PX, THREADS, PER_PAGE
from ..core.io import known_size, probe, save_sizes
from ..core.parsing import parse_boxes, largest_box
from ..ui.widgets import wait_for, clear_grid
from ..ui.tile import Tile
from .f12_closest_photos import BestDialog

SAMPLE = 25           # photos read to check that all photos have the same size

GROUP_NAME = 'Sign Review – cut-off'
GROUPS = (('Cut-off boxes', ('cut off',), '#e53935'),          # name, qa_reason values, colour
          ('No box / photo', ('no box', 'no photo', 'photo not readable'), '#757575'),
          ('Good', (None,), '#43a047'))


def touches_border(box, size):
    """True if the box is closer than EDGE_PX to any border of a photo of this (W, H)."""
    return (box[0] <= EDGE_PX or box[1] <= EDGE_PX or box[2] >= size[0] - EDGE_PX
            or box[3] >= size[1] - EDGE_PX)


# ══ A) IN THE REVIEW WINDOW ═══════════════════════════════════════════════════════════════════


class CutoffBlurMixin:
    """✂ Cut-off window - mixed into the review window, BEFORE MyBestMixin
    (it extends split_picked / update_my_best of block 14)."""

    # ── 15.1  problem_reason() : 'cut off' or None ────────────────────────────────────────────
    def problem_reason(self, f):
        b = largest_box(self.get_info(f)['boxes'])
        if not b:
            return None
        w, h = self.width_of(f), self.height_of(f)
        return 'cut off' if w and h and touches_border(b, (w, h)) else None

    # ── 15.2  split_picked() : main window = photos not in My best and not cut off ────────────
    def split_picked(self):
        super().split_picked()
        keep = getattr(self, 'problem_keep', None)
        if keep is None:
            keep = self.problem_keep = set()
        self.problems = {f: r for f in self.all_fids()
                         if f not in self.picked and f not in keep
                         for r in [self.problem_reason(f)] if r}
        if self.problems:
            self.items = [i for i in self.items if i[0] not in self.problems]
            self.pages = max(1, (len(self.items) + PER_PAGE - 1) // PER_PAGE)

    # ── 15.3  update_my_best() : also refresh the ✂ button and window ───────────────────────
    def update_my_best(self):
        super().update_my_best()
        self._problem_button()
        n = len(getattr(self, 'problems', {}))
        self.btn_problems.setText(f'✂ Cut-off ({n})')
        for d in list(self.same_dialogs):
            if isinstance(d, ProblemDialog):
                d.reload()

    def _problem_button(self):
        """Creates the ✂ button once, next to ⭐ My best in the top row."""
        if getattr(self, 'btn_problems', None) is not None:
            return
        self.btn_problems = QPushButton('✂ Cut-off (0)')
        self.btn_problems.setAutoDefault(False)
        self.btn_problems.setStyleSheet('font-weight:bold; padding:4px 12px;')
        self.btn_problems.setToolTip('Photos whose box is cut off at the photo border - moved out of '
                                     'the main window. Click to see them.')
        self.btn_problems.clicked.connect(self.open_problems)
        lay = self.layout()
        for i in range(lay.count() if lay else 0):
            sub = lay.itemAt(i).layout()
            if sub is not None and sub.indexOf(self.btn_my_best) >= 0:
                sub.addWidget(self.btn_problems)
                return
        self.btn_problems.setParent(self)

    # ── 15.4  open_problems() / keep_problems() : the window, and ↩ Back ──────────────────────
    def open_problems(self):
        for d in self.same_dialogs:
            if isinstance(d, ProblemDialog):
                d.reload()
                d.raise_()
                return
        ProblemDialog(self).show()

    def keep_problems(self, fids):
        """↩ Back: these photos go back to the main window (until the review is reopened)."""
        back = [f for f in fids if f in getattr(self, 'problems', {})]
        if not back:
            return
        self.problem_keep.update(back)
        self.selected.difference_update(back)
        keep_page = self.page
        self.unsplit()
        self.split_picked()
        self.sides, self.road_axis = self.classify_sides(self.order())
        self.goto(min(keep_page, self.pages - 1))
        self.selection_changed()
        self.update_my_best()

    def keep_selected_problems(self):
        self.keep_problems([f for f in self.problems if f in self.selected])


# ══ 15.5  ProblemDialog : the ✂ Cut-off window ═════════════════════════════════════════════════


class ProblemDialog(BestDialog):
    """The cut-off photos, sorted Left | Right. Opens at once: every tile is drawn straight away
    and its photo fills in when the review window's loader has it (no waiting for downloads)."""

    def __init__(self, rv):
        self._waiting = []
        self.fill = QTimer()
        self.fill.setInterval(60)
        super().__init__(rv)
        self.fill.timeout.connect(self._fill_tiles)
        self.setWindowTitle('✂ Cut-off - photos whose box touches the photo border')
        back = QPushButton('↩ Back to review')
        back.setProperty('active_style', 'background:#757575;color:white;font-weight:bold;padding:4px 10px;')
        back.clicked.connect(rv.keep_selected_problems)
        self.sel_bar.layout().addWidget(back)
        self.sel_bar.btns.append(back)
        self.sel_bar.update_state()

    def fids_to_show(self):
        return list(getattr(self.rv, 'problems', {}))

    def info_text(self, left):
        n = len(self.matches)
        if not n:
            return '<b>No cut-off photos</b> in this review.'
        return (f'<b>{n} cut-off photos</b>: {left} left of camera, {n - left} right   –   '
                '↩ Back puts a photo back in the main window, Select all + Delete removes them')

    def reload(self):
        rv = self.rv
        bar = self.scroll.verticalScrollBar()
        pos = bar.value()                               # a refresh keeps your place in the window
        self.matches = rv.near_first(self.fids_to_show())
        self.sides, self.road_axis = rv.classify_sides(self.matches)
        rv.forget_tiles(self.tiles)
        clear_grid(self.grid)
        self.tiles, self._waiting = [], []
        for f in self.matches:
            d = rv.get_info(f)
            fut = rv.loader.submit(rv._thumb_key(d['url'], d['boxes']), 0, d['url'], d['boxes'])
            n = rv.sign_no.get(f)
            extra = f'sign {n} ({len(rv.sign_members.get(n, []))} photos)' if n else ''
            t = Tile(rv, f, None, rv.caption(f, extra) +
                     '<br><span style="color:#e53935;font-weight:bold">✂ cut off</span>', owner=self)
            if fut.done():
                t.set_image(rv._result(fut))
            else:
                t.show_loading()
                self._waiting.append((t, fut))
            btns = t.layout().itemAt(t.layout().count() - 1).layout()
            if btns is not None:
                b = QPushButton('↩ Back')
                b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                b.setStyleSheet('font-size: 10px; padding: 1px 4px;')
                b.setFixedHeight(20)
                b.setToolTip('Back to the main window')
                b.clicked.connect(lambda _=False, fid=f: rv.keep_problems([fid]))
                btns.addWidget(b)
            self.tiles.append(t)
        self._cols = self.fit_cols()
        self.flow(self.tiles)
        rv.extra_tiles.extend(self.tiles)
        left = sum(1 for f in self.matches if self.sides.get(f) == 'L')
        self.info_lbl.setText(self.info_text(left))
        bar.setValue(pos)
        QTimer.singleShot(0, lambda: bar.setValue(pos))
        if self._waiting:
            self.fill.start()

    def _fill_tiles(self):
        still = []
        for t, fut in self._waiting:
            if not fut.done():
                still.append((t, fut))
                continue
            try:
                t.set_image(self.rv._result(fut))
            except RuntimeError:
                pass
        self._waiting = still
        if not still:
            self.fill.stop()

    def on_close(self, *args):
        self.fill.stop()
        super().on_close(*args)


# ══ B) PLUGINS > SIGN REVIEW > SEPARATE CUT-OFF… ══════════════════════════════════════════════


# ── 15.6  photo_sizes() : W x H of every photo (a sample first) ──────────────────────────────
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


# ── 15.7  classify() : cut off / no box / good ──────────────────────────────────────────────
def classify(rows, sizes):
    for r in rows:
        b = r['box']
        size = sizes.get(r['url']) if r['url'] else None
        if not b or not r['url']:
            r['reason'] = 'no box' if not b else 'no photo'
        elif not size:
            r['reason'] = 'photo not readable'
        elif touches_border(b, size):
            r['reason'] = 'cut off'


# ── 15.8  make_layers() : one new layer per group, inside one folder ──────────────────────────
def make_layers(layer, rows):
    """A fresh group GROUP_NAME at the top of the Layers panel (the previous run's group and
    layers are removed first) with one temporary layer per non-empty result."""
    fl = layer.fields()
    wkb = QgsWkbTypes.displayString(layer.wkbType()) or 'Point'
    crs = layer.crs().authid() or layer.crs().toWkt()
    proj = QgsProject.instance()
    root = proj.layerTreeRoot()
    old_group = root.findGroup(GROUP_NAME)
    if old_group is not None:
        for node in old_group.findLayers():
            proj.removeMapLayer(node.layerId())
        root.removeChildNode(old_group)
    group = root.insertGroup(0, GROUP_NAME)
    counts = {}
    for name, reasons, colour in GROUPS:
        part = [r for r in rows if r['reason'] in reasons]
        counts[name] = len(part)
        if not part:
            continue
        out = QgsVectorLayer(f'{wkb}?crs={crs}&field=qa_reason:string(30)', name, 'memory')
        dp = out.dataProvider()
        dp.addAttributes([x for x in fl.toList() if x.name() != 'qa_reason'])
        out.updateFields()
        src = [fl.indexOf(x.name()) for x in out.fields()][1:]
        feats = []
        for r in part:
            g = QgsFeature(out.fields())
            g.setGeometry(r['f'].geometry())
            g.setAttributes([r['reason'] or 'good'] + [r['f'][i] if i >= 0 else None for i in src])
            feats.append(g)
        dp.addFeatures(feats)
        out.updateExtents()
        try:
            sym = out.renderer().symbol()
            sym.setColor(QColor(colour))
            sym.setSize(3)
        except Exception:
            pass
        proj.addMapLayer(out, False)          # False = not at the top level ...
        group.addLayer(out)                   # ... but inside the group
    return counts


# ── 15.9  separate_cutoff_blur() : menu entry ────────────────────────────────────────────────
def separate_cutoff_blur():
    from concurrent.futures import ThreadPoolExecutor
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
        rows.append({'f': f, 'url': url, 'box': largest_box(parse_boxes(f[i_box])), 'reason': None})

    pool = ThreadPoolExecutor(THREADS)
    try:
        sizes = photo_sizes(sorted({r['url'] for r in rows if r['url'] and r['box']}), pool, parent)
    finally:
        pool.shutdown(wait=False)
    if sizes is None:
        return None
    classify(rows, sizes)
    counts = make_layers(layer, rows)
    msg = (f'{len(rows)} points{" (selected)" if sel else ""}: ' +
           ', '.join(f'{k} {v}' for k, v in counts.items()))
    iface.messageBar().pushSuccess('Sign Review', msg)
    return counts
