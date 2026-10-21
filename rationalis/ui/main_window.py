"""Finestra principale: periodo e risorsa, griglia dei movimenti, barra delle disponibilità, menu."""
from dataclasses import replace
from datetime import date
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPushButton, QSpinBox, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

from .. import APP_NAME, __version__
from .. import balances as bal
from .. import movements as mv
from ..backup import BACKUP_EXTENSION, make_backup, restore_backup
from .. import tools
from ..db import EXTENSION, Archive, ArchiveError, PasswordRequired
from ..interop.dpm import import_dpm
from ..interop.tabular import export_csv, export_html, export_xlsx, import_xlsx
from ..money import fmt_amount
from .common import MESI, DateEdit, ask, colors, error, guarded, is_dark
from .analysis_windows import (BudgetDialog, BulkChangeDialog, ChartsDialog, FilteredListDialog, GroupingsDialog,
                               MonitorDialog, MonthTotalsWindow, SummaryDialog, VarianceDialog, budget_sheet_report,
                               groups_outline_report)
from .calculator_dialog import CalculatorDialog
from .data_windows import DataWindow
from .printing import PrintOptions, PrintSetupDialog, blank_grid_html, print_table
from .start_page import StartPage
from .tools_windows import (AddressBookDialog, AgendaDialog, CurrencyConverterDialog, FreeCardsDialog,
                            InvestmentsDialog, MonthNotesDialog, PasswordDialog)
from .dialogs import (CardChargeDialog, ColumnsDialog, FindDialog, MoveDateDialog, ScheduleDialog, SettingsDialog,
                      TransferDialog, TransfersManager, current_balances_report, daily_report, trend_report,
                      unsettled_report)
from .movements_grid import OPTIONAL_COLUMNS, SORT_KEYS, COLUMN_INFO, MovementsModel, MovementsView

ALL_RESOURCES = "‹ Tutte le risorse ›"


DATA_DIR: Path | None = None   # impostata in modalità portabile (cartella Dati accanto al programma)


def documents_dir() -> Path:
    d = DATA_DIR or Path.home() / "Documents" / APP_NAME
    (d / "archivi").mkdir(parents=True, exist_ok=True)
    (d / "copie").mkdir(parents=True, exist_ok=True)
    return d


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings()
        self.arc: Archive | None = None
        self.model: MovementsModel | None = None
        self.view: MovementsView | None = None
        self.clip: list[mv.Movement] = []
        self.limit_states: dict[int, str] = {}
        self.find_dialog: FindDialog | None = None
        self.totals_window: MonthTotalsWindow | None = None
        self.resize(1250, 720)
        self._build_menus()
        self._show_empty()
        self.flush_timer = QTimer(self)
        self.flush_timer.timeout.connect(self._flush)
        self.flush_timer.start(2000)
        geo = self.settings.value("geometria")
        if geo is not None:
            self.restoreGeometry(geo)

    # --- costruzione -----------------------------------------------------------
    def _action(self, menu, text, fn, shortcut=None, needs_archive=True, role=None):
        """Voce di menu. shortcut: testo («Ctrl+P», su Mac diventa Cmd+P) o QKeySequence.StandardKey.
        role: su macOS sposta la voce nel menu dell'applicazione (Esci, Informazioni, Impostazioni)."""
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if role is not None:
            a.setMenuRole(role)
        a.triggered.connect(fn)
        menu.addAction(a)
        if needs_archive:
            self._archive_actions.append(a)
        return a

    def _build_menus(self):
        self._archive_actions: list[QAction] = []
        mb = self.menuBar()
        m = mb.addMenu("&File")
        self._action(m, "&Nuovo archivio…", self.new_archive, "Ctrl+N", False)
        self._action(m, "&Apri archivio…", self.open_archive_dialog, "Ctrl+O", False)
        self.recent_menu = m.addMenu("Archivi &recenti")
        self._action(m, "&Chiudi archivio", self.close_archive)
        m.addSeparator()
        imp = m.addMenu("&Importa")
        self._action(imp, "Archivio Danea Professional Manager (.dpm / .dpz)…", self.import_dpm, needs_archive=False)
        self._action(imp, "Movimenti da Excel…", self.import_excel)
        self._action(m, "&Esporta movimenti…", self.export_movements)
        m.addSeparator()
        self._action(m, "Stam&pa elenco movimenti…", self.print_movements, "Ctrl+P")
        self._action(m, "Stampa &griglia vuota…", self.print_blank_grid)
        m.addSeparator()
        self._action(m, "Copia di &sicurezza…", self.backup)
        self._action(m, "Codice d'&accesso…", self.access_code)
        self._action(m, "R&ipristina copia di sicurezza…", self.restore, needs_archive=False)
        m.addSeparator()
        self._action(m, "&Esci", self.close, QKeySequence.StandardKey.Quit, False, QAction.MenuRole.QuitRole)

        m = mb.addMenu("&Modifica")
        self._action(m, "&Taglia", self.cut, "Ctrl+X")
        self._action(m, "&Copia", self.copy, "Ctrl+C")
        self._action(m, "&Incolla e accoda", self.paste, "Ctrl+V")
        self._action(m, "&Duplica l'ultimo movimento", self.duplicate_last, "F9")
        self._action(m, "&Elimina", self.delete_selected, "Shift+Del")
        m.addSeparator()
        self._action(m, "Inverti &stato di saldo", self.toggle_settled, "F3")
        self._action(m, "Sposta in altra &data…", self.move_to_date)
        self._action(m, "&Trova…", self.find, "Ctrl+F")
        self._action(m, "&Riordina", lambda: self.model.resort(), "Ctrl+R")
        self._action(m, "Vai al &nuovo movimento", lambda: self.view.go_to_new_row(), "F12")
        m.addSeparator()
        self._action(m, "Configurazione &colonne…", self.configure_columns)

        m = mb.addMenu("&Tabelle")
        for text, table in (("&Gruppi e sottogruppi…", "gruppi"), ("&Risorse e modalità di pagamento…", "risorse"),
                            ("&Valute…", "valute"), ("&Destinazioni…", "destinazioni"), ("&Soggetti…", "soggetti"),
                            ("D&escrizioni frequenti…", "descrizioni")):
            self._action(m, text, lambda _=False, t=table: self.edit_table(t))
        m.addSeparator()
        self._action(m, "Ra&ggruppamenti…", lambda: self._modal(GroupingsDialog(self.arc, self)))

        m = mb.addMenu("&Operazioni")
        self._action(m, "&Nuovo giroconto…", self.new_transfer, "Ctrl+G")
        self._action(m, "&Gestione giroconti del mese…", self.manage_transfers)
        self._action(m, "&Addebito spese carta di credito…", self.charge_card)
        m.addSeparator()
        self._action(m, "&Variazioni automatiche…", self.bulk_change)
        self._action(m, "Cancella &tutti i movimenti…", self.delete_all)

        m = mb.addMenu("&Strumenti")
        self._action(m, "&Scadenzario…", self.schedules, "Ctrl+K")
        self._action(m, "Scadenze del &mese…", lambda: unsettled_report(self.arc, self.model.year, self.model.month,
                                                                         self.model.risorsa_id, self).exec())
        m.addSeparator()
        self._action(m, "&Calcolatrice…", lambda: CalculatorDialog(self).show(), "Ctrl+Shift+C", False)
        self._action(m, "Con&versione valute…", lambda: CurrencyConverterDialog(self.arc, self).exec())
        self._action(m, "Calcoli &rendimenti finanziari…", lambda: InvestmentsDialog(self.arc, self).exec())
        m.addSeparator()
        self._action(m, "R&ubrica…", lambda: AddressBookDialog(self.arc, self).exec())
        self._action(m, "&Agenda…", self.agenda)
        self._action(m, "Annotazioni del m&ese…", lambda: MonthNotesDialog(self.arc, self.model.year, self.model.month,
                                                                           self).exec())
        self._action(m, "Schede &libere…", lambda: FreeCardsDialog(self.arc, self).exec())

        m = mb.addMenu("&Analisi")
        self._action(m, "&Totali del mese…", self.month_totals, "Ctrl+T")
        self._action(m, "Disponibilità &correnti…", lambda: current_balances_report(self.arc, self).exec())
        self._action(m, "Disponibilità &giornaliere…", self.daily)
        self._action(m, "&Andamento disponibilità (12 mesi)…", lambda: self.trend(False))
        self._action(m, "&Proiezione disponibilità (12 mesi)…", lambda: self.trend(True))
        m.addSeparator()
        self._action(m, "&Elenco movimenti filtrati…", lambda: self._modal(FilteredListDialog(self.arc, self)),
                     "Ctrl+L")
        self._action(m, "&Riepiloghi…", lambda: self._modal(SummaryDialog(self.arc, self)), "Ctrl+E")
        self._action(m, "&Grafici…", lambda: self._modal(ChartsDialog(self.arc, self.model.year, self)))
        self._action(m, "&Monitor statistiche…", lambda: self._modal(MonitorDialog(self.arc, self.model.year, self)))
        m.addSeparator()
        self._action(m, "Impostazione &budget…", lambda: self._modal(BudgetDialog(self.arc, self)))
        self._action(m, "Prospetto budget &annuale…", lambda: budget_sheet_report(self.arc, self).exec())
        self._action(m, "Analisi &scostamenti budget…",
                     lambda: self._modal(VarianceDialog(self.arc, self.model.year, self)))

        m = mb.addMenu("&Varie")
        self._action(m, "&Pagina d'avvio", self.show_start_page, "Ctrl+Home")
        self._action(m, "&Elenco dei movimenti", self.show_movements, "Ctrl+End")
        m.addSeparator()
        self._action(m, "&Impostazioni dell'archivio…", self.archive_settings, QKeySequence.StandardKey.Preferences,
                     role=QAction.MenuRole.PreferencesRole)
        self._action(m, "&Elenco gruppi e sottogruppi…", lambda: groups_outline_report(self.arc, self).exec())

        m = mb.addMenu("&?")
        self._action(m, "&Informazioni", self.about, needs_archive=False, role=QAction.MenuRole.AboutRole)
        self._refresh_recent()

    def _show_empty(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch()
        title = QLabel(f"<h1>{APP_NAME}</h1><p>Gestione e analisi finanziaria</p>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        row = QHBoxLayout()
        row.addStretch()
        for text, fn in (("Nuovo archivio", self.new_archive), ("Apri archivio", self.open_archive_dialog),
                         ("Importa da Danea Professional Manager", self.import_dpm)):
            b = QPushButton(text)
            b.setMinimumHeight(36)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        lay.addStretch()
        self.setCentralWidget(w)
        self.setWindowTitle(APP_NAME)
        for a in self._archive_actions:
            a.setEnabled(False)

    def _show_archive(self):
        self.model = MovementsModel(self.arc, self)
        vis = self.settings.value("colonne", OPTIONAL_COLUMNS)
        self.model.set_columns(list(vis) if vis else [])
        self.view = MovementsView(self.model)
        self.model.changed.connect(self._after_change)

        top = QHBoxLayout()
        prev = QToolButton()
        prev.setText("◀")
        prev.setToolTip("Mese precedente (Ctrl+PgSu)")
        prev.clicked.connect(lambda: self.shift_month(-1))
        nxt = QToolButton()
        nxt.setText("▶")
        nxt.setToolTip("Mese successivo (Ctrl+PgGiù)")
        nxt.clicked.connect(lambda: self.shift_month(1))
        self.month_cb = QComboBox()
        for i, mname in enumerate(MESI, 1):
            self.month_cb.addItem(mname.capitalize(), i)
        self.year_sb = QSpinBox()
        self.year_sb.setRange(1900, 2200)
        self.res_cb = QComboBox()
        self.res_cb.setMinimumWidth(200)
        self.sort_cb = QComboBox()
        for key in SORT_KEYS:
            self.sort_cb.addItem(COLUMN_INFO[key][0], key)
        top.addWidget(QLabel("Periodo"))
        top.addWidget(prev)
        top.addWidget(self.month_cb)
        top.addWidget(self.year_sb)
        top.addWidget(nxt)
        top.addSpacing(20)
        res_lbl = QPushButton("Risorsa")
        res_lbl.setFlat(True)
        res_lbl.setToolTip("Mostra le disponibilità correnti di tutte le risorse")
        res_lbl.clicked.connect(lambda: current_balances_report(self.arc, self).exec())
        top.addWidget(res_lbl)
        top.addWidget(self.res_cb)
        top.addSpacing(20)
        top.addWidget(QLabel("Ordina per"))
        top.addWidget(self.sort_cb)
        top.addStretch()

        bottom = QHBoxLayout()
        self.cur_lbl = QLabel()
        self.prev_lbl, self.end_lbl, self.today_lbl, self.proj_lbl = QLabel(), QLabel(), QLabel(), QLabel()
        disp = QPushButton("Disponibilità")
        disp.setFlat(True)
        disp.setToolTip("Andamento giorno per giorno del mese")
        disp.clicked.connect(self.daily)
        bottom.addWidget(disp)
        bottom.addWidget(self.cur_lbl)
        for lbl in (self.prev_lbl, self.end_lbl, self.proj_lbl):
            bottom.addSpacing(16)
            bottom.addWidget(lbl)
        bottom.addStretch()
        bottom.addWidget(self.today_lbl)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(top)
        lay.addWidget(self.view)
        lay.addLayout(bottom)
        self.start_page = StartPage(self.arc)
        self.start_page.action.connect(self._start_action)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.start_page)
        self.stack.addWidget(w)
        self.setCentralWidget(self.stack)
        for a in self._archive_actions:
            a.setEnabled(True)
        self.setWindowTitle(f"{APP_NAME} – {self.arc.path.stem if self.arc.path else ''}")
        self.statusBar().showMessage(str(self.arc.path or ""))

        self._fill_resources()
        start = date.today()
        if self.arc.setting("mese_apertura") == "ultimo_saldato":
            start = bal.last_settled_date(self.arc) or start
        self._set_period(start.year, start.month)
        self.month_cb.currentIndexChanged.connect(self._period_changed)
        self.year_sb.valueChanged.connect(self._period_changed)
        self.res_cb.currentIndexChanged.connect(self._period_changed)
        self.sort_cb.currentIndexChanged.connect(lambda: self.model.resort(self.sort_cb.currentData()))
        self.limit_states = {r["id"]: bal.limit_state(self.arc, r["id"]) for r in self.arc.rows("risorse", order="id")}
        if self.arc.setting("avvio_mostra", "pagina") == "movimenti":
            self.show_movements()
        else:
            self.show_start_page()

    def _fill_resources(self):
        cur = self.res_cb.currentData() if self.res_cb.count() else None
        self.res_cb.blockSignals(True)
        self.res_cb.clear()
        self.res_cb.addItem(ALL_RESOURCES, None)
        for r in self.arc.rows("risorse", "in_uso = 1"):
            self.res_cb.addItem(r["nome"], r["id"])
        i = self.res_cb.findData(cur)
        self.res_cb.setCurrentIndex(i if i >= 0 else 0)
        self.res_cb.blockSignals(False)

    # --- periodo -----------------------------------------------------------------
    def _set_period(self, year: int, month: int):
        for w in (self.month_cb, self.year_sb):
            w.blockSignals(True)
        self.month_cb.setCurrentIndex(month - 1)
        self.year_sb.setValue(year)
        for w in (self.month_cb, self.year_sb):
            w.blockSignals(False)
        self._period_changed()

    def _period_changed(self, *_):
        self.model.load(self.year_sb.value(), self.month_cb.currentData(), self.res_cb.currentData())
        self._update_bar()
        if self.totals_window is not None:
            self.totals_window.refresh()

    def shift_month(self, d: int):
        y, m = self.year_sb.value(), self.month_cb.currentData() + d
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        self._set_period(y, m)

    def keyPressEvent(self, ev):
        if self.arc and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if ev.key() == Qt.Key.Key_PageUp:
                self.shift_month(-1)
                return
            if ev.key() == Qt.Key.Key_PageDown:
                self.shift_month(1)
                return
        super().keyPressEvent(ev)

    def _update_bar(self):
        if not self.arc:
            return
        rid = self.model.risorsa_id
        cur = self.arc.resource_currency(rid) if rid else self.arc.principal()
        b = bal.availability_bar(self.arc, self.model.year, self.model.month, rid)
        dec = self.arc.decimals

        c = colors(is_dark(self))

        def fmt(v):
            color = c["out"] if v < 0 else c["in"]
            return f"<b style='color:{color}'>{fmt_amount(v, dec)}</b>"

        pm = self.model.month - 1 or 12
        self.cur_lbl.setText(f"<b>{cur['sigla']}</b>")
        self.prev_lbl.setText(f"Fine {MESI[pm - 1]}: {fmt(b['fine_mese_precedente'])}")
        self.end_lbl.setText(f"Fine {MESI[self.model.month - 1]}: {fmt(b['fine_mese'])}")
        self.proj_lbl.setText(f"Con non saldati: {fmt(b['proiezione_fine_mese'])}")
        self.today_lbl.setText(f"Oggi {date.today():%d/%m/%Y}: {fmt(b['oggi'])}")

    def _after_change(self):
        self._update_bar()
        if self.totals_window is not None:
            self.totals_window.refresh()
        for r in self.arc.rows("risorse", order="id"):
            new = bal.limit_state(self.arc, r["id"])
            old = self.limit_states.get(r["id"], "ok")
            if new != "ok" and old == "ok":
                where = "sotto il limite minimo" if new == "sotto" else "sopra il limite massimo"
                QMessageBox.information(self, APP_NAME, f"Attenzione: la disponibilità di «{r['nome']}» è {where}.")
            self.limit_states[r["id"]] = new

    def reload(self, select_id: int | None = None):
        self._fill_resources()
        self._period_changed()
        self._after_change()
        if select_id:
            self.view.select_movement(select_id)

    # --- archivi -----------------------------------------------------------------
    def _remember(self, path: Path):
        recent = [p for p in (self.settings.value("recenti") or []) if p != str(path)]
        recent.insert(0, str(path))
        self.settings.setValue("recenti", recent[:8])
        self.settings.setValue("ultimo", str(path))
        self._refresh_recent()

    def _refresh_recent(self):
        self.recent_menu.clear()
        for p in self.settings.value("recenti") or []:
            a = self.recent_menu.addAction(p)
            a.triggered.connect(lambda _=False, path=p: self.open_archive(Path(path)))
        self.recent_menu.setEnabled(bool(self.settings.value("recenti")))

    def set_archive(self, arc: Archive):
        self.close_archive()
        self.arc = arc
        if arc.path:
            self._remember(arc.path)
        self._show_archive()

    def open_archive(self, path: Path) -> bool:
        password = None
        for attempt in range(3):
            try:
                arc = Archive.open(path, password)
            except PasswordRequired:
                pass
            except ArchiveError as e:
                if password is None:
                    error(self, e)
                    return False
                error(self, e)
            else:
                self.set_archive(arc)
                return True
            password, ok = QInputDialog.getText(self, APP_NAME, f"Codice d'accesso per «{path.stem}»:",
                                                QLineEdit.EchoMode.Password)
            if not ok:
                return False
        return False

    def open_archive_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Apri archivio", str(documents_dir() / "archivi"),
                                              f"Archivi {APP_NAME} (*{EXTENSION})")
        if path:
            self.open_archive(Path(path))

    def new_archive(self):
        path, _ = QFileDialog.getSaveFileName(self, "Nuovo archivio", str(documents_dir() / "archivi" / "Famiglia"),
                                              f"Archivi {APP_NAME} (*{EXTENSION})")
        if not path:
            return
        path = Path(path).with_suffix(EXTENSION)
        ok, arc = guarded(self, Archive.create, path)
        if ok:
            self.set_archive(arc)
            QMessageBox.information(self, APP_NAME,
                                    "Archivio creato con alcuni gruppi e due risorse (Cassa, Banca c/c) di esempio.\n"
                                    "Controllare le tabelle e impostare i saldi iniziali delle risorse.")
            self.edit_table("risorse")

    def close_archive(self):
        if self.arc is None:
            return
        if self.arc.setting("copia_alla_chiusura") == "1" and self.arc.path:
            guarded(self, make_backup, self.arc, documents_dir() / "copie")
        if self.totals_window is not None:
            self.totals_window.close()
            self.totals_window = None
        self.arc.close()
        self.arc = None
        self.model = self.view = None
        self._show_empty()

    def _flush(self):
        if self.arc is not None and self.arc.encrypted:
            guarded(self, self.arc.flush)

    def closeEvent(self, ev):
        self.settings.setValue("geometria", self.saveGeometry())
        self.close_archive()
        super().closeEvent(ev)

    def import_dpm(self):
        src, _ = QFileDialog.getOpenFileName(self, "Importa archivio Danea Professional Manager", str(Path.home()),
                                             "Archivi DPM (*.dpm *.dpz);;Tutti i file (*)")
        if not src:
            return
        dest, _ = QFileDialog.getSaveFileName(self, "Nome del nuovo archivio",
                                              str(documents_dir() / "archivi" / Path(src).stem),
                                              f"Archivi {APP_NAME} (*{EXTENSION})")
        if not dest:
            return
        dest = Path(dest).with_suffix(EXTENSION)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            arc, report = import_dpm(src, dest)
        except Exception as e:  # il file può essere danneggiato in molti modi diversi
            QApplication.restoreOverrideCursor()
            error(self, f"Importazione non riuscita: {e}")
            return
        QApplication.restoreOverrideCursor()
        self.set_archive(arc)
        self._show_report("Importazione completata", report)

    def _show_report(self, title: str, report):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(title + ".")
        box.setInformativeText("\n".join(f"{k}: {v}" for k, v in report.counts.items()) or "Nessun dato importato")
        if report.warnings:
            box.setDetailedText("\n".join(f"- {w}" for w in report.warnings))
        box.exec()

    def import_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importa movimenti da Excel", str(Path.home()),
                                              "Fogli Excel (*.xlsx *.xlsm)")
        if not path:
            return
        if not ask(self, "I movimenti del foglio verranno aggiunti a quelli già presenti (senza controllare i "
                         "doppioni). Continuare?"):
            return
        ok, report = guarded(self, import_xlsx, self.arc, path)
        if ok:
            self.reload()
            self._show_report("Importazione da Excel completata", report)

    def export_movements(self):
        start = DateEdit(date(self.model.year, 1, 1))
        end = DateEdit(date(self.model.year, 12, 31))
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("Esporta movimenti")
        form = QFormLayout(dlg)
        form.addRow("Dal", start)
        form.addRow("Al", end)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if not dlg.exec():
            return
        path, flt = QFileDialog.getSaveFileName(
            self, "Esporta movimenti", str(documents_dir() / f"movimenti_{start.value():%Y%m%d}_{end.value():%Y%m%d}"),
            "Excel (*.xlsx);;Testo delimitato da tabulazioni (*.txt);;Pagina HTML (*.html)")
        if not path:
            return
        p = Path(path)
        fn = export_html if p.suffix.lower() in (".html", ".htm") else export_csv if p.suffix.lower() in (
            ".txt", ".tsv", ".csv") else export_xlsx
        if fn is export_xlsx and p.suffix.lower() != ".xlsx":
            p = p.with_suffix(".xlsx")
        ok, _ = guarded(self, fn, self.arc, p, start.value(), end.value())
        if ok:
            self.statusBar().showMessage(f"Esportato in {p}", 8000)

    def backup(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Copia di sicurezza",
            str(documents_dir() / "copie" / f"{self.arc.path.stem}_{date.today():%Y%m%d}{BACKUP_EXTENSION}"),
            f"Copie di sicurezza (*{BACKUP_EXTENSION})")
        if path:
            ok, p = guarded(self, make_backup, self.arc, Path(path).with_suffix(BACKUP_EXTENSION))
            if ok:
                QMessageBox.information(self, APP_NAME, f"Copia di sicurezza salvata in:\n{p}")

    def restore(self):
        src, _ = QFileDialog.getOpenFileName(self, "Ripristina copia di sicurezza", str(documents_dir() / "copie"),
                                             f"Copie di sicurezza (*{BACKUP_EXTENSION})")
        if not src:
            return
        dest = QFileDialog.getExistingDirectory(self, "Cartella in cui ripristinare l'archivio",
                                                str(documents_dir() / "archivi"))
        if not dest:
            return
        ok, path = guarded(self, restore_backup, src, dest)
        if ok:
            self.open_archive(path)

    # --- modifica ------------------------------------------------------------------
    def copy(self):
        movs = [m for m in self.view.selected_movements() if not m.is_transfer]
        if movs:
            self.clip = movs
            self.statusBar().showMessage(f"{len(movs)} movimenti copiati", 4000)

    def cut(self):
        movs = [m for m in self.view.selected_movements() if not m.is_transfer]
        if not movs:
            return
        self.clip = [replace(m, id=None) for m in movs]
        mv.delete(self.arc, [m.id for m in movs])
        self.reload()
        self.statusBar().showMessage(f"{len(movs)} movimenti tagliati", 4000)

    def paste(self):
        if not self.clip:
            return
        ok, ids = guarded(self, mv.paste_into_month, self.arc, self.clip, self.model.year, self.model.month)
        if ok:
            self.reload(ids[-1] if ids else None)

    def duplicate_last(self):
        ok, i = guarded(self, mv.duplicate_last, self.arc, self.model.year, self.model.month, self.model.risorsa_id)
        if ok and i:
            self.reload(i)

    def delete_selected(self):
        movs = self.view.selected_movements()
        if not movs or not ask(self, f"Eliminare {len(movs)} movimenti selezionati?"):
            return
        done, skipped = mv.delete(self.arc, [m.id for m in movs])
        self.reload()
        if skipped:
            QMessageBox.information(self, APP_NAME, f"{skipped} giroconti non sono stati eliminati: "
                                                    "usare Operazioni › Gestione giroconti.")

    def toggle_settled(self):
        movs = self.view.selected_movements()
        if movs:
            mv.toggle_settled(self.arc, [m.id for m in movs])
            rows = self.view.selected_rows()
            for r in rows:
                self.model.refresh_row(r)
            self._after_change()

    def move_to_date(self):
        movs = self.view.selected_movements()
        if len(movs) != 1 or movs[0].is_transfer:
            error(self, "Selezionare un solo movimento (non un giroconto)")
            return
        dlg = MoveDateDialog(movs[0].data, self)
        if dlg.exec():
            mv.move_to_date(self.arc, movs[0].id, dlg.date.value())
            self.reload()

    def find(self):
        if self.find_dialog is None:
            self.find_dialog = FindDialog(self)
            self.find_dialog.next_btn.clicked.connect(lambda: self._find_step(False))
            self.find_dialog.prev_btn.clicked.connect(lambda: self._find_step(True))
        self.find_dialog.show()
        self.find_dialog.raise_()

    def _find_step(self, backwards: bool):
        d = self.find_dialog
        cur = self.view.selected_movements()
        after = (cur[0].data, cur[0].id) if cur else (date(self.model.year, self.model.month, 1), 0)
        rid = None if d.all_res.isChecked() else self.model.risorsa_id
        ok, m = guarded(self, mv.find, self.arc, d.text.text(), d.mode.currentData(), rid, after, backwards)
        if not ok:
            return
        if m is None:
            d.status.setText("Nessun altro movimento trovato")
            return
        d.status.setText(f"Trovato: {m.data:%d/%m/%Y}")
        if (m.data.year, m.data.month) != (self.model.year, self.model.month) or \
                (rid is None and self.model.risorsa_id is not None):
            if rid is None and self.model.risorsa_id is not None:
                self.res_cb.setCurrentIndex(self.res_cb.findData(m.risorsa_id))
            self._set_period(m.data.year, m.data.month)
        self.view.select_movement(m.id)

    def configure_columns(self):
        dlg = ColumnsDialog([c for c in self.model.columns if c in OPTIONAL_COLUMNS], self)
        if dlg.exec():
            self.settings.setValue("colonne", dlg.visible())
            self.model.set_columns(dlg.visible())

    # --- tabelle e operazioni ---------------------------------------------------------
    def edit_table(self, table: str):
        DataWindow(self.arc, table, self).exec()
        self.reload()

    def new_transfer(self):
        d = date(self.model.year, self.model.month, min(date.today().day, self.model.days_in_month()))
        if TransferDialog(self.arc, default_date=d, parent=self).exec():
            self.reload()

    def manage_transfers(self):
        TransfersManager(self.arc, self.model.year, self.model.month, self).exec()
        self.reload()

    def charge_card(self):
        if not self.arc.rows("risorse", "tipo = 'carta'"):
            error(self, "Non ci sono risorse di tipo carta di credito")
            return
        if CardChargeDialog(self.arc, self).exec():
            self.reload()

    def delete_all(self):
        if not ask(self, "Cancellare TUTTI i movimenti, i giroconti e le scadenze dell'archivio? Le tabelle restano. "
                         "L'operazione non si può annullare."):
            return
        text, ok = QInputDialog.getText(self, APP_NAME, "Per confermare scrivere CANCELLA:")
        if ok and text.strip().upper() == "CANCELLA":
            mv.delete_all(self.arc)
            self.reload()

    def schedules(self):
        ScheduleDialog(self.arc, self).exec()
        self.reload()

    def daily(self):
        daily_report(self.arc, self.model.year, self.model.month, self.model.risorsa_id, self).exec()

    def trend(self, projection: bool):
        trend_report(self.arc, self.model.year, self.model.month, self.model.risorsa_id, projection, self).exec()

    # --- fase 3: pagina d'avvio, stampe, strumenti ----------------------------------------------------
    def show_start_page(self):
        self.start_page.refresh()
        self.stack.setCurrentIndex(0)

    def show_movements(self):
        self.stack.setCurrentIndex(1)
        self.view.go_to_new_row()
        self.view.setFocus()

    def _start_action(self, name: str):
        if name in ("movimenti", "nuovo"):
            self.show_movements()
        elif name == "giroconto":
            self.show_movements()
            self.new_transfer()
        elif name == "agenda":
            self.agenda()
        elif name == "scadute":
            self.overdue_report()
        elif name in ("risorse", "gruppi"):
            self.edit_table(name)
        elif name == "scadenzario":
            self.schedules()
        if self.stack.currentIndex() == 0:
            self.start_page.refresh()

    def overdue_report(self):
        from .dialogs import TableReport
        a, dec = self.arc, self.arc.decimals
        rows = [[m.data.strftime("%d/%m/%Y"), "‹giroconto›" if m.is_transfer else a.name_of("gruppi", m.gruppo_id),
                 a.name_of("risorse", m.risorsa_id), fmt_amount(m.entrata, dec, True), fmt_amount(m.uscita, dec, True),
                 m.descrizione] for m in tools.start_page_data(a)["scadute"]]
        TableReport("Movimenti scaduti non saldati", ["Data", "Gruppo", "Risorsa", "Entrate", "Uscite", "Descrizione"],
                    rows, (3, 4), self, note="Movimenti con data precedente a oggi non ancora saldati.").exec()

    def agenda(self):
        cur = self.view.selected_movements() if self.view else []
        AgendaDialog(self.arc, cur[0].data if cur else None, self).exec()

    def _visible_grid(self):
        cols = [c for c in self.model.columns]
        headers = [COLUMN_INFO[c][0] for c in cols]
        rows = [[self.model._display(m, c) for c in cols] for m in self.model.rows]
        right = tuple(i for i, c in enumerate(cols) if c in ("entrata", "uscita"))
        return headers, rows, right

    def print_movements(self):
        headers, rows, right = self._visible_grid()
        who = self.arc.name_of("risorse", self.model.risorsa_id) if self.model.risorsa_id else "tutte le risorse"
        title = f"Movimenti di {MESI[self.model.month - 1]} {self.model.year} – {who}"
        print_table(self, title, headers, rows, "movimenti", right, landscape=True)

    def print_blank_grid(self):
        n, ok = QInputDialog.getInt(self, "Stampa griglia vuota", "Numero di righe:", 40, 1, 500)
        if not ok:
            return
        headers, _rows, _right = self._visible_grid()
        opts = PrintOptions.load("griglia_vuota", PrintOptions(orientamento="orizzontale"))
        PrintSetupDialog("Griglia per annotare i movimenti", blank_grid_html(headers, n, opts), "griglia_vuota", self,
                         PrintOptions(orientamento="orizzontale")).exec()

    def access_code(self):
        if PasswordDialog(self.arc, self).exec():
            state = "protetto da codice d'accesso" if self.arc.encrypted else "non protetto"
            self.statusBar().showMessage(f"Archivio {state}: {self.arc.path}", 8000)

    def _modal(self, dlg):
        dlg.exec()
        self.reload()

    def month_totals(self):
        if self.totals_window is None:
            self.totals_window = MonthTotalsWindow(self)
        self.totals_window.refresh()
        self.totals_window.show()
        self.totals_window.raise_()

    def bulk_change(self):
        dlg = BulkChangeDialog(self.arc, self)
        dlg.exec()
        if dlg.changed:
            self.reload()

    def archive_settings(self):
        if SettingsDialog(self.arc, self).exec():
            self.model.load()
            self._update_bar()

    def about(self):
        QMessageBox.about(self, APP_NAME, f"<h3>{APP_NAME} {__version__}</h3>"
                                          "<p>Gestione e analisi finanziaria personale e aziendale.</p>"
                                          "<p>Importa gli archivi di Danea Professional Manager 5.</p>")
