# SPDX-License-Identifier: GPL-2.0-or-later
"""BLOCK 11 - MAP, STREET AND FULL PHOTO
Map    = pan the QGIS map to the point and flash it.
Street = open Google Street View at the camera position, facing the camera heading.
Right-click on a tile = the whole photo with its box in red.
"""

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import (QImage, QDesktopServices)
from qgis.PyQt.QtWidgets import (QApplication, QDialog, QVBoxLayout, QLabel)
from qgis.core import QgsFeatureRequest
from qgis.utils import iface

from ..core.io import fetch
from ..core.imaging import render


class MapStreetMixin:
    """Map, street and full photo - mixed into the review window."""

    # ── 11.1  pan_to() : Map button ───────────────────────────────────────────────────────────
    def pan_to(self, fid):
        feat = next(self.layer.getFeatures(QgsFeatureRequest().setFilterFid(fid)), None)
        if feat is None or not feat.hasGeometry():
            return
        p = self.canvas.mapSettings().layerToMapCoordinates(
            self.layer, feat.geometry().centroid().asPoint())
        self.canvas.setCenter(p)
        self.canvas.refresh()
        self.canvas.flashFeatureIds(self.layer, [fid])

    # ── 11.2  open_streetview() : Street button ───────────────────────────────────────────────
    def open_streetview(self, fid):
        d = self.get_info(fid)
        if not d.get('cam'):
            iface.messageBar().pushWarning('Sign review', f'fid {fid}: no camera position')
            return
        lon, lat = d['cam']
        url = (f'https://www.google.com/maps/@?api=1&map_action=pano'
               f'&viewpoint={lat:.7f},{lon:.7f}')
        if d.get('heading') is not None:
            url += f'&heading={d["heading"] % 360:.0f}'
        QDesktopServices.openUrl(QUrl(url))

    # ── 11.3  show_full() : right-click on a tile ─────────────────────────────────────────────
    def show_full(self, fid):
        """Right-click on a tile -> the whole photo."""
        FullImageDialog(self, fid).show()


# ══ 11.4  FullImageDialog : the full photo window ═════════════════════════════════════════════


class FullImageDialog(QDialog):
    """The whole photo of one point, its detected box drawn in red."""

    def __init__(self, rv, fid):
        super().__init__(rv)
        d = rv.get_info(fid)
        path = fetch(d['url'])
        self.setWindowTitle(f'fid {fid} - full photo')
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowTitleHint |
                            Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinimizeButtonHint |
                            Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
        lay = QVBoxLayout(self)
        img = QImage(path) if path else QImage()
        if img.isNull():
            lay.addWidget(QLabel('Image could not be loaded:\n' + str(d['url'])))
            return
        av = (self.screen() if hasattr(self, 'screen') and self.screen()
              else QApplication.primaryScreen()).availableGeometry()
        max_w, max_h = int(av.width() * 0.85), int(av.height() * 0.8)
        pix = render(path, d['boxes'], crop=False, size=max(img.width(), img.height()))
        pix = pix.scaled(min(max_w, img.width()), min(max_h, img.height()),
                         Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        lbl = QLabel()
        lbl.setPixmap(pix)
        lbl.setFixedSize(pix.size())
        lay.addWidget(lbl, 0, Qt.AlignmentFlag.AlignCenter)
        self.adjustSize()
        self.move(av.x() + max(0, (av.width() - self.width()) // 2),
                  av.y() + max(0, (av.height() - self.height()) // 2))
