# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 8 - RELOCATE AND RESET TO CAMERA
Relocate moves each selected point from the camera to the sign, with ITS OWN photo:
    bearing  = heading + angle                (block 2)
    distance = sign width x focal / box width (block 2)
    new point = camera position + distance in the bearing direction
If the new point is on the road - closer than "Curb offset" (default 5 m) sideways to
the driving line - it is moved out beside the curb.
Reset to camera puts the selected points back on original_x / original_y.
"""

import math

from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import (QgsGeometry, QgsPointXY, QgsWkbTypes)
from qgis.utils import iface

from ..config import (ORIG_X_FIELD, ORIG_Y_FIELD)
from ..core.io import fetch, image_width
from ..core.parsing import largest_box
from ..ui.widgets import wait_for

from ..ui.widgets import wait_for


class RelocateMixin:
    """Relocate and reset to camera - mixed into the review window."""

    # ── 8.1  estimate() : sign position from one photo (+ curb offset) ────────────────────────
    def estimate(self, fid, img_w):
        """Sign position (lon, lat) from camera position, heading and the box."""
        d = self.get_info(fid)
        if not d or not d['boxes'] or d['cam'] is None or d['heading'] is None or not img_w:
            return None
        x1, y1, x2, y2 = largest_box(d['boxes'])
        box_w = max(1, x2 - x1)
        cx = (x1 + x2) / 2.0
        focal = (img_w / 2.0) / math.tan(math.radians(self.sp_fov.value() / 2.0))
        bearing = d['heading'] + math.degrees(math.atan((cx - img_w / 2.0) / focal))
        dist = self.sp_sign.value() * focal / box_w
        dist = min(max(dist, self.sp_min.value()), self.sp_max.value())
        lon, lat = d['cam']
        ang = math.radians(bearing - d['heading'])
        along, side = dist * math.cos(ang), dist * math.sin(ang)
        curb = self.sp_curb.value() if hasattr(self, 'sp_curb') else 0.0
        if curb > 0 and abs(side) < curb:
            side = curb if side >= 0 else -curb
        h = math.radians(d['heading'])
        east = along * math.sin(h) + side * math.cos(h)
        north = along * math.cos(h) - side * math.sin(h)
        dlat = north / 111320.0
        dlon = east / (111320.0 * math.cos(math.radians(lat)))
        return lon + dlon, lat + dlat

    # ── 8.2  relocate() : move the points (one undo step) ─────────────────────────────────────
    def relocate(self, fids, what, ask=True):
        if not fids:
            return
        ans = QMessageBox.StandardButton.Yes if not ask else QMessageBox.question(
            self, 'Relocate',
            f'Move {len(fids)} {what} points from the camera position to the sign position?\n'
            'Each point is moved with its own photo:\n'
            '   direction = heading + atan((box centre x - W/2) / focal)\n'
            '   distance  = sign width x focal / box width,   focal = (W/2) / tan(FOV/2)\n'
            f'   on the road (closer than {self.sp_curb.value():.1f} m to the driving line)? '
            '-> moved out beside the curb\n'
            f'(FOV {self.sp_fov.value():.0f}°, sign width {self.sp_sign.value():.2f} m)\n\n'
            'Undo works until you Save Layer Edits; "Reset to camera" puts them back.')
        if ans != QMessageBox.StandardButton.Yes:
            return
        futs = {fid: self.pool.submit(fetch, self.get_info(fid)['url']) for fid in fids}
        if not wait_for(futs.values(), 'Downloading images…', self):
            return

        self.ensure_editing()
        self.layer.beginEditCommand('Relocate signs')
        moved, skipped = [], []
        for fid in fids:
            est = self.estimate(fid, image_width(futs[fid].result()))
            if est is None:
                skipped.append(fid)
                continue
            pt = self.to_layer.transform(QgsPointXY(*est))
            if self.layer.changeGeometry(fid, self.make_geom(pt)):
                moved.append(fid)
            else:
                skipped.append(fid)
        self.layer.endEditCommand()
        self.refresh_moved(moved)
        self.update_status()
        msg = f'{len(moved)} points relocated'
        if skipped:
            msg += f', {len(skipped)} skipped (no image, box, heading or camera position)'
            print('Relocate skipped fids:', skipped)
        iface.messageBar().pushSuccess('Sign review', msg + ' - check them, then Save Layer Edits')

    # ── 8.3  relocate_selected() : Relocate button ────────────────────────────────────────────
    def relocate_selected(self):
        if self.selected:
            self.relocate(sorted(self.selected), 'selected')

    # ── 8.4  reset_to_camera() : put points back on the camera ────────────────────────────────
    def reset_to_camera(self, fids, what):
        fids = [fid for fid in fids if self.get_info(fid)['cam']]
        if not fids:
            return
        if QMessageBox.question(self, 'Reset',
                                f'Put {len(fids)} {what} points back on the camera position '
                                f'({ORIG_X_FIELD} / {ORIG_Y_FIELD})?') != QMessageBox.StandardButton.Yes:
            return
        self.ensure_editing()
        self.layer.beginEditCommand('Reset signs to camera')
        for fid in fids:
            pt = self.to_layer.transform(QgsPointXY(*self.get_info(fid)['cam']))
            self.layer.changeGeometry(fid, self.make_geom(pt))
        self.layer.endEditCommand()
        self.refresh_moved(fids)
        iface.messageBar().pushInfo('Sign review', f'{len(fids)} points reset to camera position')

    # ── 8.5  reset_selected() : Reset to camera button ────────────────────────────────────────
    def reset_selected(self):
        if self.selected:
            self.reset_to_camera(sorted(self.selected), 'selected')

    # ── 8.6  make_geom() : point geometry in the layer type ───────────────────────────────────
    def make_geom(self, pt_layer_crs):
        if QgsWkbTypes.isMultiType(self.layer.wkbType()):
            return QgsGeometry.fromMultiPointXY([pt_layer_crs])
        return QgsGeometry.fromPointXY(pt_layer_crs)

    # ── 8.7  ensure_editing() : switch the layer to editing ───────────────────────────────────
    def ensure_editing(self):
        if not self.layer.isEditable():
            self.layer.startEditing()

    # ── 8.8  refresh_moved() : redraw after points moved ──────────────────────────────────────
    def refresh_moved(self, fids):
        self._all = None
        self.clear_selection_highlights()
        self.sync_selection_highlights()
        self.layer.triggerRepaint()
        self.canvas.refresh()
