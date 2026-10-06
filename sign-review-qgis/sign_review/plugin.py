# SPDX-License-Identifier: GPL-2.0-or-later
"""QGIS plugin glue: toolbar button, menu entries (Sign Review, Help on GitHub,
Report an issue) and the Ctrl+Shift+R shortcut."""

import configparser
import os

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtGui import QIcon, QKeySequence, QDesktopServices
from qgis.PyQt.QtWidgets import QAction

MENU = '&Sign Review'


class SignReviewPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.links = []
        meta = configparser.ConfigParser(interpolation=None)
        meta.read(os.path.join(os.path.dirname(__file__), 'metadata.txt'), encoding='utf-8')
        self.homepage = meta['general'].get('homepage', '')
        self.tracker = meta['general'].get('tracker', '')

    def initGui(self):  # noqa: N802
        icon = QIcon(os.path.join(os.path.dirname(__file__), 'icons', 'icon.png'))
        self.action = QAction(icon, 'Sign Review', self.iface.mainWindow())
        self.action.setToolTip('Sign Review - review the selected points '
                               '(or the whole layer if nothing is selected)')
        self.action.setShortcut(QKeySequence('Ctrl+Shift+R'))
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(MENU, self.action)
        for text, url in (('Help and documentation (GitHub)', self.homepage),
                          ('Report an issue', self.tracker)):
            if url:
                a = QAction(text, self.iface.mainWindow())
                a.triggered.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
                self.iface.addPluginToMenu(MENU, a)
                self.links.append(a)

    def unload(self):
        from .app import close_reviewer
        close_reviewer()
        self.iface.removePluginMenu(MENU, self.action)
        for a in self.links:
            self.iface.removePluginMenu(MENU, a)
        self.iface.removeToolBarIcon(self.action)
        self.action.deleteLater()

    def run(self):
        from .app import open_reviewer
        open_reviewer()
