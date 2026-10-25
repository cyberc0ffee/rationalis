# Third-party components

Rationalis source code is released under the MIT license (see `LICENSE`). The prebuilt packages
(Windows zip, macOS `.dmg`/`.zip`) also bundle the following components, each under its own license.

| Component | Used for | License | Source |
|---|---|---|---|
| Python | interpreter bundled in the packages | PSF License | https://www.python.org |
| Qt for Python (PySide6, shiboken6) and Qt 6 | user interface, charts, printing | LGPL-3.0 (or GPL-2.0/3.0) | https://code.qt.io/cgit/pyside/pyside-setup.git |
| openpyxl | reading and writing Excel files | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| et-xmlfile | openpyxl dependency | MIT | https://foss.heptapod.net/openpyxl/et_xmlfile |
| access-parser | reading Access/Jet databases (DPM import) | Apache-2.0 | https://github.com/ClarotyICS/access_parser |
| construct, tabulate | access-parser dependencies | MIT | https://github.com/construct/construct, https://github.com/astanin/python-tabulate |
| cryptography | encryption of protected archives | Apache-2.0 or BSD-3-Clause | https://github.com/pyca/cryptography |
| cffi, pycparser | cryptography dependencies | MIT, BSD-3-Clause | https://github.com/python-cffi/cffi, https://github.com/eliben/pycparser |
| OpenSSL | bundled with cryptography | Apache-2.0 | https://www.openssl.org |
| PyInstaller (bootloader) | package launcher | GPL-2.0 with bootloader exception | https://pyinstaller.org |

## Qt and the LGPL-3.0
Rationalis uses Qt through PySide6 as unmodified dynamic libraries. In the packages the Qt libraries are
separate files (the `_internal` folder on Windows, `Rationalis.app/Contents/Frameworks` on macOS) and can be
replaced with compatible versions, as the LGPL requires. Qt and PySide6 source code is available at the
addresses above; Rationalis source code is in this repository.
License text: https://www.gnu.org/licenses/lgpl-3.0.html
