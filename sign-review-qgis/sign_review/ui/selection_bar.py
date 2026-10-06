# SPDX-License-Identifier: GPL-2.0-or-later
"""The blue selection bar (Select best / Invert / ... / Relocate / Delete)."""


from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QLabel, QPushButton, QFrame)

from .widgets import FlowLayout


class SelectionBar(QFrame):
    """'N selected' + Select all, then Clear / Reset to camera / Relocate / Delete
    (active once something is selected)."""

    def __init__(self, rv):
        super().__init__()
        self.rv = rv
        self.setStyleSheet('SelectionBar {background:#e3f2fd; border:1px solid #90caf9; border-radius:4px;}')
        h = FlowLayout(self)
        h.setContentsMargins(8, 4, 8, 4)
        self.lbl = QLabel()
        self.btns = []
        h.addWidget(self.lbl)
        for text, fn in (('Select all', rv.select_all_shown),):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(fn)
            h.addWidget(b)
        sep = QLabel('│')
        sep.setStyleSheet('color:#90caf9;')
        h.addWidget(sep)
        for text, fn, style in (
                ('Clear', rv.clear_selection, ''),
                ('Reset to camera', rv.reset_selected, ''),
                ('Relocate', rv.relocate_selected,
                 'background:#1e88e5;color:white;font-weight:bold;padding:4px 10px;'),
                ('Delete', rv.delete_selected,
                 'background:#e53935;color:white;font-weight:bold;padding:4px 10px;')):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if style:
                b.setProperty('active_style', style)
            b.clicked.connect(fn)
            h.addWidget(b)
            self.btns.append(b)
        rv.bars.append(self)
        self.update_state()

    def update_state(self):
        n = len(self.rv.selected)
        self.lbl.setText(f'<b>{n} selected</b>' if n else 'Nothing selected')
        for b in self.btns:
            b.setEnabled(bool(n))
            st = b.property('active_style')
            if st:
                b.setStyleSheet(st if n else '')
