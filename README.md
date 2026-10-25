# Rationalis

Personal, household and small-business finance manager for **Windows** (macOS from source).
Track accounts (cash, bank accounts, credit cards), income and expenses, transfers between accounts
even across currencies, recurring payments, balances and forecasts, summaries, charts, budgets, an
address book, a diary and printouts. Your data stays on your computer, in a single file that can be
protected with a password (AES-256 encryption).

> **Language:** the user interface is in **Italian**. *Leggi in italiano: [README.it.md](README.it.md).*

License: [MIT](LICENSE).

## Download (Windows)
Get `Rationalis-<version>-portabile-win64.zip` from the **Releases** page (Windows 10/11, 64-bit),
extract it and run `Rationalis.exe`. Nothing to install: Python and all libraries are bundled.
The executable is not code-signed, so on first launch SmartScreen asks you to confirm
(“More info” › “Run anyway”).

On **macOS** there is no prebuilt package: run it from source (see below) or build the app as
described in [Packaging](#packaging).

## Running from source
Requires Python 3.11 or later.
```
pip install -r requirements.txt
python -m rationalis [archive.rtl]
```
On Windows you can also double-click `Avvia Rationalis.bat`; on macOS `Avvia Rationalis.command`
(on first run it creates a `.venv` and installs the dependencies).

Archives (`.rtl`, SQLite databases) are stored by default in `Documents/Rationalis/archivi`, backups
(`.rtz`, zip) in `Documents/Rationalis/copie`. The same archive opens on Windows and macOS.

## Features
| Area | What it does |
|---|---|
| Archives | create (with starter categories and accounts), open, recent files, backup and restore, automatic backup on close; archives from older versions are upgraded on open |
| Password | optional protection: the file is encrypted (AES-256-GCM, scrypt key derivation) and the plaintext database only exists in memory; backups stay encrypted too |
| Start page | customizable welcome, account balances, today's reminders (diary notes, overdue items), upcoming due items |
| Lists | income/expense categories and subcategories, accounts and payment methods, currencies with a base currency, purposes, people, frequent descriptions, category groupings |
| Transactions | monthly grid per account or for all accounts; auto-completion; calculator in amount cells (F2); configurable columns; sorting; cut/copy/paste into another month; duplicate last (F9); toggle cleared (F3); find (Ctrl+F); new row (F12); zoom (F5…F8) |
| Operations | transfers (one source, up to three destinations, balance check), credit-card statement settlement, bulk replace/delete |
| Scheduler | recurring transactions or transfers every n days/weeks/months, on a day of the month, the last day, “first Monday”, etc.; editing a schedule only touches items not yet cleared |
| Analysis | monthly totals; current, daily, trend and projected balances; filtered lists with saved searches; summaries over 3 periods or 12 months; charts; statistics monitor; budgets, yearly budget sheet and variance |
| Tools | calculator (percentages, VAT, exchange rates, paper tape), currency converter, investment returns, address book, diary with reminders, monthly notes, free-form tally cards |
| Printing | lists and reports with preview, printer or PDF; orientation, margins, grid lines, fit to page; headers and footers with `&L &C &R &D &T &P &N &B &I &U` codes |
| Import/export | Excel import; transaction export to Excel/text/HTML (re-importable); every report to Excel; import of Danea Professional Manager 5 archives (see below) |

Analysis rules: transfers are neither income nor expense; unless a filter says otherwise only cleared
transactions count; amounts from different accounts are summed in the base currency at the current rate.
Budget variance is actual − budget with sign, so a positive value means less spending or more income than planned.

Not implemented: step-by-step guided entry for beginners, printing charts (export the table instead),
online help, modem dialing (the ☎ button hands the number to the system phone app).

A note on passwords: protecting an existing archive replaces the plaintext file, but its old contents may
still be recoverable from the disk with forensic tools; for sensitive data, create the archive and protect it right away.

## Importing Danea Professional Manager 5 archives
Rationalis can import `.dpm` archives (and `.dpz` backups in zip format) created with Danea Professional
Manager 5, so users can keep their data when switching programs. The importer reads the Microsoft
Access/Jet database inside the file; the table layout was reconstructed solely for interoperability and
**has not yet been verified against a real archive**. Anything not recognized is listed in the import
report instead of being silently dropped. Bug reports and sample archives (without personal data) are welcome.

## Development
```
pip install -r requirements.txt pytest
python -m pytest
```
`tests/fixtures/sintetico.dpm` is a purpose-built Jet 3 database (`tests/fixtures/make_dpm_fixture.ps1`,
32-bit PowerShell) used to test format reading; it contains no real data.

Source code identifiers and comments are in Italian.

### Packaging
`python tools_build/build_portable.py` (after `pip install pyinstaller pillow`) builds the package for the
current OS, smoke-tests it by launching it with `--prova-avvio`, and produces a zip (Windows) or a `.dmg`
and `.zip` (macOS). PyInstaller does not cross-compile: macOS builds must be made on a Mac or with the
[`.github/workflows/build.yml`](.github/workflows/build.yml) GitHub Actions workflow, which builds and tests
Windows, macOS Apple Silicon and macOS Intel. On Intel Macs install dependencies with `--only-binary=cryptography`.

Portable mode: with a `PORTABILE.txt` file next to the executable (or next to `Rationalis.app`), settings
and archives are kept in a `Dati` folder next to the program.

## License and trademarks
Rationalis is released under the [MIT](LICENSE) license. Libraries bundled in the packages have their own
licenses, listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (notably Qt/PySide6, LGPL-3.0).

Rationalis is an independent project written from scratch: it contains no code, text or graphics from other
programs and is **not affiliated with, endorsed or sponsored by Danea Soft S.r.l. or TeamSystem**.
“Danea”, “Danea Professional Manager” and “Easyfatt” are trademarks of their respective owners and are
mentioned only to describe file compatibility.
