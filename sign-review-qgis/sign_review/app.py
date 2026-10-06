# SPDX-License-Identifier: GPL-2.0-or-later
"""Open / close the review window (used by the toolbar button and the console runner)."""

from qgis.utils import iface

_reviewer = None


def open_reviewer():
    """Open the review window for the active layer (selected points, or the whole layer)."""
    global _reviewer
    close_reviewer()
    layer = iface.activeLayer()
    if layer is None or not hasattr(layer, 'selectedFeatureCount'):
        iface.messageBar().pushWarning('Sign Review', 'Click your point layer in the Layers panel first')
        return None
    from .ui.reviewer import Reviewer
    try:
        _reviewer = Reviewer(layer)
    except Exception as e:
        iface.messageBar().pushCritical('Sign Review', str(e))
        return None
    _reviewer.show()
    _reviewer.raise_()
    return _reviewer


def close_reviewer():
    global _reviewer
    if _reviewer is not None:
        try:
            _reviewer.close()
        except Exception:
            pass
        _reviewer = None
