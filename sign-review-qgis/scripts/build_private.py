#!/usr/bin/env python3
"""Build a PRIVATE Sign Review plugin: people can install and use it, but the ZIP holds
no readable source code - only compiled Python bytecode (.pyc).

Two ways to run it
------------------
1. Inside QGIS (recommended - always matches the team's Python):
       Plugins > Python Console > Show Editor > open this file > Run
   It builds from the Sign Review plugin installed in QGIS and writes
       <your Downloads folder>/sign_review_private_pyX.Y.zip

2. From a terminal, with the SAME Python version as the team's QGIS:
       python3.12 scripts/build_private.py            ->  dist/sign_review_private_py3.12.zip

IMPORTANT
  * Bytecode only runs on the Python version it was built with (QGIS 3.34 and newer on
    Windows use Python 3.12). Everyone must use QGIS with that same Python version.
    The version is written into the ZIP name and the plugin description.
  * Compiled with optimize=2: comments and docstrings are removed as well.
  * This hides the code from normal users. It is not encryption: a determined
    programmer with decompiler tools can still recover parts of it.
"""
import os
import py_compile
import shutil
import sys
import tempfile
import zipfile

PKG = 'sign_review'
KEEP_SOURCE = {os.path.join(PKG, '__init__.py')}
SKIP_DIRS = {'__pycache__'}


def find_source():
    """The plugin folder: next to this script (repository) or installed in QGIS."""
    here = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    repo_pkg = os.path.join(os.path.dirname(here), PKG)
    if os.path.isfile(os.path.join(repo_pkg, 'metadata.txt')):
        return repo_pkg
    try:
        from qgis.core import QgsApplication
        inst = os.path.join(QgsApplication.qgisSettingsDirPath(), 'python', 'plugins', PKG)
        if os.path.isfile(os.path.join(inst, 'metadata.txt')):
            return inst
    except ImportError:
        pass
    raise SystemExit('Sign Review plugin folder not found.')


def build(src_pkg, out_zip):
    pyver = f'{sys.version_info.major}.{sys.version_info.minor}'
    work = tempfile.mkdtemp()
    dst_pkg = os.path.join(work, PKG)
    shutil.copytree(src_pkg, dst_pkg, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))

    with open(os.path.join(dst_pkg, '__init__.py'), 'w', encoding='utf-8') as f:
        f.write('# Sign Review (private build for Python %s)\n\n'
                'def classFactory(iface):\n'
                '    from .plugin import SignReviewPlugin\n'
                '    return SignReviewPlugin(iface)\n' % pyver)

    compiled = 0
    for root, dirs, files in os.walk(dst_pkg):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith('.py'):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, work)
            if rel in KEEP_SOURCE:
                continue
            py_compile.compile(full, cfile=full + 'c', dfile=rel, doraise=True, optimize=2)
            os.remove(full)
            compiled += 1

    meta = os.path.join(dst_pkg, 'metadata.txt')
    with open(meta, encoding='utf-8') as f:
        text = f.read()
    note = f'Private build for Python {pyver} (QGIS with Python {pyver}). '
    text = text.replace('\nabout=', '\nabout=' + note, 1)
    with open(meta, 'w', encoding='utf-8') as f:
        f.write(text)

    os.makedirs(os.path.dirname(out_zip), exist_ok=True)
    with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(dst_pkg):
            for fn in sorted(files):
                full = os.path.join(root, fn)
                z.write(full, os.path.relpath(full, work))
    shutil.rmtree(work, ignore_errors=True)
    return compiled, pyver


def main():
    src = find_source()
    pyver = f'{sys.version_info.major}.{sys.version_info.minor}'
    try:
        from qgis.utils import iface                        # noqa: F401
        out = os.path.join(os.path.expanduser('~'), 'Downloads', f'{PKG}_private_py{pyver}.zip')
    except ImportError:
        out = os.path.join(os.path.dirname(src), 'dist', f'{PKG}_private_py{pyver}.zip')
    n, pyver = build(src, out)
    msg = f'Private plugin written to {out}  ({n} modules compiled, Python {pyver}, no .py source)'
    print(msg)
    try:
        from qgis.utils import iface
        iface.messageBar().pushSuccess('Sign Review', msg)
    except Exception:
        pass


main()
