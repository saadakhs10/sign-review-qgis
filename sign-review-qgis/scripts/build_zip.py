#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the installable plugin ZIP and the plugins.xml repository file.

    python scripts/build_zip.py                      (GitHub user saadakhs10)
    python scripts/build_zip.py --version 1.5.0.12   (the release workflow sets the version)

Writes  dist/sign_review.zip   (install with Plugins > Manage and Install > Install from ZIP)
and     plugins.xml            (point QGIS at its raw GitHub URL to install / update)
"""
import argparse
import configparser
import datetime
import os
import re
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = 'sign_review'
REPO = 'sign-review-qgis'

XML = '''<?xml version="1.0" encoding="UTF-8"?>
<plugins>
  <pyqgis_plugin name="{name}" version="{version}" plugin_id="{pkg}">
    <description><![CDATA[{description}]]></description>
    <about><![CDATA[{about}]]></about>
    <version>{version}</version>
    <qgis_minimum_version>{qmin}</qgis_minimum_version>
    <qgis_maximum_version>{qmax}</qgis_maximum_version>
    <homepage><![CDATA[https://github.com/{user}/{repo}]]></homepage>
    <file_name>{pkg}.zip</file_name>
    <icon>https://raw.githubusercontent.com/{user}/{repo}/main/{pkg}/icons/icon.png</icon>
    <author_name><![CDATA[{author}]]></author_name>
    <download_url>https://github.com/{user}/{repo}/releases/download/v{version}/{pkg}.zip</download_url>
    <uploaded_by><![CDATA[{user}]]></uploaded_by>
    <create_date>{today}</create_date>
    <update_date>{today}</update_date>
    <experimental>False</experimental>
    <deprecated>False</deprecated>
    <tracker><![CDATA[https://github.com/{user}/{repo}/issues]]></tracker>
    <repository><![CDATA[https://github.com/{user}/{repo}]]></repository>
    <tags><![CDATA[{tags}]]></tags>
    <downloads>0</downloads>
    <average_vote>0</average_vote>
    <rating_votes>0</rating_votes>
  </pyqgis_plugin>
</plugins>
'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--github-user', default='saadakhs10')
    ap.add_argument('--version', default=None, help='override the version in metadata.txt')
    args = ap.parse_args()

    meta = configparser.ConfigParser(interpolation=None)
    meta.read(os.path.join(ROOT, PKG, 'metadata.txt'), encoding='utf-8')
    g = meta['general']
    if args.version:
        g['version'] = args.version

    os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
    out = os.path.join(ROOT, 'dist', PKG + '.zip')
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for base, dirs, files in os.walk(os.path.join(ROOT, PKG)):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for fn in files:
                if fn.endswith(('.pyc', '.pyo')):
                    continue
                full = os.path.join(base, fn)
                arc = os.path.relpath(full, ROOT)
                if fn == 'metadata.txt' and args.version:
                    with open(full, encoding='utf-8') as f:
                        text = f.read()
                    z.writestr(arc, re.sub(r'^version=.*$', 'version=' + args.version, text, flags=re.M))
                else:
                    z.write(full, arc)
    print('wrote', out)

    xml = XML.format(name=g['name'], version=g['version'], pkg=PKG, repo=REPO,
                     description=g['description'], about=g['about'],
                     qmin=g['qgisMinimumVersion'] + '.0', qmax=g['qgisMaximumVersion'] + '.0',
                     author=g['author'], user=args.github_user, tags=g.get('tags', ''),
                     today=datetime.date.today().isoformat())
    with open(os.path.join(ROOT, 'plugins.xml'), 'w', encoding='utf-8') as f:
        f.write(xml)
    print('wrote plugins.xml for github user', args.github_user)


if __name__ == '__main__':
    main()
