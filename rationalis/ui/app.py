"""Avvio dell'applicazione: `python -m rationalis [archivio.rtl]`.

`--prova-avvio <cartella>`: verifica di funzionamento (usata dopo la creazione della versione portabile).
Senza finestre, con impostazioni temporanee nella cartella indicata: crea un archivio di prova, apre le
finestre principali, stampa un PDF, scrive l'esito in <cartella>/esito.txt ed esce.
"""
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTimer, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import APP_NAME, __version__


def _self_test(win, folder: Path) -> str:
    from datetime import date
    from decimal import Decimal

    from .. import movements as mv
    from ..db import Archive
    from . import analysis_windows as aw
    from . import tools_windows as tw
    from .dialogs import current_balances_report
    from .printing import Job, PrintOptions, save_pdf, table_html
    arc = Archive.create(folder / "prova.rtl")
    banca = arc.find_by_name("risorse", "Banca c/c")["id"]
    mv.save(arc, mv.Movement(data=date.today(), risorsa_id=banca, gruppo_id=arc.find_by_name("gruppi", "Casa")["id"],
                             importo=Decimal("-800"), saldato=True, descrizione="Affitto"))
    win.set_archive(arc)
    for dlg in (aw.SummaryDialog(arc, win), aw.ChartsDialog(arc, date.today().year, win), aw.BudgetDialog(arc, win),
                tw.AddressBookDialog(arc, win), tw.FreeCardsDialog(arc, win), current_balances_report(arc, win)):
        dlg.close()
    win.show_movements()
    headers, rows, right = win._visible_grid()
    pages = save_pdf(Job("Prova", table_html(headers, rows, right), PrintOptions()), str(folder / "prova.pdf"))
    arc.set_password("prova-1234")
    win.close_archive()
    Archive.open(folder / "prova.rtl", "prova-1234").close()
    return f"ok {__version__}: {len(rows)} movimenti, PDF di {pages} pagine, cifratura verificata"


PORTABLE_MARKER = "PORTABILE.txt"


def portable_dir() -> Path | None:
    """Cartella del programma se accanto all'eseguibile c'è PORTABILE.txt (solo versione impacchettata).
    Su macOS la cartella è quella che contiene Rationalis.app: scrivere dentro il pacchetto lo danneggerebbe."""
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    if sys.platform == "darwin" and exe_dir.parent.name == "Contents" and exe_dir.parent.parent.suffix == ".app":
        exe_dir = exe_dir.parent.parent.parent
    return exe_dir if (exe_dir / PORTABLE_MARKER).exists() else None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    test_dir = None
    portable = portable_dir()
    if portable is not None:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        data = portable / ("Rationalis Dati" if sys.platform == "darwin" else "Dati")
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(data / "impostazioni"))
        from . import main_window
        main_window.DATA_DIR = data
    if "--prova-avvio" in argv:
        i = argv.index("--prova-avvio")
        test_dir = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(test_dir / "impostazioni"))
    QLocale.setDefault(QLocale(QLocale.Language.Italian, QLocale.Country.Italy))
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    icon = Path(__file__).resolve().parent.parent / "resources" / "rationalis.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    from .common import fix_palette
    from .main_window import MainWindow
    fix_palette(app)
    translator = QTranslator(app)
    if translator.load(QLocale(), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    win = MainWindow()
    if test_dir is not None:
        def run():
            try:
                result = _self_test(win, test_dir)
            except Exception as e:  # l'esito, qualunque sia, va scritto nel file
                import traceback
                result = "ERRORE " + "".join(traceback.format_exception(e))
            (test_dir / "esito.txt").write_text(result, encoding="utf-8")
            app.quit()
        QTimer.singleShot(0, run)
        return app.exec()
    target = Path(argv[1]) if len(argv) > 1 else None
    last = win.settings.value("ultimo")
    if target is not None:
        win.open_archive(target)
    elif last and Path(last).exists():
        win.open_archive(Path(last))
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
