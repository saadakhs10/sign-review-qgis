# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared widgets: progress waiting, the re-flowing tile grid with lasso selection."""

import time

from qgis.PyQt.QtCore import Qt, QRect, QTimer, QSize, QPoint
from qgis.PyQt.QtWidgets import (QApplication, QHBoxLayout, QGridLayout, QLabel,
                                 QScrollArea, QWidget, QProgressDialog, QRubberBand,
                                 QLayout)

from ..config import (COLS, THUMB)

def wait_for(futures, label, parent):
    """Wait for background downloads with a progress bar. Returns False if cancelled."""
    futures = list(futures)
    if not futures:
        return True
    if all(f.done() for f in futures):
        return True
    dlg = QProgressDialog(label, 'Cancel', 0, len(futures), parent)
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(300)
    while True:
        done = sum(f.done() for f in futures)
        dlg.setValue(done)
        dlg.setLabelText(f'{label}  {done} / {len(futures)}')
        if done == len(futures):
            break
        if dlg.wasCanceled():
            for f in futures:
                f.cancel()
            dlg.close()
            return False
        QApplication.processEvents()
        time.sleep(0.05)
    dlg.close()
    return True

def clear_grid(grid):
    while grid.count():
        w = grid.takeAt(0).widget()
        if w:
            w.hide()
            w.setParent(None)
            w.deleteLater()


class FlowLayout(QLayout):
    """Like a row of buttons, but wraps onto the next line when the window is narrow,
    so the window can be made small without cutting buttons off."""

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items = []
        self._space = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):  # noqa: N802
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):  # noqa: N802
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):  # noqa: N802
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation.Horizontal

    def hasHeightForWidth(self):  # noqa: N802
        return True

    def heightForWidth(self, width):  # noqa: N802
        return self._place(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):  # noqa: N802
        super().setGeometry(rect)
        self._place(rect, dry=False)

    def sizeHint(self):  # noqa: N802
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _place(self, rect, dry):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            nxt = x + hint.width() + self._space
            if nxt - self._space > r.right() + 1 and line_h > 0:
                x, y = r.x(), y + line_h + self._space
                nxt = x + hint.width() + self._space
                line_h = 0
            if not dry:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nxt
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()

def labelled(text, widget):
    """A label and its control kept together (they wrap as one piece)."""
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    h.addWidget(QLabel(text))
    h.addWidget(widget)
    return box

def make_window(w, min_w=520, min_h=380):
    """Give a dialog the normal title-bar buttons: minimize, maximize, close."""
    w.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowTitleHint |
                     Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinimizeButtonHint |
                     Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
    w.setMinimumSize(min_w, min_h)
    w.setSizeGripEnabled(True) if hasattr(w, 'setSizeGripEnabled') else None

def fit_to_screen(w, want_w, want_h):
    """Open at the wanted size but never bigger than the screen, centred on it."""
    scr = (w.screen() if hasattr(w, 'screen') and w.screen() else QApplication.primaryScreen())
    av = scr.availableGeometry()
    ww = int(min(want_w, av.width() * 0.92))
    hh = int(min(want_h, av.height() * 0.88))
    w.resize(ww, hh)
    w.move(av.x() + (av.width() - ww) // 2, av.y() + (av.height() - hh) // 2)

def global_pos(e):
    return e.globalPosition().toPoint() if hasattr(e, 'globalPosition') else e.globalPos()


class GridHost(QWidget):
    """The area behind the tiles: press and drag here to draw a selection rectangle."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.owner.lasso_press(global_pos(e))

    def mouseMoveEvent(self, e):
        self.owner.lasso_move(global_pos(e))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.owner.lasso_release(global_pos(e))

from ..features.f07_lasso import LassoMixin
from ..features.f03_left_right import LeftRightGridMixin


class TileGrid(LassoMixin, LeftRightGridMixin):
    """Mixin: lays tiles out in as many columns as fit the window, re-flows on resize,
    and lets you drag a selection rectangle (lasso) over the tiles."""

    def make_grid(self):
        host = GridHost(self)
        self.grid_host = host
        self.rubber = QRubberBand(QRubberBand.Shape.Rectangle, host)
        self._lasso_origin, self._lasso_active = None, False
        self.grid = QGridLayout(host)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.grid.setSpacing(6)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(host)
        self._cols = COLS
        return self.scroll

    def tile_width(self):
        tiles = getattr(self, 'tiles', None)
        return (tiles[0].sizeHint().width() if tiles else THUMB + 12) + self.grid.spacing()

    def fit_cols(self):
        w = self.scroll.viewport().width() - 20
        return max(1, w // self.tile_width())

    def size_for(self, cols, height):
        """Window size that shows `cols` tiles per row without cutting any."""
        return cols * self.tile_width() + 90, height

    def reflow(self):
        """Re-arrange tiles if a different number of columns fits now."""
        if not hasattr(self, 'scroll'):
            return
        c = self.fit_cols()
        if c != self._cols:
            self._cols = c
            if getattr(self, 'tiles', None):
                self.flow(self.tiles)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self.reflow)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.reflow)
