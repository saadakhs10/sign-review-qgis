# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 9 - NEARBY (Near) AND SNAP TOGETHER
📍 Nearby: click a point on the map (or Near under a tile) -> a popup shows that point and
every point whose CURRENT position is within the distance you set (starts at 1 m; type a
value or scroll), nearest first, Left | Right.
🧲 Snap together: moves the ticked points (or all shown) onto ONE spot - the clicked point
or their middle. Points already there are not moved.
"""

import math

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QLabel, QPushButton,
                                 QMessageBox, QDoubleSpinBox, QComboBox)
from qgis.core import (QgsFeatureRequest, QgsPointXY, QgsRectangle)
from qgis.gui import QgsMapToolEmitPoint
from qgis.utils import iface

from ..config import (COLS, NEARBY_RADIUS_M, NEARBY_MAX_M, SNAP_TOL_M)
from ..core.io import fetch
from ..core.geometry import LocalXY
from ..core.imaging import render
from ..ui.widgets import TileGrid, wait_for, clear_grid, FlowLayout, make_window, fit_to_screen
from ..ui.selection_bar import SelectionBar
from ..ui.tile import Tile

from ..ui.widgets import clear_grid, wait_for, TileGrid


class NearbyMixin:
    """Nearby (near) and snap together - mixed into the review window."""

    # ── 9.1  point_lonlat() : current position of a point (WGS 84) ────────────────────────────
    def point_lonlat(self, fid):
        """Current position of the point on the map (WGS84), or None."""
        feat = next(self.layer.getFeatures(QgsFeatureRequest().setFilterFid(fid)), None)
        if feat is None or not feat.hasGeometry() or feat.geometry().isEmpty():
            return None
        p = self.to_wgs.transform(feat.geometry().centroid().asPoint())
        return p.x(), p.y()

    # ── 9.2  points_near() : points within a distance, in metres ──────────────────────────────
    def points_near(self, fid, radius_m):
        """[(fid, metres)] of the points whose CURRENT position is within radius_m of fid's,
        nearest first (the clicked point itself first, at 0 m)."""
        c = self.point_lonlat(fid)
        if c is None:
            return [(fid, 0.0)]
        L = LocalXY(*c)
        dlat = radius_m / 111320.0
        dlon = radius_m / (111320.0 * max(0.01, math.cos(math.radians(c[1]))))
        a = self.to_layer.transform(QgsPointXY(c[0] - dlon, c[1] - dlat))
        b = self.to_layer.transform(QgsPointXY(c[0] + dlon, c[1] + dlat))
        rect = QgsRectangle(min(a.x(), b.x()), min(a.y(), b.y()), max(a.x(), b.x()), max(a.y(), b.y()))
        out = []
        for feat in self.layer.getFeatures(QgsFeatureRequest().setFilterRect(rect)):
            if not feat.hasGeometry() or feat.geometry().isEmpty():
                continue
            p = self.to_wgs.transform(feat.geometry().centroid().asPoint())
            x, y = L.xy(p.x(), p.y())
            dm = math.hypot(x, y)
            if dm <= radius_m or feat.id() == fid:
                out.append((feat.id(), 0.0 if feat.id() == fid else dm))
        out.sort(key=lambda t: (t[0] != fid, t[1]))
        return out

    # ── 9.3  open_nearby() : open / update the Nearby popup ───────────────────────────────────
    def open_nearby(self, fid):
        for d in self.same_dialogs:
            if isinstance(d, NearbyDialog):
                d.set_center(fid)
                d.showNormal()
                d.raise_()
                return
        NearbyDialog(self, fid).show()

    # ── 9.4  toggle_near_tool() : 📍 Nearby map tool on / off ──────────────────────────────────
    def toggle_near_tool(self, on):
        """Map tool: click a point on the map -> Nearby window."""
        if on:
            self.near_prev_tool = self.canvas.mapTool()
            self.near_tool = QgsMapToolEmitPoint(self.canvas)
            self.near_tool.canvasClicked.connect(self.near_click)
            self.near_tool.deactivated.connect(lambda: self.btn_near.setChecked(False))
            self.canvas.setMapTool(self.near_tool)
            iface.messageBar().pushInfo('Sign review', 'Nearby: click a point on the map '
                                        '(right-click or the button again to stop)')
        elif self.near_tool is not None:
            tool, self.near_tool = self.near_tool, None
            if self.canvas.mapTool() is tool:
                if getattr(self, 'near_prev_tool', None) is not None:
                    self.canvas.setMapTool(self.near_prev_tool)
                else:
                    self.canvas.unsetMapTool(tool)

    # ── 9.5  near_click() : click on the map -> nearest point ─────────────────────────────────
    def near_click(self, point, button):
        if button != Qt.MouseButton.LeftButton:
            self.btn_near.setChecked(False)
            return
        ms = self.canvas.mapSettings()
        tol = 12 * self.canvas.mapUnitsPerPixel()
        r = QgsRectangle(point.x() - tol, point.y() - tol, point.x() + tol, point.y() + tol)
        r = ms.mapToLayerCoordinates(self.layer, r)
        here = ms.mapToLayerCoordinates(self.layer, QgsPointXY(point))
        best, best_d = None, None
        for feat in self.layer.getFeatures(QgsFeatureRequest().setFilterRect(r)):
            if not feat.hasGeometry() or feat.geometry().isEmpty():
                continue
            q = feat.geometry().centroid().asPoint()
            dd = (q.x() - here.x()) ** 2 + (q.y() - here.y()) ** 2
            if best_d is None or dd < best_d:
                best, best_d = feat.id(), dd
        if best is None:
            iface.messageBar().pushInfo('Sign review', 'Nearby: no point there - click closer to a point')
            return
        self.canvas.flashFeatureIds(self.layer, [best])
        self.open_nearby(best)

    # ── 9.6  snap_together() : put the points on one spot ─────────────────────────────────────
    def snap_together(self, fids, target_fid=None, what='ticked', ask=True):
        """🧲 Put points that are near each other on ONE spot.
        target_fid given -> onto that point's position, else onto the middle (average) of them.
        Points already within SNAP_TOL_M of the spot are not touched. Returns True if moved."""
        pos = {f: self.point_lonlat(f) for f in fids}
        pos = {f: p for f, p in pos.items() if p is not None}
        if len(pos) < 2:
            return False
        if target_fid is not None and target_fid in pos:
            spot, where = pos[target_fid], f'onto the clicked point (fid {target_fid})'
        else:
            L0 = LocalXY(*next(iter(pos.values())))
            xy = [L0.xy(*p) for p in pos.values()]
            mx, my = sum(x for x, _ in xy) / len(xy), sum(y for _, y in xy) / len(xy)
            spot = L0.lonlat(mx, my)
            where = 'onto the middle of them'
        L = LocalXY(*spot)
        to_move = [f for f, p in pos.items() if math.hypot(*L.xy(*p)) > SNAP_TOL_M]
        if not to_move:
            iface.messageBar().pushInfo('Sign review', f'The {len(pos)} points are already together')
            return False
        far = max(math.hypot(*L.xy(*pos[f])) for f in to_move)
        if ask and QMessageBox.question(
                self, 'Snap together',
                f'Snap {len(to_move)} of the {len(pos)} {what} points {where}?\n'
                f'({len(pos) - len(to_move)} already there; the farthest moves {far:.1f} m)\n\n'
                'Undo works until you Save Layer Edits; "Reset to camera" puts them back.'
        ) != QMessageBox.StandardButton.Yes:
            return False
        pt = self.to_layer.transform(QgsPointXY(*spot))
        self.ensure_editing()
        self.layer.beginEditCommand('Snap signs together')
        moved = [f for f in to_move if self.layer.changeGeometry(f, self.make_geom(pt))]
        self.layer.endEditCommand()
        self.refresh_moved(moved)
        self.update_status()
        iface.messageBar().pushSuccess('Sign review', f'{len(moved)} points snapped together '
                                       '- check them, then Save Layer Edits')
        return bool(moved)


# ══ 9.7  NearbyDialog : the Nearby popup window ═══════════════════════════════════════════════


class NearbyDialog(TileGrid, QDialog):
    """The point you clicked + every point placed near it (current positions on the map),
    nearest first, sorted Left | Right of the camera."""

    def __init__(self, rv, fid):
        super().__init__(rv)
        self.rv, self.fid, self.tiles, self.matches, self.dist = rv, fid, [], [], {}
        self.sp_r = QDoubleSpinBox()
        self.sp_r.setRange(0.05, NEARBY_MAX_M)
        self.sp_r.setDecimals(2)
        self.sp_r.setSingleStep(0.5)
        self.sp_r.setKeyboardTracking(False)
        self.sp_r.setValue(min(NEARBY_RADIUS_M, NEARBY_MAX_M))
        self.sp_r.setSuffix(' m')
        self.sp_r.setPrefix('within ')
        self.sp_r.setToolTip('Show the points this close to the clicked point. '
                             'Type a distance or scroll the mouse wheel to change it (starts at 1 m)')
        self.cb_snap = QComboBox()
        self.cb_snap.addItems(['onto the clicked point', 'onto their middle'])
        self.cb_snap.setToolTip('Where the points are snapped to')
        self.btn_snap = QPushButton('🧲 Snap together')
        self.btn_snap.setToolTip('Move the ticked points (or all shown, if none ticked) to one spot.\n'
                                 'Points that are already together are left alone.')
        self.btn_snap.clicked.connect(self.snap)
        self.info_lbl = QLabel()
        self.info_lbl.setWordWrap(True)
        self.info_lbl.setMinimumWidth(420)
        scroll = self.make_grid()
        make_window(self)
        fit_to_screen(self, *self.size_for(COLS, 700))
        self.sel_bar = SelectionBar(rv)
        top = FlowLayout()
        top.addWidget(self.sp_r)
        top.addWidget(self.btn_snap)
        top.addWidget(self.cb_snap)
        top.addWidget(self.info_lbl)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.sel_bar)
        lay.addWidget(scroll, 1)
        self.r_timer = QTimer(self)
        self.r_timer.setSingleShot(True)
        self.r_timer.setInterval(500)
        self.r_timer.timeout.connect(self.reload)
        self.sp_r.valueChanged.connect(lambda *_: self.r_timer.start())
        self.finished.connect(self.on_close)
        rv.same_dialogs.append(self)
        self.reload()

    def order(self):
        return list(self.matches)

    def set_center(self, fid):
        self.fid = fid
        self.reload()

    def reload(self):
        rv = self.rv
        near = rv.points_near(self.fid, self.sp_r.value())
        self.dist = dict(near)
        fids = [f for f, _ in near]
        futs = [rv.pool.submit(fetch, rv.get_info(f)['url']) for f in fids]
        if not wait_for(futs, 'Downloading images…', self):
            return
        paths = {f: fut.result() for f, fut in zip(fids, futs)}
        self.matches = fids
        self.sides, self.road_axis = rv.classify_sides(self.matches)
        rv.forget_tiles(self.tiles)
        clear_grid(self.grid)
        self.tiles = []
        for f in self.matches:
            here = 'CLICKED' if f == self.fid else f'{self.dist[f]:.2f} m away'
            n = rv.sign_no.get(f)
            extra = here + (f'  |  sign {n}' if n else '')
            t = Tile(rv, f, render(paths[f], rv.get_info(f)['boxes'], True),
                     rv.caption(f, extra), owner=self)
            if f == self.fid:
                t.cap.setStyleSheet('font-size: 10px; font-weight: bold; color: #1565c0;')
            self.tiles.append(t)
        self._cols = self.fit_cols()
        self.flow(self.tiles)
        rv.extra_tiles.extend(self.tiles)
        r = self.sp_r.value()
        self.setWindowTitle(f'📍 Nearby - fid {self.fid} and {len(fids) - 1} points within {r:g} m')
        if len(fids) > 1:
            self.info_lbl.setText(f'<b>fid {self.fid}</b> + <b>{len(fids) - 1}</b> points placed within '
                                  f'{r:g} m (nearest first)')
        else:
            self.info_lbl.setText(f'<b>fid {self.fid}</b>: no other point within {r:g} m')

    def snap(self):
        """🧲 Move the ticked points of this window (or all shown) onto one spot."""
        ticked = [f for f in self.matches if f in self.rv.selected]
        fids = ticked or list(self.matches)
        if len(fids) < 2:
            QMessageBox.information(self, 'Snap together', 'Tick at least 2 points to snap together.')
            return
        target = self.fid if self.cb_snap.currentIndex() == 0 else None
        if self.rv.snap_together(fids, target, 'ticked' if ticked else 'shown'):
            self.reload()

    def on_close(self, *args):
        self.rv.forget_tiles(self.tiles)
        if self.sel_bar in self.rv.bars:
            self.rv.bars.remove(self.sel_bar)
        if self in self.rv.same_dialogs:
            self.rv.same_dialogs.remove(self)

    def keyPressEvent(self, e):
        if self.rv.handle_select_keys(self, e):
            return
        super().keyPressEvent(e)
