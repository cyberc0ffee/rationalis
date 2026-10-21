"""Prova dell'interfaccia senza schermo (QT_QPA_PLATFORM=offscreen): inserimento in griglia e apertura
delle finestre principali. Le impostazioni Qt sono dirottate su un file temporaneo."""
import os
from datetime import date
from decimal import Decimal as D

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from rationalis import movements as mv  # noqa: E402
from rationalis import transfers as tr  # noqa: E402
from rationalis.db import Archive  # noqa: E402


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("ini")))
    a = QApplication.instance() or QApplication([])
    a.setOrganizationName("RationalisTest")
    a.setApplicationName("RationalisTest")
    return a


@pytest.fixture
def win(app, tmp_path):
    from rationalis.ui.main_window import MainWindow
    w = MainWindow()
    w.set_archive(Archive.create(tmp_path / "prova.rtl"))
    yield w
    w.close_archive()
    w.deleteLater()


def test_insert_from_grid(win):
    m = win.model
    win._set_period(2024, 3)
    banca = win.arc.find_by_name("risorse", "Banca c/c")["id"]
    stip = win.arc.find_by_name("gruppi", "Stipendi e compensi")["id"]
    new_row = m.rowCount() - 1
    col = m.columns.index
    assert m.setData(m.index(new_row, col("giorno")), 10)
    assert m.setData(m.index(new_row, col("entrata")), "1.350,00")
    assert m.setData(m.index(new_row, col("risorsa")), banca)
    assert m.setData(m.index(new_row, col("gruppo")), stip)      # ora il movimento è completo e viene salvato
    movs = mv.list_month(win.arc, 2024, 3)
    assert len(movs) == 1 and movs[0].importo == D(1350) and movs[0].data == date(2024, 3, 10)
    assert m.rowCount() == 2
    # modifica di una cella esistente e saldo
    assert m.setData(m.index(0, col("descrizione")), "Stipendio marzo")
    win.view.setCurrentIndex(m.index(0, 0))
    win.toggle_settled()
    assert mv.get(win.arc, movs[0].id).saldato
    assert "1.350,00" in win.end_lbl.text()
    # un'uscita su gruppo di entrata è rifiutata (messaggio d'errore sostituito)
    import rationalis.ui.movements_grid as grid
    grid.error = lambda *a, **k: None
    assert not m.setData(m.index(0, col("uscita")), "10")


def test_windows_open(win, tmp_path):
    from rationalis.ui.data_windows import SPECS, DataWindow
    from rationalis.ui.dialogs import (CardChargeDialog, ScheduleDialog, SettingsDialog, TransferDialog,
                                       TransfersManager, current_balances_report, daily_report, trend_report)
    arc = win.arc
    for t in SPECS:
        d = DataWindow(arc, t, win)
        d._new()
        d.close()
    arc.add_risorsa("Visa", "carta", arc.principal()["id"])
    cassa, banca = arc.find_by_name("risorse", "Cassa")["id"], arc.find_by_name("risorse", "Banca c/c")["id"]
    tid = tr.save(arc, tr.Transfer(date(2024, 3, 2), tr.Leg(banca, D(200)), [tr.Leg(cassa, D(200))]))
    TransferDialog(arc, tr.get(arc, tid), parent=win).close()
    TransfersManager(arc, 2024, 3, win).close()
    CardChargeDialog(arc, win).close()
    s = ScheduleDialog(arc, win)
    s.descr.setText("Affitto")
    s.importo.setText("800")
    s.gruppo.set_value(arc.find_by_name("gruppi", "Casa")["id"])
    s.end_by_count.setChecked(True)
    s.count.setValue(12)
    s._save()
    assert len(arc.rows("movimenti", "scadenza_id IS NOT NULL", order="id")) == 12
    s.close()
    SettingsDialog(arc, win).close()
    for rep in (current_balances_report(arc, win), daily_report(arc, 2024, 3, None, win),
                trend_report(arc, 2024, 1, cassa, True, win)):
        rep.close()
    win.reload()
    shot = os.environ.get("RATIONALIS_SCREENSHOT")
    if shot:
        win.resize(1250, 600)
        win.show()
        QApplication.processEvents()
        win.grab().save(shot)


def test_analysis_windows(win, tmp_path, monkeypatch):
    import rationalis.ui.analysis_windows as aw
    from rationalis import analysis as an
    from rationalis.interop.tabular import export_table_xlsx
    arc = win.arc
    g = lambda n: arc.find_by_name("gruppi", n)["id"]  # noqa: E731
    cassa = arc.find_by_name("risorse", "Cassa")["id"]
    for d, grp, imp in ((date(2024, 1, 5), "Alimentari", -30), (date(2024, 2, 5), "Trasporti", -45),
                        (date(2024, 2, 9), "Stipendi e compensi", 900)):
        mv.save(arc, mv.Movement(data=d, risorsa_id=cassa, gruppo_id=g(grp), importo=D(imp), saldato=True))
    monkeypatch.setattr(aw, "ask", lambda *a, **k: True)
    monkeypatch.setattr(aw.QMessageBox, "information", lambda *a, **k: None)

    fl = aw.FilteredListDialog(arc, win)
    fl.filter.d_from.set_date(date(2024, 1, 1))
    fl.filter.d_to.set_date(date(2024, 12, 31))
    fl._run()
    assert fl.table.rowCount() == 3
    fl.extended.setChecked(True)
    fl._run()
    assert fl.table.columnCount() == 14
    an.save_search(arc, "Tutto il 2024", fl.filter.value())
    fl._reload_searches()

    sd = aw.SummaryDialog(arc, win)
    sd.mode12.setChecked(True)
    sd.start_year.setValue(2024)
    sd.start_month.setCurrentIndex(0)
    sd._run()
    assert sd.table.rowCount() == 4 and sd.table.columnCount() == 15
    sd.table.selectRow(0)
    for i in range(1, sd.preset.count()):
        sd.preset.setCurrentIndex(i)
    export_table_xlsx(tmp_path / "riepilogo.xlsx", sd._title(), sd.table.headers, sd.table.data_rows)

    cd = aw.ChartsDialog(arc, 2024, win)
    assert cd.table.rowCount() == 3
    cd.form.setCurrentIndex(1)
    cd.by.setCurrentIndex(cd.by.findData("mese"))
    md = aw.MonitorDialog(arc, 2024, win)
    md.pct.setChecked(True)
    assert md.table.columnCount() == 10

    bd = aw.BudgetDialog(arc, win)
    for i in range(bd.list.count()):
        if bd.list.item(i).data(Qt.ItemDataRole.UserRole) == g("Alimentari"):
            bd.list.setCurrentRow(i)
    bd.assist_amount.setText("600")
    bd._assist("annuale")
    bd._save()
    assert an.budget_of(arc, g("Alimentari"))[0] == D(50)
    aw.budget_sheet_report(arc, win).close()
    vd = aw.VarianceDialog(arc, 2024, win)
    assert vd.table.rowCount() == 3

    gd = aw.GroupingsDialog(arc, win)
    monkeypatch.setattr(aw.QInputDialog, "getText", lambda *a, **k: ("Mobilità", True))
    gd._new()
    gd._add(g("Trasporti"), None)
    assert gd.chosen.count() == 1

    bc = aw.BulkChangeDialog(arc, win)
    p = bc.pages["gruppo"]
    p["old"].set_value(g("Trasporti"))
    p["new"].set_value(g("Spese varie"))
    bc._apply()
    assert bc.changed and not an.filtered(arc, an.Filter(gruppi=[g("Trasporti")]))

    tw = aw.MonthTotalsWindow(win)
    tw.refresh()
    aw.groups_outline_report(arc, win).close()


def test_tools_windows(win, tmp_path, monkeypatch):
    import rationalis.ui.tools_windows as tw
    from rationalis import tools
    from rationalis.ui.calculator_dialog import AmountCellEdit, CalculatorDialog
    from rationalis.ui.printing import Job, PrintOptions, save_pdf, table_html
    arc = win.arc
    monkeypatch.setattr(tw, "ask", lambda *a, **k: True)

    # calcolatrice da tastiera, modalità scelta importo
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    calc = CalculatorDialog(win, D("100"), picker=True)
    for text, key in (("+", Qt.Key.Key_Plus), ("2", Qt.Key.Key_2), ("2", Qt.Key.Key_2), ("%", Qt.Key.Key_Percent)):
        calc.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text))
    assert calc.calc.result == D(122)
    calc.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F3, Qt.KeyboardModifier.NoModifier, ""))
    assert "→" in calc.info.text()
    calc.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier, "\r"))
    assert calc.result_value == D(122)
    assert isinstance(win.view.itemDelegate().createEditor(
        win.view, None, win.model.index(0, win.model.columns.index("uscita"))), AmountCellEdit)

    cc = tw.CurrencyConverterDialog(arc, win)
    assert len(cc.edits) == 1

    inv = tw.InvestmentsDialog(arc, win)
    inv.nome.setText("BTP")
    inv.ci.setText("1000")
    inv.cf.setText("1150")
    inv.di.set_date(date(2023, 5, 4))
    inv.df.set_date(date(2023, 11, 15))
    assert "28,08%" in inv.out.text()
    inv._save()
    assert arc.rows("investimenti")

    ab = tw.AddressBookDialog(arc, win)
    ab._new()
    ab.w["nome"].setText("APIX Srl")
    ab.w["tel1"].setText("049 123")
    ab._save()
    assert tools.contacts(arc)[0]["nome"] == "APIX Srl"
    ab._set_letter("B")
    assert ab.list.count() == 0

    ag = tw.AgendaDialog(arc, date(2026, 5, 10), win)
    ag.text.setPlainText("rinnovo patente")
    ag.remind.setChecked(True)
    ag.cal.setSelectedDate(QtCore.QDate(2026, 5, 11))
    assert tools.agenda_get(arc, date(2026, 5, 10)) == ("rinnovo patente", True)
    ag.close()

    fc = tw.FreeCardsDialog(arc, win)
    fc._new()
    fc.nome.setText("Viacard")
    fc.table.item(0, 1).setText("apertura")
    fc.table.item(0, 2).setText("100")
    fc.table.item(1, 2).setText("-7,6")
    fc._save()
    assert "92,40" in fc.total.text()

    pw = tw.PasswordDialog(arc, win)
    pw.new1.setText("Gatto-42")
    pw.new2.setText("Gatto-42")
    pw.accept()
    assert arc.encrypted

    win.show_start_page()
    assert "Situazione delle risorse" in win.start_page.toPlainText()
    win.show_movements()
    headers, rows, right = win._visible_grid()
    job = Job("Prova", table_html(headers, rows, right, opts=PrintOptions()), PrintOptions())
    assert save_pdf(job, str(tmp_path / "mov.pdf")) == 1


def test_grid_zoom(win):
    w0 = win.view.columnWidth(0)
    win.view.set_zoom(145)
    assert win.view.columnWidth(0) > w0 and win.view.zoom == 145
