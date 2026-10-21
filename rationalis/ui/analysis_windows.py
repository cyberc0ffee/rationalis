"""Finestre di analisi (fase 2): elenco filtrato, riepiloghi, grafici, monitor statistiche, budget,
scostamenti, totali del mese, raggruppamenti, variazioni automatiche, elenco gruppi."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QRadioButton, QSpinBox, QSplitter, QTabWidget, QVBoxLayout, QWidget)

from .. import analysis as an
from .. import movements as mv
from ..db import Archive, ArchiveError, ValidationError
from ..money import ZERO, fmt_amount
from ..ui_text import MESI, month_name
from .charts import Chart
from .common import AmountEdit, DateEdit, LookupCombo, ask, error, group_items, lookup_items
from .dialogs import ReportTable, TableReport, export_report, print_report
from .filter_widget import FilterWidget


def _money(arc, v: Decimal, blank: bool = False) -> str:
    return fmt_amount(v, arc.decimals, blank_zero=blank)


def _close_row(dialog: QDialog, table: ReportTable, title_fn, extra: list[QPushButton] = ()) -> QHBoxLayout:
    row = QHBoxLayout()
    for b in extra:
        row.addWidget(b)
    exp = QPushButton("Esporta in &Excel…")
    exp.clicked.connect(lambda: export_report(dialog, title_fn(), table))
    row.addWidget(exp)
    prn = QPushButton("&Stampa…")
    prn.clicked.connect(lambda: print_report(dialog, title_fn(), table))
    row.addWidget(prn)
    row.addStretch()
    close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    close.rejected.connect(dialog.reject)
    row.addWidget(close)
    return row


# --- elenco movimenti filtrati -------------------------------------------------------------
class FilteredListDialog(QDialog):
    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Elenco movimenti filtrati")
        self.resize(1100, 680)
        self.searches = LookupCombo()
        self.searches.currentIndexChanged.connect(self._load_search)
        btns = QHBoxLayout()
        for text, fn in (("Salva come nuova…", self._save_new), ("Salva sulla corrente", self._save_current),
                         ("Elimina", self._delete_search)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        top = QGroupBox("Ricerche salvate")
        tl = QVBoxLayout(top)
        tl.addWidget(self.searches)
        tl.addLayout(btns)
        self.filter = FilterWidget(arc)
        fbox = QGroupBox("Impostazioni di ricerca")
        QVBoxLayout(fbox).addWidget(self.filter)
        self.extended = QCheckBox("Vista estesa (tutte le colonne)")
        show = QPushButton("&Visualizza elenco")
        show.setDefault(True)
        show.clicked.connect(self._run)
        self.totals = QLabel()
        self.table = ReportTable()
        left = QVBoxLayout()
        left.addWidget(top)
        left.addWidget(fbox)
        left.addWidget(self.extended)
        left.addWidget(show)
        left.addStretch()
        lw = QWidget()
        lw.setLayout(left)
        right = QVBoxLayout()
        right.addWidget(self.totals)
        right.addWidget(self.table)
        rw = QWidget()
        rw.setLayout(right)
        split = QSplitter()
        split.addWidget(lw)
        split.addWidget(rw)
        split.setSizes([420, 680])
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        lay.addLayout(_close_row(self, self.table, lambda: "Movimenti filtrati"))
        self._reload_searches()

    def _reload_searches(self, select: int | None = None):
        self.searches.fill([(r["id"], r["nome"]) for r in self.arc.rows("ricerche")], select)

    def _load_search(self):
        sid = self.searches.value()
        if sid is not None:
            self.filter.set_value(an.load_search(self.arc, sid))

    def _save_new(self):
        name, ok = QInputDialog.getText(self, "Nuova ricerca", "Nome della ricerca:")
        if ok:
            try:
                sid = an.save_search(self.arc, name, self.filter.value())
            except ArchiveError as e:
                error(self, e)
                return
            self._reload_searches(sid)

    def _save_current(self):
        sid = self.searches.value()
        if sid is None:
            self._save_new()
            return
        try:
            an.save_search(self.arc, self.arc.row("ricerche", sid)["nome"], self.filter.value(), sid)
        except ArchiveError as e:
            error(self, e)

    def _delete_search(self):
        sid = self.searches.value()
        if sid is not None and ask(self, "Eliminare la ricerca salvata?"):
            self.arc.conn.execute("DELETE FROM ricerche WHERE id = ?", (sid,))
            self._reload_searches()

    def _run(self):
        try:
            flt = self.filter.value()
            movs = an.filtered(self.arc, flt)
        except ArchiveError as e:
            error(self, e)
            return
        a = self.arc
        cur = flt.single_currency(a)
        t = an.totals(a, movs, cur)
        sigla = a.row("valute", cur)["sigla"] if cur else a.principal()["sigla"]
        self.totals.setText(f"<b>{t['numero']}</b> movimenti — entrate <b>{_money(a, t['entrate'])}</b>, uscite "
                            f"<b>{_money(a, t['uscite'])}</b>, saldo <b>{_money(a, t['saldo'])}</b> {sigla}")
        if self.extended.isChecked():
            headers = ["Data", "Gruppo", "Sottogruppo", "Risorsa", "Val.", "Entrate", "Uscite", "S", "Modalità", "C",
                       "Rif", "Descrizione", "Soggetto", "Destinazione"]
            rows = [[m.data.strftime("%d/%m/%Y"), a.name_of("gruppi", m.gruppo_id),
                     a.name_of("sottogruppi", m.sottogruppo_id), a.name_of("risorse", m.risorsa_id),
                     a.resource_currency(m.risorsa_id)["sigla"], _money(a, m.entrata, True), _money(a, m.uscita, True),
                     "*" if m.saldato else "", a.name_of("modalita", m.modalita_id), m.controllo, m.rif, m.descrizione,
                     a.name_of("soggetti", m.soggetto_id), a.name_of("destinazioni", m.destinazione_id)]
                    for m in movs]
            right = (5, 6)
        else:
            headers = ["Data", "Gruppo", "Risorsa", "Entrate", "Uscite", "S", "Descrizione"]
            rows = [[m.data.strftime("%d/%m/%Y"), a.name_of("gruppi", m.gruppo_id), a.name_of("risorse", m.risorsa_id),
                     _money(a, m.entrata, True), _money(a, m.uscita, True), "*" if m.saldato else "", m.descrizione]
                    for m in movs]
            right = (3, 4)
        self.table.fill(headers, rows, right)


# --- riepiloghi ------------------------------------------------------------------------------
class PeriodPicker(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.index = QComboBox()
        self.year = QSpinBox()
        self.year.setRange(1900, 2200)
        self.year.setValue(date.today().year)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.index)
        lay.addWidget(self.year)

    def set_kind(self, kind: str):
        cur = self.index.currentIndex()
        self.index.clear()
        n = 12 // an.PERIOD_MONTHS[kind]
        if kind == "mese":
            for i in range(1, 13):
                self.index.addItem(month_name(i), i)
        elif kind == "anno":
            self.index.addItem("—", 1)
        else:
            for i in range(1, n + 1):
                self.index.addItem(f"{i}° {kind}", i)
        self.index.setCurrentIndex(min(max(cur, 0), self.index.count() - 1))
        self.index.setEnabled(kind != "anno")

    def set_value(self, year: int, index: int):
        self.year.setValue(year)
        self.index.setCurrentIndex(max(0, self.index.findData(index)))

    def value(self, kind: str) -> an.Period:
        return an.period(kind, self.year.value(), self.index.currentData() or 1)


class SummaryDialog(QDialog):
    PRESETS = ["Bilancio dell'anno corrente per gruppo (12 mesi)", "Mese corrente e due mesi precedenti per gruppo",
               "Trimestre corrente: quest'anno e due anni prima", "Ultimi tre anni per gruppo",
               "Ultimi tre anni per sottogruppo", "Anno corrente per risorsa (12 mesi)"]

    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Riepiloghi")
        self.resize(1150, 720)
        self.rows: list[an.SummaryRow] = []
        self.periods: list[an.Period] = []
        self.by = QComboBox()
        for k in ("gruppo", "sottogruppo", "risorsa", "destinazione", "soggetto"):
            self.by.addItem(an.GROUP_BY[k], k)
        self.mode3 = QRadioButton("Tre periodi")
        self.mode12 = QRadioButton("Dodici mesi")
        g = QButtonGroup(self)
        g.addButton(self.mode3)
        g.addButton(self.mode12)
        self.kind = QComboBox()
        for k, v in an.PERIOD_NAMES.items():
            self.kind.addItem(v, k)
        self.pickers = [PeriodPicker() for _ in range(3)]
        self.start_month = QComboBox()
        for i in range(1, 13):
            self.start_month.addItem(month_name(i), i)
        self.start_year = QSpinBox()
        self.start_year.setRange(1900, 2200)
        self.start_year.setValue(date.today().year)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.mode3.toggled.connect(self._mode_changed)
        self.use_filter = QCheckBox("Applica il filtro")
        self.filter = FilterWidget(arc, with_dates=False)
        self.filter.setEnabled(False)
        self.use_filter.toggled.connect(self.filter.setEnabled)
        self.preset = QComboBox()
        self.preset.addItem("Riepiloghi preimpostati…", None)
        for i, p in enumerate(self.PRESETS):
            self.preset.addItem(p, i)
        self.preset.currentIndexChanged.connect(self._apply_preset)

        form = QFormLayout()
        form.addRow("Riepilogo per", self.by)
        modes = QHBoxLayout()
        modes.addWidget(self.mode3)
        modes.addWidget(self.mode12)
        form.addRow("Periodi", modes)
        self.box3 = QWidget()
        f3 = QFormLayout(self.box3)
        f3.setContentsMargins(0, 0, 0, 0)
        f3.addRow("Tipo di periodo", self.kind)
        for i, p in enumerate(self.pickers, 1):
            f3.addRow(f"Periodo {i}", p)
        self.box12 = QWidget()
        f12 = QHBoxLayout(self.box12)
        f12.setContentsMargins(0, 0, 0, 0)
        f12.addWidget(QLabel("a partire da"))
        f12.addWidget(self.start_month)
        f12.addWidget(self.start_year)
        run = QPushButton("&Visualizza riepilogo")
        run.setDefault(True)
        run.clicked.connect(self._run)
        left = QVBoxLayout()
        left.addWidget(self.preset)
        left.addLayout(form)
        left.addWidget(self.box3)
        left.addWidget(self.box12)
        fb = QGroupBox()
        fl = QVBoxLayout(fb)
        fl.addWidget(self.use_filter)
        fl.addWidget(self.filter)
        left.addWidget(fb)
        left.addWidget(run)
        left.addStretch()
        lw = QWidget()
        lw.setLayout(left)

        self.table = ReportTable()
        self.table.itemSelectionChanged.connect(self._chart_selected)
        self.chart = Chart("", arc.decimals)
        self.chart_hint = QLabel("Selezionare una riga per vederne il grafico per periodo.")
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.table)
        cw = QWidget()
        cl = QVBoxLayout(cw)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.chart_hint)
        cl.addWidget(self.chart)
        right.addWidget(cw)
        right.setSizes([380, 260])
        split = QSplitter()
        split.addWidget(lw)
        split.addWidget(right)
        split.setSizes([400, 750])
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        lay.addLayout(_close_row(self, self.table, self._title))
        self.mode3.setChecked(True)
        self.kind.setCurrentIndex(self.kind.findData("mese"))
        self._kind_changed()
        today = date.today()
        for i, p in enumerate(self.pickers):
            y, m = today.year, today.month - (2 - i)
            if m < 1:
                y, m = y - 1, m + 12
            p.set_value(y, m)

    def _mode_changed(self):
        self.box3.setVisible(self.mode3.isChecked())
        self.box12.setVisible(self.mode12.isChecked())

    def _kind_changed(self):
        for p in self.pickers:
            p.set_kind(self.kind.currentData())

    def _apply_preset(self):
        i = self.preset.currentData()
        if i is None:
            return
        t = date.today()
        q = (t.month - 1) // 3 + 1
        self.use_filter.setChecked(False)
        by = "gruppo"
        if i in (0, 5):
            self.mode12.setChecked(True)
            self.start_month.setCurrentIndex(0)
            self.start_year.setValue(t.year)
            by = "risorsa" if i == 5 else "gruppo"
        else:
            self.mode3.setChecked(True)
            kind = {1: "mese", 2: "trimestre", 3: "anno", 4: "anno"}[i]
            self.kind.setCurrentIndex(self.kind.findData(kind))
            self._kind_changed()
            for k, p in enumerate(self.pickers):
                if i == 1:
                    y, m = t.year, t.month - (2 - k)
                    if m < 1:
                        y, m = y - 1, m + 12
                    p.set_value(y, m)
                elif i == 2:
                    p.set_value(t.year - (2 - k), q)
                else:
                    p.set_value(t.year - (2 - k), 1)
            by = "sottogruppo" if i == 4 else "gruppo"
        self.by.setCurrentIndex(self.by.findData(by))
        self.preset.setCurrentIndex(0)
        self._run()

    def _title(self) -> str:
        if not self.periods:
            return "Riepilogo"
        return f"Riepilogo per {self.by.currentText().lower()}: {self.periods[0].label} – {self.periods[-1].label}"

    def _run(self):
        try:
            if self.mode3.isChecked():
                kind = self.kind.currentData()
                self.periods = [p.value(kind) for p in self.pickers]
            else:
                self.periods = an.twelve_months(self.start_year.value(), self.start_month.currentData())
            flt = self.filter.value() if self.use_filter.isChecked() else None
            self.rows, tot = an.summary(self.arc, self.by.currentData(), self.periods, flt)
        except ArchiveError as e:
            error(self, e)
            return
        a = self.arc
        headers = [self.by.currentText()] + [p.label for p in self.periods] + ["Totale", "Media"]
        rows = [[r.label] + [_money(a, v, True) for v in r.values] + [_money(a, r.total), _money(a, r.mean)]
                for r in self.rows]
        rows.append([tot.label] + [_money(a, v) for v in tot.values] + [_money(a, tot.total), _money(a, tot.mean)])
        self.table.fill(headers, rows, tuple(range(1, len(headers))), bold_rows=(len(rows) - 1,))
        self.totals_row = tot
        self.setWindowTitle(self._title())
        self.table.selectRow(len(rows) - 1)

    def _chart_selected(self):
        r = self.table.currentRow()
        if r < 0 or not self.periods:
            return
        row = self.rows[r] if r < len(self.rows) else self.totals_row
        labels = [p.label for p in self.periods]
        if len(labels) == 12:
            labels = [p.label.split()[0][:3] for p in self.periods]
        self.chart.chart().setTitle(f"{row.label}: entrate − uscite per periodo")
        self.chart.signed_bars(labels, row.values)
        self.chart_hint.setVisible(False)


# --- grafici ------------------------------------------------------------------------------------
class ChartsDialog(QDialog):
    def __init__(self, arc: Archive, year: int, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Grafici")
        self.resize(1050, 640)
        self.form = QComboBox()
        self.form.addItem("Barre (classifica delle voci)", "barre")
        self.form.addItem("Torta (parti dell'intero)", "torta")
        self.kind = QComboBox()
        self.kind.addItem("Uscite", "uscite")
        self.kind.addItem("Entrate", "entrate")
        self.by = QComboBox()
        for k in ("gruppo", "sottogruppo", "risorsa", "destinazione", "soggetto", "mese"):
            self.by.addItem(an.GROUP_BY[k], k)
        self.d_from, self.d_to = DateEdit(date(year, 1, 1)), DateEdit(date(year, 12, 31))
        self.res = LookupCombo()
        self.res.fill(lookup_items(arc, "risorse"))
        for w in (self.form, self.kind, self.by, self.res):
            w.currentIndexChanged.connect(self._run)
        for w in (self.d_from, self.d_to):
            w.dateChanged.connect(self._run)
        bar = QHBoxLayout()
        for lbl, w in (("Grafico", self.form), ("Dati", self.kind), ("per", self.by), ("dal", self.d_from),
                       ("al", self.d_to), ("Risorsa", self.res)):
            bar.addWidget(QLabel(lbl))
            bar.addWidget(w)
        bar.addStretch()
        self.tabs = QTabWidget()
        self.chart = Chart("", arc.decimals)
        self.table = ReportTable()
        self.tabs.addTab(self.chart, "Grafico")
        self.tabs.addTab(self.table, "Tabella")
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.tabs)
        lay.addLayout(_close_row(self, self.table, self._title))
        self._run()

    def _title(self) -> str:
        return (f"{self.kind.currentText()} per {self.by.currentText().lower()} dal {self.d_from.value():%d/%m/%Y} "
                f"al {self.d_to.value():%d/%m/%Y}")

    def _run(self, *_):
        a = self.arc
        by = self.by.currentData()
        if self.d_from.value() > self.d_to.value():
            return
        rid = self.res.value()
        pairs = an.chart_data(a, self.d_from.value(), self.d_to.value(), by, self.kind.currentData(), rid)
        total = sum((v for _, v in pairs), ZERO)
        cur = a.resource_currency(rid)["sigla"] if rid else a.principal()["sigla"]
        self.table.fill([self.by.currentText(), f"Importo ({cur})", "%"],
                        [[lbl, _money(a, v), f"{an.share(v, total):.1f}%".replace(".", ",")] for lbl, v in pairs]
                        + [["Totale", _money(a, total), "100,0%" if pairs else ""]], (1, 2),
                        bold_rows=(len(pairs),))
        self.chart.chart().setTitle(f"{self._title()} ({cur})")
        form = "barre" if by == "mese" else self.form.currentData()
        if by == "mese":
            self.chart.bars([p[0].split()[0][:3] + " " + p[0].split()[1][2:] for p in pairs], [p[1] for p in pairs])
        elif form == "torta":
            self.chart.pie(pairs)
        else:
            top = pairs[:20]
            if len(pairs) > 20:
                top = pairs[:19] + [("Altro", sum((v for _, v in pairs[19:]), ZERO))]
            self.chart.bars([p[0] for p in top], [p[1] for p in top], horizontal=True)


# --- monitor statistiche ------------------------------------------------------------------------
class MonitorDialog(QDialog):
    def __init__(self, arc: Archive, year: int, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Monitor statistiche")
        self.resize(1000, 600)
        self.d_from, self.d_to = DateEdit(date(year, 1, 1)), DateEdit(date(year, 12, 31))
        self.res = LookupCombo()
        self.res.fill(lookup_items(arc, "risorse"))
        self.by = QComboBox()
        for k, v in an.GROUP_BY.items():
            self.by.addItem(v, k)
        self.pct = QCheckBox("Mostra %")
        run = QPushButton("&Elabora")
        run.setDefault(True)
        run.clicked.connect(self._run)
        self.pct.toggled.connect(self._run)
        bar = QHBoxLayout()
        for lbl, w in (("Dal", self.d_from), ("al", self.d_to), ("Risorsa", self.res), ("Raggruppa per", self.by)):
            bar.addWidget(QLabel(lbl))
            bar.addWidget(w)
        bar.addWidget(self.pct)
        bar.addWidget(run)
        bar.addStretch()
        self.table = ReportTable()
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(self.table)
        lay.addLayout(_close_row(self, self.table, lambda: f"Monitor statistiche per {self.by.currentText().lower()}"))
        self._run()

    def _run(self, *_):
        a = self.arc
        try:
            rows, tot = an.monitor(a, self.d_from.value(), self.d_to.value(), self.by.currentData(), self.res.value())
        except ArchiveError as e:
            error(self, e)
            return
        pct = self.pct.isChecked()

        def pc(x, w):
            return f"{an.share(x, w):.1f}%".replace(".", ",")

        headers = [self.by.currentText(), "N. entrate", "Entrate", "N. uscite", "Uscite", "N.", "Saldo"]
        if pct:
            headers += ["% n. mov.", "% entrate", "% uscite"]
        out = []
        for r in rows + [tot]:
            line = [r.label, str(r.n_entrate), _money(a, r.entrate, True), str(r.n_uscite), _money(a, r.uscite, True),
                    str(r.n), _money(a, r.saldo)]
            if pct:
                line += [pc(r.n, tot.n), pc(r.entrate, tot.entrate), pc(r.uscite, tot.uscite)]
            out.append(line)
        self.table.fill(headers, out, tuple(range(1, len(headers))), bold_rows=(len(out) - 1,))


# --- budget ------------------------------------------------------------------------------------
class BudgetDialog(QDialog):
    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.current: int | None = None
        self.setWindowTitle(f"Impostazione budget (importi in {arc.principal()['sigla']})")
        self.resize(760, 520)
        self.list = QListWidget()
        for gid, text in group_items(arc):
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, gid)
            self.list.addItem(it)
        self.list.currentItemChanged.connect(self._select)
        grid = QGridLayout()
        self.edits = []
        for i in range(12):
            e = AmountEdit(arc.decimals, allow_negative=True)
            grid.addWidget(QLabel(month_name(i + 1)), i % 6, (i // 6) * 2)
            grid.addWidget(e, i % 6, (i // 6) * 2 + 1)
            self.edits.append(e)
        self.total = QLabel()
        assist = QGroupBox("Inserimento assistito")
        al = QHBoxLayout(assist)
        self.assist_amount = AmountEdit(arc.decimals, allow_negative=True)
        b_year = QPushButton("Importo annuale ÷ 12")
        b_year.clicked.connect(lambda: self._assist("annuale"))
        b_month = QPushButton("Importo mensile × 12")
        b_month.clicked.connect(lambda: self._assist("mensile"))
        al.addWidget(self.assist_amount)
        al.addWidget(b_year)
        al.addWidget(b_month)
        save = QPushButton("&Salva budget del gruppo")
        save.clicked.connect(self._save)
        hint = QLabel("Importi positivi: spesa prevista per i gruppi di uscita, incasso previsto per quelli di "
                      "entrata. Per i gruppi misti un importo negativo indica un'uscita.")
        hint.setWordWrap(True)
        right = QVBoxLayout()
        right.addLayout(grid)
        right.addWidget(self.total)
        right.addWidget(assist)
        right.addWidget(save)
        right.addWidget(hint)
        right.addStretch()
        body = QHBoxLayout()
        body.addWidget(self.list, 2)
        body.addLayout(right, 3)
        b_sheet = QPushButton("Prospetto budget annuale…")
        b_sheet.clicked.connect(lambda: budget_sheet_report(arc, self).exec())
        b_var = QPushButton("Analisi scostamenti…")
        b_var.clicked.connect(lambda: VarianceDialog(arc, date.today().year, self).exec())
        row = QHBoxLayout()
        row.addWidget(b_sheet)
        row.addWidget(b_var)
        row.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addLayout(body)
        lay.addLayout(row)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _select(self, item, _prev=None):
        self.current = item.data(Qt.ItemDataRole.UserRole) if item else None
        vals = an.budget_of(self.arc, self.current) if self.current else [ZERO] * 12
        for e, v in zip(self.edits, vals):
            e.set_value(v if v else None)
        self._update_total()

    def _values(self) -> list[Decimal]:
        return [e.value() for e in self.edits]

    def _update_total(self):
        try:
            self.total.setText(f"Totale annuo: <b>{_money(self.arc, sum(self._values(), ZERO))}</b>")
        except ValueError:
            self.total.setText("")

    def _assist(self, mode: str):
        try:
            vals = an.assisted_budget(self.assist_amount.value(), mode)
        except ValueError as e:
            error(self, e)
            return
        for e, v in zip(self.edits, vals):
            e.set_value(v)
        self._update_total()

    def _save(self):
        if self.current is None:
            return
        try:
            an.set_budget(self.arc, self.current, self._values())
        except (ValueError, ArchiveError) as e:
            error(self, e)
            return
        self._update_total()


def budget_sheet_report(arc: Archive, parent=None) -> TableReport:
    sheet = an.budget_sheet(arc)
    headers = ["Gruppo"] + [m[:3].capitalize() for m in MESI] + ["Totale"]
    rows = [[name] + [_money(arc, v, True) for v in vals] + [_money(arc, sum(vals, ZERO))] for name, _t, vals in sheet]
    totals = [sum((vals[i] for _n, _t, vals in sheet), ZERO) for i in range(12)]
    rows.append(["Totale"] + [_money(arc, v) for v in totals] + [_money(arc, sum(totals, ZERO))])
    return TableReport(f"Prospetto budget annuale ({arc.principal()['sigla']})", headers, rows,
                       tuple(range(1, 14)), parent, note="Entrate previste positive, uscite previste negative.",
                       bold_rows=(len(rows) - 1,))


class VarianceDialog(QDialog):
    def __init__(self, arc: Archive, year: int, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Analisi scostamenti budget")
        self.resize(1150, 600)
        self.year = QSpinBox()
        self.year.setRange(1900, 2200)
        self.year.setValue(year)
        self.m_from, self.m_to = QComboBox(), QComboBox()
        for i in range(1, 13):
            self.m_from.addItem(month_name(i), i)
            self.m_to.addItem(month_name(i), i)
        self.m_to.setCurrentIndex(date.today().month - 1 if year == date.today().year else 11)
        self.only = QCheckBox("Solo gruppi con budget impostato")
        self.only.setChecked(True)
        run = QPushButton("&Elabora")
        run.setDefault(True)
        run.clicked.connect(self._run)
        bar = QHBoxLayout()
        for lbl, w in (("Anno", self.year), ("da", self.m_from), ("a", self.m_to)):
            bar.addWidget(QLabel(lbl))
            bar.addWidget(w)
        bar.addWidget(self.only)
        bar.addWidget(run)
        bar.addStretch()
        note = QLabel("Per ogni gruppo: movimenti saldati (riga evidenziata), budget, scostamento. "
                      "Uno scostamento positivo indica meno spesa o più entrata del previsto.")
        note.setWordWrap(True)
        self.table = ReportTable()
        lay = QVBoxLayout(self)
        lay.addLayout(bar)
        lay.addWidget(note)
        lay.addWidget(self.table)
        lay.addLayout(_close_row(self, self.table, lambda: f"Scostamenti budget {self.year.value()}"))
        self._run()

    def _run(self):
        a = self.arc
        try:
            lines = an.budget_variance(a, self.year.value(), self.m_from.currentData(), self.m_to.currentData(),
                                       self.only.isChecked())
        except ArchiveError as e:
            error(self, e)
            return
        months = list(range(self.m_from.currentData(), self.m_to.currentData() + 1))
        headers = ["Gruppo", ""] + [month_name(m)[:3] for m in months] + ["Totale"]
        rows, shaded, bold = [], [], []
        for ln in lines:
            for label, vals in (("Movimenti", ln.consuntivo), ("Budget", ln.budget), ("Scostamento", ln.scostamento)):
                if label == "Movimenti":
                    shaded.append(len(rows))
                if label == "Scostamento":
                    bold.append(len(rows))
                rows.append([ln.gruppo if label == "Movimenti" else "", label] + [_money(a, v) for v in vals]
                            + [_money(a, sum(vals, ZERO))])
        self.table.fill(headers, rows, tuple(range(2, len(headers))), bold_rows=bold, shaded_rows=shaded)


# --- totali del mese (finestra sempre aggiornata) ------------------------------------------------
class MonthTotalsWindow(QDialog):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self.setWindowTitle("Totali del mese")
        self.setWindowFlag(Qt.WindowType.Tool)
        self.on_top = QCheckBox("Sempre in primo piano")
        self.on_top.toggled.connect(self._top)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        lay = QVBoxLayout(self)
        lay.addWidget(self.label)
        lay.addWidget(self.on_top)
        self.refresh()

    def _top(self, on: bool):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()

    def refresh(self):
        m = self.main.model
        if m is None:
            return
        a = self.main.arc
        t = an.month_totals(a, m.year, m.month, m.risorsa_id)
        cur = a.resource_currency(m.risorsa_id)["sigla"] if m.risorsa_id else a.principal()["sigla"]
        who = a.name_of("risorse", m.risorsa_id) if m.risorsa_id else "tutte le risorse"

        def row(label, d):
            return (f"<tr><td><b>{label}</b></td><td align=right>{_money(a, d['entrate'])}</td>"
                    f"<td align=right>{_money(a, d['uscite'])}</td><td align=right><b>{_money(a, d['saldo'])}</b></td></tr>")

        self.label.setText(f"<p>{who} – {cur} (solo saldati)</p><table cellspacing=6>"
                           "<tr><th></th><th>Entrate</th><th>Uscite</th><th>Differenza</th></tr>"
                           f"{row(month_name(m.month) + ' ' + str(m.year), t['mese'])}{row('Anno ' + str(m.year), t['anno'])}"
                           "</table>")


# --- raggruppamenti ------------------------------------------------------------------------------
class GroupingsDialog(QDialog):
    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Raggruppamenti")
        self.resize(900, 520)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        self.groups = QListWidget()
        self.groups.currentItemChanged.connect(self._fill_subs)
        self.groups.itemDoubleClicked.connect(lambda it: self._add(it.data(Qt.ItemDataRole.UserRole), None))
        self.subs = QListWidget()
        self.subs.itemDoubleClicked.connect(lambda it: self._add(self._group(), it.data(Qt.ItemDataRole.UserRole)))
        self.chosen = QListWidget()
        self.chosen.itemDoubleClicked.connect(self._remove)
        for gid, text in group_items(arc):
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, gid)
            self.groups.addItem(it)
        lists = QHBoxLayout()
        for title, w in (("Gruppi (doppio clic = gruppo intero)", self.groups),
                         ("Sottogruppi (doppio clic = aggiungi)", self.subs),
                         ("Voci del raggruppamento (doppio clic = togli)", self.chosen)):
            col = QVBoxLayout()
            col.addWidget(QLabel(title))
            col.addWidget(w)
            lists.addLayout(col)
        left = QVBoxLayout()
        left.addWidget(QLabel("Raggruppamenti"))
        left.addWidget(self.list)
        btns = QHBoxLayout()
        for text, fn in (("Nuovo…", self._new), ("Rinomina…", self._rename), ("Elimina", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        left.addLayout(btns)
        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addLayout(lists, 3)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(body)
        lay.addWidget(close)
        self._reload()

    def _current(self) -> int | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _group(self) -> int | None:
        it = self.groups.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _reload(self, select: int | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        for r in self.arc.rows("raggruppamenti"):
            it = QListWidgetItem(r["nome"])
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.list.addItem(it)
            if r["id"] == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._select(self.list.currentItem())

    def _select(self, *_):
        self.chosen.clear()
        rid = self._current()
        if rid is None:
            return
        for v in self.arc.rows("raggruppamenti_voci", "raggruppamento_id = ?", (rid,), order="id"):
            g = self.arc.name_of("gruppi", v["gruppo_id"])
            text = f"Sottogr.: {g} / {self.arc.name_of('sottogruppi', v['sottogruppo_id'])}" if v["sottogruppo_id"] \
                else f"Gruppo: {g}"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, v["id"])
            self.chosen.addItem(it)

    def _fill_subs(self, *_):
        self.subs.clear()
        g = self._group()
        if g is None:
            return
        for sid, text in lookup_items(self.arc, "sottogruppi", "gruppo_id = ?", (g,)):
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, sid)
            self.subs.addItem(it)

    def _add(self, gid: int | None, sid: int | None):
        rid = self._current()
        if rid is None or gid is None:
            error(self, "Creare o scegliere prima un raggruppamento")
            return
        dup = self.arc.conn.execute(
            "SELECT 1 FROM raggruppamenti_voci WHERE raggruppamento_id = ? AND gruppo_id = ? AND "
            "(sottogruppo_id IS ? OR sottogruppo_id IS NULL)", (rid, gid, sid)).fetchone()
        if dup:
            return
        self.arc.insert("raggruppamenti_voci", raggruppamento_id=rid, gruppo_id=gid, sottogruppo_id=sid)
        self._select()

    def _remove(self, item):
        self.arc.conn.execute("DELETE FROM raggruppamenti_voci WHERE id = ?", (item.data(Qt.ItemDataRole.UserRole),))
        self._select()

    def _new(self):
        name, ok = QInputDialog.getText(self, "Nuovo raggruppamento", "Nome:")
        if ok and name.strip():
            self._reload(self.arc.insert("raggruppamenti", nome=name.strip()))

    def _rename(self):
        rid = self._current()
        if rid is None:
            return
        name, ok = QInputDialog.getText(self, "Rinomina raggruppamento", "Nome:", text=self.arc.name_of(
            "raggruppamenti", rid))
        if ok and name.strip():
            self.arc.update("raggruppamenti", rid, nome=name.strip())
            self._reload(rid)

    def _delete(self):
        rid = self._current()
        if rid is not None and ask(self, "Eliminare il raggruppamento? I movimenti non vengono toccati."):
            self.arc.delete("raggruppamenti", rid)
            self._reload()


# --- variazioni automatiche -------------------------------------------------------------------------
class BulkChangeDialog(QDialog):
    FIELDS = (("gruppo", "Gruppo e sottogruppo", "gruppi"), ("risorsa", "Risorsa", "risorse"),
              ("destinazione", "Destinazione", "destinazioni"), ("soggetto", "Soggetto", "soggetti"))

    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Variazioni automatiche")
        self.tabs = QTabWidget()
        self.pages = {}
        for key, title, table in self.FIELDS:
            w = QWidget()
            f = QFormLayout(w)
            old, new = LookupCombo(allow_empty=False), LookupCombo(allow_empty=key in ("destinazione", "soggetto"))
            items = group_items(arc) if key == "gruppo" else lookup_items(arc, table)
            old.fill(items)
            new.fill(items)
            page = {"old": old, "new": new}
            f.addRow("Movimenti con", old)
            if key == "gruppo":
                old_sub, new_sub = LookupCombo(), LookupCombo()
                old_sub.setToolTip("Vuoto = tutti i sottogruppi del gruppo")
                old.currentIndexChanged.connect(lambda _=0, c=old, s=old_sub: self._subs(c, s))
                new.currentIndexChanged.connect(lambda _=0, c=new, s=new_sub: self._subs(c, s))
                self._subs(old, old_sub)
                self._subs(new, new_sub)
                f.addRow("e sottogruppo (vuoto = tutti)", old_sub)
                page.update(old_sub=old_sub, new_sub=new_sub)
            replace = QRadioButton("Sostituisci con")
            delete = QRadioButton("Cancella i movimenti")
            replace.setChecked(True)
            grp = QButtonGroup(w)
            grp.addButton(replace)
            grp.addButton(delete)
            f.addRow(replace, new)
            if key == "gruppo":
                f.addRow("nuovo sottogruppo", page["new_sub"])
            f.addRow(delete)
            page.update(replace=replace, delete=delete)
            self.pages[key] = page
            self.tabs.addTab(w, title)
        apply = QPushButton("&Applica variazioni")
        apply.clicked.connect(self._apply)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        note = QLabel("Le variazioni riguardano tutti i movimenti dell'archivio (non i giroconti) e non si "
                      "possono annullare: conviene fare prima una copia di sicurezza.")
        note.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(note)
        row = QHBoxLayout()
        row.addWidget(apply)
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)
        self.changed = False

    def _subs(self, combo: LookupCombo, sub: LookupCombo):
        g = combo.value()
        sub.fill(lookup_items(self.arc, "sottogruppi", "gruppo_id = ?", (g,)) if g else [])

    def _apply(self):
        key = self.FIELDS[self.tabs.currentIndex()][0]
        p = self.pages[key]
        old = p["old"].value()
        if old is None:
            return
        old_sub = p["old_sub"].value() if key == "gruppo" else None
        col = f"{key}_id"
        where = f"{col} = ? AND giroconto_id IS NULL" + (" AND sottogruppo_id = ?" if old_sub else "")
        params = [old] + ([old_sub] if old_sub else [])
        n = self.arc.conn.execute(f"SELECT COUNT(*) FROM movimenti WHERE {where}", params).fetchone()[0]
        if not n:
            error(self, "Nessun movimento corrisponde alla scelta")
            return
        deleting = p["delete"].isChecked()
        verb = "cancellati" if deleting else "modificati"
        if not ask(self, f"Verranno {verb} {n} movimenti. Continuare?"):
            return
        try:
            done = mv.bulk_change(self.arc, key, old, p["new"].value(), old_sub,
                                  p["new_sub"].value() if key == "gruppo" else None, deleting)
        except (ValidationError, ArchiveError) as e:
            error(self, e)
            return
        self.changed = True
        QMessageBox.information(self, self.windowTitle(), f"{done} movimenti {verb}.")


# --- elenco gruppi e sottogruppi -----------------------------------------------------------------
def groups_outline_report(arc: Archive, parent=None) -> TableReport:
    outline = an.groups_outline(arc)
    rows, bold = [], []
    for tipo, title in (("E", "ENTRATE"), ("U", "USCITE"), ("M", "ENTRATE E USCITE")):
        if not outline[tipo]:
            continue
        bold.append(len(rows))
        rows.append([title, ""])
        for g, subs in outline[tipo]:
            rows.append([g, ", ".join(subs)])
    return TableReport("Elenco gruppi e sottogruppi", ["Gruppo", "Sottogruppi"], rows, (), parent, bold_rows=bold)
