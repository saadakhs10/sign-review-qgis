# SPDX-License-Identifier: GPL-2.0-or-later
"""Sign Review - QGIS plugin to review and localize road-sign detections."""


def classFactory(iface):  # noqa: N802  (name required by QGIS)
    from .plugin import SignReviewPlugin
    return SignReviewPlugin(iface)
