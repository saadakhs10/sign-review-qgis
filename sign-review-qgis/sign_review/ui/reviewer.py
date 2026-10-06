# SPDX-License-Identifier: GPL-2.0-or-later
"""The main review window (Qt5 + Qt6 compatible).

WHAT IS IN THE WINDOW
  * Photo grid, LEFT | RIGHT of the camera:
        focal = (W/2) / tan(FOV/2),  angle = atan((box centre x - W/2) / focal)
        angle < 0 -> LEFT columns,   angle > 0 -> RIGHT columns
    Inside each side: same sign together (DBSCAN), nearest photo first.
  * Selecting: drag = lasso, click = select/unselect, Shift+click = a run, tick box.
    Selected points are highlighted on the map.
  * Blue bar: Select all, then (with a selection) Clear, Reset to camera, Relocate, Delete.
  * Tile buttons: Map (pan to the point), Street (Google Street View), Near (points close to it).
  * 📁 Closest photos: the best photo of every sign (nearest to the camera, not cut off).
  * 📍 Nearby: click a point on the map -> popup with the points within the distance you set (starts at 1 m);
    🧲 Snap together puts them on one spot.

RELOCATE (camera position -> sign)
  bearing = heading + angle,  distance = sign width x focal / box width.
  A point that would land on the road (closer than "Curb offset" sideways to the
  driving line) is moved out beside the curb.

Nothing is saved until you press Save Layer Edits; Undo (Ctrl+Z) works until then."""

import json
import time
from concurrent.futures import ThreadPoolExecutor

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (QApplication, QDialog, QVBoxLayout, QLabel,
                                 QPushButton, QDoubleSpinBox)
from qgis.core import (QgsCoordinateTransform, QgsProject)
from qgis.utils import iface

from ..config import (LINK_FIELD, BOX_FIELD, HEADING_FIELD, ORIG_X_FIELD, ORIG_Y_FIELD, CONF_FIELD,
                      PER_PAGE, MAX_WHOLE_LAYER, COLS, THREADS, CAMERA_HFOV_DEG,
                      SIGN_WIDTH_M, MIN_DIST_M, MAX_DIST_M, CURB_OFFSET_M, GROUP_DIST_M,
                      HASH_FILE, SHARP_FILE, WGS84)
from ..core.io import fetch
from ..core.imaging import render
from .widgets import TileGrid, clear_grid, FlowLayout, labelled, make_window, fit_to_screen
from .selection_bar import SelectionBar
from .tile import Tile
# ---- the features, one file per block (see sign_review/features/) ----
from ..features.f01_photo_data import PhotoDataMixin
from ..features.f02_distance import DistanceMixin
from ..features.f03_left_right import LeftRightMixin
from ..features.f04_same_sign import SameSignMixin
from ..features.f05_best_photo import BestPhotoMixin
from ..features.f06_selection import SelectionMixin
from ..features.f08_relocate import RelocateMixin
from ..features.f09_nearby_snap import NearbyMixin
from ..features.f10_delete import DeleteMixin
from ..features.f11_map_street_photo import MapStreetMixin
from ..features.f12_closest_photos import ClosestPhotosMixin


class Reviewer(PhotoDataMixin,       # block 1  fields + photos
               DistanceMixin,        # block 2  camera angle + distance
               LeftRightMixin,       # block 3  Left | Right
               SameSignMixin,        # block 4  same sign (DBSCAN)
               BestPhotoMixin,       # block 5  best photo + flags
               SelectionMixin,       # block 6  selecting  (block 7 lasso is in TileGrid)
               RelocateMixin,        # block 8  Relocate / Reset to camera
               NearbyMixin,          # block 9  Nearby + Snap together
               DeleteMixin,          # block 10 Delete
               MapStreetMixin,       # block 11 Map / Street / full photo
               ClosestPhotosMixin,   # block 12 Closest photos window
               TileGrid, QDialog):
    """The review window: builds the buttons and the grid, pages through the photos.
    Every feature lives in its own block in sign_review/features/."""
    def __init__(self, layer):
        super().__init__(iface.mainWindow())
        self.layer = layer
        self.canvas = iface.mapCanvas()
        self.setWindowTitle(f'Sign review - {layer.name()}')

        flds = layer.fields()
        self.idx_link = flds.indexOf(LINK_FIELD)
        self.idx_box = flds.indexOf(BOX_FIELD)
        self.idx_head = flds.indexOf(HEADING_FIELD)
        self.idx_ox = flds.indexOf(ORIG_X_FIELD)
        self.idx_oy = flds.indexOf(ORIG_Y_FIELD)
        self.idx_conf = flds.indexOf(CONF_FIELD)
        if self.idx_link < 0:
            raise Exception(f'Field "{LINK_FIELD}" not found in layer "{layer.name()}"')

        self.to_layer = QgsCoordinateTransform(WGS84, layer.crs(), QgsProject.instance())
        self.to_wgs = QgsCoordinateTransform(layer.crs(), WGS84, QgsProject.instance())

        self.pool = ThreadPoolExecutor(THREADS)
        self.items, self.tiles, self.extra_tiles = [], [], []
        self.selected, self.anchor = set(), None
        self.bars, self.same_dialogs = [], []
        self.page, self.pages = 0, 1
        self.info = {}
        self._all = None
        self.sign_no = {}
        self.sign_members = {}
        self.sign_pos = {}
        self.flags, self.rays, self.L = {}, {}, None
        self.best = {}
        self.rel = {}
        self._sharp_cache = {}
        self.sel_highlights = {}
        self.sides, self.road_axis = {}, None
        self._busy = False
        self.near_tool = None

        self.widths = {}
        self.hashes, self.sharp = {}, {}
        try:
            self.hashes = json.load(open(HASH_FILE))
        except Exception:
            pass
        try:
            self.sharp = json.load(open(SHARP_FILE))
        except Exception:
            pass

        top = FlowLayout()
        self.btn_prev = QPushButton('◀ Prev')
        self.btn_next = QPushButton('Next ▶')
        self.btn_best = QPushButton('📁 Closest photos')
        self.btn_best.setStyleSheet('font-weight:bold; padding:4px 12px;')
        self.btn_best.setToolTip('Open a window with the best photo of every sign: nearest to the '
                                 'camera and not cut off - sorted Left | Right')
        for w in (self.btn_prev, self.btn_next):
            top.addWidget(w)
        top.addWidget(self.btn_best)
        self.btn_near = QPushButton('📍 Nearby')
        self.btn_near.setCheckable(True)
        self.btn_near.setStyleSheet('QPushButton {font-weight:bold; padding:4px 12px;}'
                                    'QPushButton:checked {background:#ffe082;}')
        self.btn_near.setToolTip('Switch on, then click a point on the MAP: a window shows it together '
                                 'with every point placed near it.  Right-click on the map = switch off')
        top.addWidget(self.btn_near)

        rel = FlowLayout()
        self.sp_fov = self.spin(10, 180, CAMERA_HFOV_DEG, 1, '°')
        self.sp_sign = self.spin(0.1, 5, SIGN_WIDTH_M, 2, ' m')
        self.sp_min = self.spin(0, 100, MIN_DIST_M, 1, ' m')
        self.sp_max = self.spin(1, 300, MAX_DIST_M, 1, ' m')
        self.sp_group = self.spin(2, 100, GROUP_DIST_M, 1, ' m')
        self.sp_curb = self.spin(0, 30, CURB_OFFSET_M, 1, ' m')
        self.sp_curb.setToolTip('Relocate: a sign that would land closer than this (sideways) to the '
                                "camera's driving line is on the road - it is moved out to this "
                                'distance, beside the curb. 0 = off')
        self.sp_group.setToolTip('DBSCAN distance: photos whose estimated sign positions are closer '
                                 'than this are grouped as ONE physical sign')
        for lbl, w in (('Camera FOV', self.sp_fov), ('Sign width', self.sp_sign),
                       ('Min dist', self.sp_min), ('Max dist', self.sp_max),
                       ('Same-sign dist', self.sp_group), ('Curb offset', self.sp_curb)):
            rel.addWidget(labelled(lbl, w))

        self.source_lbl = QLabel()
        self.status = QLabel()

        scroll = self.make_grid()

        self.source_lbl.setWordWrap(True)
        self.source_lbl.setMinimumWidth(480)
        info = FlowLayout(spacing=16)
        info.addWidget(self.source_lbl)
        info.addWidget(self.status)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(rel)
        self.sel_bar = SelectionBar(self)
        lay.addWidget(self.sel_bar)
        lay.addLayout(info)
        hint = QLabel('Drag = lasso select  |  Click = select/unselect  |  Shift+click = select a run  |  '
                      'Tick box = select  |  Right-click = full photo  |  ← → = page')
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#607d8b;')
        lay.addWidget(hint)
        lay.addWidget(scroll, 1)
        make_window(self)
        fit_to_screen(self, *self.size_for(COLS, 950))

        self.btn_prev.clicked.connect(lambda: self.goto(self.page - 1))
        self.btn_next.clicked.connect(lambda: self.goto(self.page + 1))
        self.btn_best.clicked.connect(self.open_best)
        self.btn_near.toggled.connect(self.toggle_near_tool)
        for sp in (self.sp_fov, self.sp_sign, self.sp_min, self.sp_max):
            sp.valueChanged.connect(lambda *_: self.regroup_timer.start())
        self.sp_group.valueChanged.connect(lambda *_: self.regroup_timer.start())
        self.regroup_timer = QTimer(self)
        self.regroup_timer.setSingleShot(True)
        self.regroup_timer.setInterval(700)
        self.regroup_timer.timeout.connect(self.regroup)

        self.reload_timer = QTimer(self)
        self.reload_timer.setSingleShot(True)
        self.reload_timer.setInterval(400)
        self.reload_timer.timeout.connect(self.load_items)
        self.layer.selectionChanged.connect(self.on_selection_changed)
        self.finished.connect(self.cleanup)

        self.load_items()

    @staticmethod
    def spin(lo, hi, val, dec, suffix):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setValue(val)
        s.setSuffix(suffix)
        return s

    def on_selection_changed(self, *args):
        if not self._busy:
            self.reload_timer.start()

    def load_items(self):
        n_sel = self.layer.selectedFeatureCount()
        if not n_sel and self.layer.featureCount() > MAX_WHOLE_LAYER:
            self.items, self.info, self.sign_members, self.sign_no, self.best = [], {}, {}, {}, {}
            self.pages, self.page = 1, 0
            clear_grid(self.grid)
            self.tiles = []
            self.source_lbl.setText(f'<b>Select a cluster of points on the map</b> - the whole layer has '
                                    f'{self.layer.featureCount()} points (limit {MAX_WHOLE_LAYER}, see config.py)')
            self.update_status()
            self.update_best_folder()
            return
        feats = self.layer.selectedFeatures() if n_sel else self.layer.getFeatures()
        self.items, self.info = [], {}
        for f in feats:
            d = self.build_info(f)
            self.info[f.id()] = d
            self.items.append((f.id(), d['url'], d['boxes']))
        self.pages = max(1, (len(self.items) + PER_PAGE - 1) // PER_PAGE)
        if n_sel:
            self.source_lbl.setText(f'<b>Reviewing {len(self.items)} SELECTED points</b>')
        else:
            self.source_lbl.setText(f'<b>Reviewing the WHOLE layer ({len(self.items)} points)</b>')
        self.order_items()
        self.sides, self.road_axis = self.classify_sides(self.order())
        keep = set(self.order())
        self.selected &= keep
        if self.anchor not in keep:
            self.anchor = None
        self.goto(0)
        self.selection_changed()
        self.update_best_folder()
        for b in list(self.bars):
            b.update_state()

    def page_items(self, n):
        return self.items[n * PER_PAGE:(n + 1) * PER_PAGE]

    def goto(self, n):
        if n < 0 or n >= self.pages:
            return
        self.page = n
        items = self.page_items(n)
        self.status.setText('Downloading images…')
        QApplication.processEvents()

        futs = [self.pool.submit(fetch, url) for _, url, _ in items]
        while not all(f.done() for f in futs):
            QApplication.processEvents()
            time.sleep(0.05)
        for m in (n + 1, n + 2):
            for _, url, _ in self.page_items(m):
                self.pool.submit(fetch, url)

        clear_grid(self.grid)
        self.tiles = []
        for (fid, url, boxes), fut in zip(items, futs):
            pix = render(fut.result(), boxes, True)
            sign = self.sign_no.get(fid)
            extra = ''
            if sign:
                meth = self.sign_pos.get(sign, (0, 0, ''))[2]
                extra = f'sign {sign} ({len(self.sign_members[sign])}, {"tri" if meth == "triangulated" else "est"})'
            rs = self.rel.get(fid)
            if rs is not None:
                extra += f'  |  sharp {rs * 100:.0f}%'
            t = Tile(self, fid, pix, self.caption(fid, extra))
            if sign and self.best.get(sign) == fid:
                t.best = True
                t.cap.setText('<span style="color:#2e7d32;font-weight:bold">★ BEST</span>  ' + t.cap.text())
                t.refresh()
            fl = self.flags.get(fid)
            if fl:
                t.cap.setText(t.cap.text() + '<br><span style="color:#e53935;font-weight:bold">⚠ '
                              + ', '.join(fl) + '</span>')
            self.tiles.append(t)
        self._cols = self.fit_cols()
        self.flow(self.tiles)
        self.update_status()

    def keyPressEvent(self, e):
        if self.handle_select_keys(self, e):
            return
        if e.key() == Qt.Key.Key_Right:
            self.goto(self.page + 1)
        elif e.key() == Qt.Key.Key_Left:
            self.goto(self.page - 1)
        else:
            super().keyPressEvent(e)

    def order(self):
        return [i[0] for i in self.items]

    def update_status(self):
        self.status.setText(f'Page {self.page + 1} / {self.pages}')

    def cleanup(self, *args):
        """Runs when the window is closed (X button, Esc or a new run)."""
        try:
            self.layer.selectionChanged.disconnect(self.on_selection_changed)
        except Exception:
            pass
        self.reload_timer.stop()
        if self.near_tool is not None:
            self.btn_near.setChecked(False)
        self.clear_selection_highlights()
        self.selected = set()
        self.canvas.refresh()
