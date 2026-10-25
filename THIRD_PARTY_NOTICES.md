# Componenti di terze parti

Il codice di Rationalis è distribuito con licenza MIT (vedi `LICENSE`). I pacchetti pronti
(zip per Windows, `.dmg`/`.zip` per macOS) includono anche i componenti seguenti, ciascuno con la propria licenza.

| Componente | Uso | Licenza | Sorgente |
|---|---|---|---|
| Python | interprete incluso nei pacchetti | PSF License | https://www.python.org |
| Qt for Python (PySide6, shiboken6) e Qt 6 | interfaccia grafica, grafici, stampa | LGPL-3.0 (oppure GPL-2.0/3.0) | https://code.qt.io/cgit/pyside/pyside-setup.git |
| openpyxl | lettura e scrittura di file Excel | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| et-xmlfile | dipendenza di openpyxl | MIT | https://foss.heptapod.net/openpyxl/et_xmlfile |
| access-parser | lettura dei database Access/Jet (import DPM) | Apache-2.0 | https://github.com/ClarotyICS/access_parser |
| construct, tabulate | dipendenze di access-parser | MIT | https://github.com/construct/construct, https://github.com/astanin/python-tabulate |
| cryptography | cifratura degli archivi protetti | Apache-2.0 o BSD-3-Clause | https://github.com/pyca/cryptography |
| cffi, pycparser | dipendenze di cryptography | MIT, BSD-3-Clause | https://github.com/python-cffi/cffi, https://github.com/eliben/pycparser |
| OpenSSL | incluso in cryptography | Apache-2.0 | https://www.openssl.org |
| PyInstaller (bootloader) | avvio dei pacchetti | GPL-2.0 con eccezione per il bootloader | https://pyinstaller.org |

## Qt e la LGPL-3.0
Rationalis usa Qt tramite PySide6 come librerie dinamiche, non modificate. Nei pacchetti le librerie Qt
sono file separati (cartella `_internal` su Windows, `Rationalis.app/Contents/Frameworks` su macOS) e
possono essere sostituite con versioni compatibili, come richiesto dalla LGPL. Il sorgente di Qt e di
PySide6 è disponibile agli indirizzi indicati sopra; il sorgente di Rationalis è in questo repository.
Testo della licenza: https://www.gnu.org/licenses/lgpl-3.0.html
