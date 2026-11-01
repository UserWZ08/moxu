NeighbourPrint includes unmodified Python 3.13.9, PySide6 / Shiboken / Qt 6.8.3, Qt's bundled dependencies, and the PyInstaller bootloader.

Python: Python Software Foundation license; see licenses/Python-LICENSE.txt.

Qt / PySide6 / Shiboken: used under LGPL v3 (with applicable Qt exceptions and third-party terms). See licenses/LGPL-3.0.txt and licenses/GPL-3.0.txt. These components remain dynamically linked in _internal. Users may replace compatible library binaries and debug modifications to these libraries. No application restriction is intended to prevent those rights.

Corresponding upstream source and dependency notices:
- https://download.qt.io/archive/qt/6.8/6.8.3/submodules/
- https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/
- https://code.qt.io/cgit/qt/qtwebengine.git/tree/src/3rdparty/chromium/LICENSE?h=v6.8.3
- https://github.com/pyinstaller/pyinstaller (GPL with bootloader exception)

The complete application source is delivered alongside the binaries. Build instructions are in 使用说明.md and build.ps1. Redistribution must preserve upstream license terms and corresponding source availability.

Version 0.4 additions:
- pypinyin 0.55.0: MIT, copyright mozillazg and contributors. Original license: licenses/pypinyin-MIT.txt. https://github.com/mozillazg/python-pinyin
- openpyxl 3.1.5: MIT, original notice: licenses/openpyxl-MIT.txt. https://openpyxl.readthedocs.io/
- et_xmlfile 2.0.0: original MIT and Python notices: licenses/et_xmlfile-MIT.txt and licenses/et_xmlfile-Python.txt.
- The orange printer icon, millimetre layout module and UI controls are original application code. Solid-background replacement has been removed in version 0.5.
- HivisionIDPhotos (Apache-2.0) and rembg (MIT) were researched as possible future optional engines; no code or model weights from those projects are included in this release.
