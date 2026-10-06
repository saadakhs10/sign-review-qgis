# SPDX-License-Identifier: GPL-2.0-or-later
"""Run Sign Review from the QGIS Python Console WITHOUT installing the plugin
(handy while developing).  Plugins > Python Console > Show Editor > open this file > Run.
Reload after editing the code: just run this file again."""
import importlib
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

for name in [m for m in sys.modules if m == 'sign_review' or m.startswith('sign_review.')]:
    del sys.modules[name]

app = importlib.import_module('sign_review.app')
app.open_reviewer()
