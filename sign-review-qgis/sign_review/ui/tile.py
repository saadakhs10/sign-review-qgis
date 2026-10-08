# SPDX-License-Identifier: GPL-2.0-or-later
"""One picture tile: checkbox, photo with its box, caption and Map / Street / Near buttons."""


from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QApplication, QVBoxLayout, QHBoxLayout, QLabel,
                                 QPushButton, QFrame, QCheckBox)

from ..config import THUMB
from .widgets import global_pos


class Tile(QFrame):
    """Compact tile: the cropped photo (no empty space around it) and, under it, one
    small info strip: checkbox + caption, then the Map / Street / Near buttons."""

    def __init__(self, dlg, fid, pix, caption, owner=None):
        super().__init__()
        self.dlg, self.fid = dlg, fid
        self.owner = owner or dlg
        self.setFrameShape(QFrame.Shape.NoFrame)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)

        self.img = QLabel()
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setToolTip('Drag: lasso select  |  Click: select/unselect  |  Shift+click: select a run  |  '
                            'Right-click: full photo')
        if pix:
            self.img.setPixmap(pix)
            self.img.setFixedSize(pix.size())
        else:
            self.img.setText('NO IMAGE / NO BOX')
            self.img.setFixedSize(THUMB, 60)

        info = QHBoxLayout()
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(4)
        self.chk = QCheckBox()
        self.chk.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.chk.setStyleSheet('QCheckBox::indicator {width: 16px; height: 16px;}')
        self.chk.toggled.connect(self.on_check)
        self.chk.setToolTip('Select')
        self.cap = QLabel(caption)
        self.cap.setWordWrap(True)
        self.cap.setStyleSheet('font-size: 10px;')
        info.addWidget(self.chk, 0, Qt.AlignmentFlag.AlignTop)
        info.addWidget(self.cap, 1)

        btns = QHBoxLayout()
        btns.setContentsMargins(0, 0, 0, 0)
        btns.setSpacing(2)
        for text, fn in (('Map', dlg.pan_to), ('Street', dlg.open_streetview),
                         ('Near', dlg.open_nearby)):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet('font-size: 10px; padding: 1px 4px;')
            b.setFixedHeight(20)
            b.clicked.connect(lambda _=False, f=fn: f(self.fid))
            btns.addWidget(b)
        if hasattr(dlg, 'pick_toggle'):                     # block 14: ⭐ My best / ↩ Back
            back = getattr(self.owner, 'is_my_best', False)
            b = QPushButton('↩ Back' if back else '⭐')
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet('font-size: 10px; padding: 1px 4px;')
            b.setFixedHeight(20)
            b.setToolTip('Back to the main window' if back else
                         'Move this photo to the ⭐ My best window')
            b.clicked.connect(lambda _=False: dlg.pick_toggle(self.fid))
            btns.addWidget(b)
        lay.addWidget(self.img, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addLayout(info)
        lay.addLayout(btns)
        self.setFixedWidth(THUMB + 12)
        self.refresh()

    def refresh(self):
        sel = self.fid in self.dlg.selected
        self.chk.blockSignals(True)
        self.chk.setChecked(sel)
        self.chk.blockSignals(False)
        if sel:
            border, bg = '#1565c0', '#bbdefb'
        elif getattr(self, 'best', False):
            border, bg = '#f9a825', '#fffde7'
        else:
            border, bg = '#bdbdbd', 'white'
        self.setStyleSheet('Tile {border: 3px solid %s; border-radius: 4px; background: %s;}' % (border, bg))

    def on_check(self, checked):
        """Ticking / unticking the box selects / unselects the picture."""
        self.dlg.set_selected(self.fid, checked)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.owner.lasso_press(global_pos(e))
        elif e.button() == Qt.MouseButton.RightButton:
            self.dlg.show_full(self.fid)

    def mouseMoveEvent(self, e):
        self.owner.lasso_move(global_pos(e))

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        if self.owner.lasso_release(global_pos(e)):
            return
        m = QApplication.queryKeyboardModifiers()
        shift = (m & Qt.KeyboardModifier.ShiftModifier) == Qt.KeyboardModifier.ShiftModifier
        self.dlg.click_select(self.owner, self.fid, shift)
