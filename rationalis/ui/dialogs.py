"""Finestre di dialogo: giroconti, addebito carta, scadenzario, ricerca, impostazioni, colonne, analisi rapide."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QRadioButton, QSpinBox, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget, QHeaderView, QFileDialog)

from .. import balances as bal
from .. import movements as mv
from .. import scheduler as sch
from .. import transfers as tr
from ..db import Archive, ArchiveError, ValidationError
from ..money import ZERO, fmt_amount, round_to
from ..recurrence import GIORNI, ORDINALI, Plan, describe, occurrences
from ..ui_text import GIORNI_BREVI, MESI
from .common import (AmountEdit, DateEdit, LookupCombo, ask, colors, error, group_items, is_dark,
                     lookup_items, month_label, shade_color)
from .charts import Chart
from .movements_grid import COLUMN_INFO, OPTIONAL_COLUMNS


def _buttons(dialog: QDialog, ok_text: str = "OK") -> QDialogButtonBox:
    b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    b.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    b.button(QDialogButtonBox.StandardButton.Cancel).setText("Annulla")
    b.accepted.connect(dialog.accept)
    b.rejected.connect(dialog.reject)
    return b


def _resource_items(arc, include=None):
    return [(i, f"{n}  ({arc.resource_currency(i)['sigla']})") for i, n in lookup_items(arc, "risorse", include=include)]


# --- giroconti ------------------------------------------------------------------
class TransferDialog(QDialog):
    def __init__(self, arc: Archive, transfer: tr.Transfer | None = None, default_date: date | None = None,
                 parent=None):
        super().__init__(parent)
        self.arc = arc
        self.transfer = transfer
        self.setWindowTitle("Giroconto" if transfer is None else "Modifica giroconto")
        dec = arc.decimals
        self.data = DateEdit(transfer.data if transfer else default_date or date.today())
        self.descr = QLineEdit(transfer.descrizione if transfer else "")
        self.descr.setMaxLength(mv.MAX_DESCRIZIONE)
        self.saldato = QCheckBox("Saldato")
        self.saldato.setChecked(transfer.saldato if transfer else arc.setting("salda_subito") == "1")

        grid = QGridLayout()
        grid.addWidget(QLabel("<b>Prelievo da</b>"), 0, 0)
        self.from_res = LookupCombo(allow_empty=False)
        self.from_amt = AmountEdit(dec, allow_negative=False)
        grid.addWidget(self.from_res, 0, 1)
        grid.addWidget(self.from_amt, 0, 2)
        self.to_res, self.to_amt, self.rate_lbl = [], [], []
        for i in range(tr.MAX_VERSAMENTI):
            grid.addWidget(QLabel(f"<b>Versamento {i + 1} in</b>" if i == 0 else f"Versamento {i + 1} in"), i + 1, 0)
            r = LookupCombo()
            a = AmountEdit(dec, allow_negative=False)
            lbl = QLabel()
            btn = QPushButton("=")
            btn.setToolTip("Calcola l'importo che azzera lo sbilancio")
            btn.setFixedWidth(28)
            btn.clicked.connect(lambda _=False, k=i: self._balance(k))
            grid.addWidget(r, i + 1, 1)
            grid.addWidget(a, i + 1, 2)
            grid.addWidget(btn, i + 1, 3)
            grid.addWidget(lbl, i + 1, 4)
            self.to_res.append(r)
            self.to_amt.append(a)
            self.rate_lbl.append(lbl)
        self.imbalance_lbl = QLabel()
        for w in [self.from_res, *self.to_res]:
            w.currentIndexChanged.connect(self._update)
        for w in [self.from_amt, *self.to_amt]:
            w.textChanged.connect(self._update)

        include = [transfer.prelievo.risorsa_id] + [v.risorsa_id for v in transfer.versamenti] if transfer else []
        items = _resource_items(arc)
        known = {i for i, _ in items}
        items += [(i, arc.name_of("risorse", i)) for i in include if i not in known]
        self.from_res.fill(items)
        for r in self.to_res:
            r.fill(items)
        if transfer:
            self.from_res.set_value(transfer.prelievo.risorsa_id)
            self.from_amt.set_value(transfer.prelievo.importo)
            for i, v in enumerate(transfer.versamenti):
                self.to_res[i].set_value(v.risorsa_id)
                self.to_amt[i].set_value(v.importo)

        form = QFormLayout()
        form.addRow("Data", self.data)
        form.addRow("Descrizione", self.descr)
        form.addRow("", self.saldato)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(grid)
        lay.addWidget(self.imbalance_lbl)
        lay.addWidget(_buttons(self, "Conferma"))
        self._update()

    def _build(self) -> tr.Transfer:
        frm = self.from_res.value()
        if frm is None:
            raise ValidationError("Scegliere la risorsa di prelievo")
        legs = []
        for r, a in zip(self.to_res, self.to_amt):
            if r.value() is not None and a.text().strip():
                legs.append(tr.Leg(r.value(), a.value()))
        return tr.Transfer(self.data.value(), tr.Leg(frm, self.from_amt.value()), legs, saldato=self.saldato.isChecked(),
                           descrizione=self.descr.text().strip(), scadenza_id=self.transfer.scadenza_id if self.transfer else None,
                           id=self.transfer.id if self.transfer else None)

    def _update(self):
        frm = self.from_res.value()
        cur_from = self.arc.resource_currency(frm) if frm else None
        for r, lbl in zip(self.to_res, self.rate_lbl):
            if frm and r.value():
                cur_to = self.arc.resource_currency(r.value())
                if cur_to["id"] != cur_from["id"]:
                    rate = bal.convert(self.arc, Decimal(1), cur_from["id"], cur_to["id"])
                    lbl.setText(f"1 {cur_from['sigla']} = {round_to(rate, 4)} {cur_to['sigla']}")
                    lbl.setToolTip(f"1 {cur_to['sigla']} = {round_to(1 / rate, 4)} {cur_from['sigla']}")
                    continue
            lbl.setText("")
        try:
            t = self._build()
            if not t.versamenti:
                raise ValueError
            imb = tr.imbalance(self.arc, t)
            self.imbalance_lbl.setText(f"Sbilancio: {fmt_amount(imb, self.arc.decimals)} {cur_from['sigla']}")
            c = colors(is_dark(self))
            self.imbalance_lbl.setStyleSheet(f"color: {c['in'] if abs(imb) < Decimal('0.005') else c['out']}")
        except (ValueError, ArchiveError, TypeError):
            self.imbalance_lbl.setText("Sbilancio: —")
            self.imbalance_lbl.setStyleSheet("")

    def _balance(self, k: int):
        try:
            t = self._build()
            if self.to_res[k].value() is None:
                return
            idx = [i for i, leg in enumerate(t.versamenti) if leg.risorsa_id == self.to_res[k].value()]
            if not idx:
                t.versamenti.append(tr.Leg(self.to_res[k].value(), Decimal("0.01")))
                idx = [len(t.versamenti) - 1]
            v = tr.balancing_amount(self.arc, t, idx[0])
            self.to_amt[k].set_value(round_to(v, self.arc.decimals))
        except (ValueError, ArchiveError) as e:
            error(self, e)

    def accept(self):
        try:
            t = self._build()
            check = None
            if t.id is not None and abs(tr.imbalance(self.arc, t)) >= Decimal("0.005"):
                check = not ask(self, "Il giroconto risulta sbilanciato, forse per un cambio variato dopo la sua "
                                      "creazione. Salvarlo comunque senza ricalcolarlo?")
            tr.save(self.arc, t, check_balance=check)
        except (ValueError, ArchiveError) as e:
            error(self, e)
            return
        super().accept()


class TransfersManager(QDialog):
    def __init__(self, arc: Archive, year: int, month: int, parent=None):
        super().__init__(parent)
        self.arc, self.year, self.month = arc, year, month
        self.setWindowTitle(f"Giroconti di {month_label(year, month)}")
        self.resize(720, 360)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Data", "Prelievo", "Versamenti", "S", "Descrizione"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self._edit)
        row = QHBoxLayout()
        for text, fn in (("&Nuovo", self._new), ("&Modifica", self._edit), ("&Elimina", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.accept)
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        lay.addLayout(row)
        self._reload()

    def _reload(self):
        self.items = tr.list_month(self.arc, self.year, self.month)
        self.table.setRowCount(len(self.items))
        dec = self.arc.decimals
        for r, t in enumerate(self.items):
            vals = [t.data.strftime("%d/%m/%Y"),
                    f"{self.arc.name_of('risorse', t.prelievo.risorsa_id)} {fmt_amount(t.prelievo.importo, dec)}",
                    "; ".join(f"{self.arc.name_of('risorse', v.risorsa_id)} {fmt_amount(v.importo, dec)}"
                              for v in t.versamenti),
                    "*" if t.saldato else "", t.descrizione]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()

    def _selected(self) -> tr.Transfer | None:
        r = self.table.currentRow()
        return self.items[r] if 0 <= r < len(self.items) else None

    def _new(self):
        if TransferDialog(self.arc, default_date=date(self.year, self.month, 1), parent=self).exec():
            self._reload()

    def _edit(self, *_):
        t = self._selected()
        if t and TransferDialog(self.arc, t, parent=self).exec():
            self._reload()

    def _delete(self):
        t = self._selected()
        if t and ask(self, "Eliminare il giroconto selezionato?"):
            tr.delete(self.arc, t.id)
            self._reload()


class CardChargeDialog(QDialog):
    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Addebito spese carta di credito")
        dec = arc.decimals
        self.carta = LookupCombo(allow_empty=False)
        self.carta.fill([(r["id"], r["nome"]) for r in arc.rows("risorse", "tipo = 'carta' AND in_uso = 1")])
        self.saldo = QLabel()
        self.banca = QLabel()
        self.data = DateEdit(tr.default_card_charge_date())
        self.importo = AmountEdit(dec, allow_negative=False)
        self.commissione = AmountEdit(dec, allow_negative=False)
        self.gruppo = LookupCombo()
        self.gruppo.fill([(i, t) for i, t in group_items(arc)])
        g = arc.find_by_name("gruppi", "Spese bancarie")
        if g:
            self.gruppo.set_value(g["id"])
        self.sotto = LookupCombo()
        self.gruppo.currentIndexChanged.connect(self._fill_sub)
        self.carta.currentIndexChanged.connect(self._update)
        form = QFormLayout()
        form.addRow("Carta di credito", self.carta)
        form.addRow("Spese da addebitare", self.saldo)
        form.addRow("Addebito sul conto", self.banca)
        form.addRow("Data addebito", self.data)
        form.addRow("Importo da addebitare", self.importo)
        form.addRow("Commissioni bancarie", self.commissione)
        form.addRow("Gruppo commissioni", self.gruppo)
        form.addRow("Sottogruppo commissioni", self.sotto)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(_buttons(self, "Addebita"))
        self._fill_sub()
        self._update()

    def _fill_sub(self):
        g = self.gruppo.value()
        self.sotto.fill(lookup_items(self.arc, "sottogruppi", "gruppo_id = ?", (g,)) if g else [])
        s = self.arc.find_by_name("sottogruppi", "Commissioni", gruppo_id=g) if g else None
        if s:
            self.sotto.set_value(s["id"])

    def _update(self):
        c = self.carta.value()
        if c is None:
            self.saldo.setText("nessuna carta di credito in tabella risorse")
            return
        owed = -tr.card_balance(self.arc, c)
        cur = self.arc.resource_currency(c)["sigla"]
        self.saldo.setText(f"{fmt_amount(owed, self.arc.decimals)} {cur}")
        self.banca.setText(self.arc.name_of("risorse", self.arc.row("risorse", c)["banca_id"]))
        self.importo.set_value(max(owed, ZERO))

    def accept(self):
        try:
            c = self.carta.value()
            if c is None:
                raise ValidationError("Scegliere una carta di credito")
            tr.charge_credit_card(self.arc, c, self.importo.value(), self.data.value(),
                                  self.commissione.value() if self.commissione.text().strip() else ZERO,
                                  self.gruppo.value(), self.sotto.value())
        except (ValueError, ArchiveError) as e:
            error(self, e)
            return
        super().accept()


# --- scadenzario ------------------------------------------------------------------
class ScheduleDialog(QDialog):
    """Elenco delle scadenze a sinistra, dettaglio e piano di sviluppo a destra."""

    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.current: sch.Schedule | None = None
        self.setWindowTitle("Scadenzario")
        self.resize(900, 560)
        dec = arc.decimals
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)

        self.descr = QLineEdit()
        self.descr.setMaxLength(mv.MAX_DESCRIZIONE)
        self.tipo_mov = QRadioButton("Movimento")
        self.tipo_giro = QRadioButton("Giroconto")
        tipo_box = QHBoxLayout()
        tipo_box.addWidget(self.tipo_mov)
        tipo_box.addWidget(self.tipo_giro)
        tipo_box.addStretch()
        self.risorsa = LookupCombo(allow_empty=False)
        self.importo = AmountEdit(dec)
        self.importo.setToolTip("Per i gruppi «entrata e uscita» un importo negativo è un'uscita")

        self.stack = QStackedWidget()
        p_mov = QWidget()
        f_mov = QFormLayout(p_mov)
        f_mov.setContentsMargins(0, 0, 0, 0)
        self.gruppo = LookupCombo(allow_empty=False)
        self.sotto = LookupCombo()
        self.modalita = LookupCombo()
        self.soggetto = LookupCombo()
        self.destinazione = LookupCombo()
        self.rif = QLineEdit()
        self.rif.setMaxLength(mv.MAX_RIF)
        for label, w in (("Gruppo", self.gruppo), ("Sottogruppo", self.sotto), ("Modalità", self.modalita),
                         ("Soggetto", self.soggetto), ("Destinazione", self.destinazione), ("Rif", self.rif)):
            f_mov.addRow(label, w)
        p_giro = QWidget()
        f_giro = QFormLayout(p_giro)
        f_giro.setContentsMargins(0, 0, 0, 0)
        self.dest = LookupCombo(allow_empty=False)
        self.importo_dest = AmountEdit(dec, allow_negative=False)
        self.importo_dest.setPlaceholderText("vuoto = calcolato col cambio")
        f_giro.addRow("Versamento in", self.dest)
        f_giro.addRow("Importo versato", self.importo_dest)
        self.stack.addWidget(p_mov)
        self.stack.addWidget(p_giro)
        self.tipo_mov.toggled.connect(lambda on: self.stack.setCurrentIndex(0 if on else 1))
        self.gruppo.currentIndexChanged.connect(self._fill_sub)
        self.risorsa.currentIndexChanged.connect(self._fill_mod)

        # piano di sviluppo
        self.start = DateEdit()
        self.end_by_date = QRadioButton("fino al")
        self.end_by_count = QRadioButton("per n. volte")
        self.end = DateEdit()
        self.count = QSpinBox()
        self.count.setRange(1, 9999)
        self.step = QSpinBox()
        self.step.setRange(1, 999)
        self.unit = QComboBox()
        for k, v in (("G", "giorni"), ("S", "settimane"), ("M", "mesi")):
            self.unit.addItem(v, k)
        self.weekday = QComboBox()
        for i, g in enumerate(GIORNI):
            self.weekday.addItem(g, i)
        self.m_day = QRadioButton("il giorno")
        self.m_last = QRadioButton("l'ultimo giorno")
        self.m_nth = QRadioButton("il")
        self.monthday = QSpinBox()
        self.monthday.setRange(1, 31)
        self.ordinal = QComboBox()
        for k, v in ORDINALI.items():
            self.ordinal.addItem(v, k)
        self.m_weekday = QComboBox()
        for i, g in enumerate(GIORNI):
            self.m_weekday.addItem(g, i)
        grp_month = QButtonGroup(self)
        for b in (self.m_day, self.m_last, self.m_nth):
            grp_month.addButton(b)
        grp_tipo = QButtonGroup(self)
        grp_tipo.addButton(self.tipo_mov)
        grp_tipo.addButton(self.tipo_giro)
        grp_end = QButtonGroup(self)
        grp_end.addButton(self.end_by_date)
        grp_end.addButton(self.end_by_count)

        plan = QGridLayout()
        plan.addWidget(QLabel("dal"), 0, 0)
        plan.addWidget(self.start, 0, 1)
        plan.addWidget(self.end_by_date, 1, 0)
        plan.addWidget(self.end, 1, 1)
        plan.addWidget(self.end_by_count, 2, 0)
        plan.addWidget(self.count, 2, 1)
        plan.addWidget(QLabel("ogni"), 3, 0)
        every = QHBoxLayout()
        every.addWidget(self.step)
        every.addWidget(self.unit)
        plan.addLayout(every, 3, 1)
        self.week_row = QWidget()
        wr = QHBoxLayout(self.week_row)
        wr.setContentsMargins(0, 0, 0, 0)
        wr.addWidget(QLabel("di"))
        wr.addWidget(self.weekday)
        wr.addStretch()
        plan.addWidget(self.week_row, 4, 0, 1, 2)
        self.month_row = QWidget()
        mr = QGridLayout(self.month_row)
        mr.setContentsMargins(0, 0, 0, 0)
        mr.addWidget(self.m_day, 0, 0)
        mr.addWidget(self.monthday, 0, 1)
        mr.addWidget(self.m_last, 1, 0)
        mr.addWidget(self.m_nth, 2, 0)
        nth = QHBoxLayout()
        nth.addWidget(self.ordinal)
        nth.addWidget(self.m_weekday)
        nth.addWidget(QLabel("del mese"))
        mr.addLayout(nth, 2, 1)
        plan.addWidget(self.month_row, 5, 0, 1, 2)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        plan.addWidget(self.preview, 6, 0, 1, 2)
        for w in (self.unit, self.ordinal, self.m_weekday, self.weekday):
            w.currentIndexChanged.connect(self._update_plan)
        for w in (self.step, self.count, self.monthday):
            w.valueChanged.connect(self._update_plan)
        for w in (self.start, self.end):
            w.dateChanged.connect(self._update_plan)
        for w in (self.end_by_date, self.end_by_count, self.m_day, self.m_last, self.m_nth):
            w.toggled.connect(self._update_plan)

        form = QFormLayout()
        form.addRow("Descrizione", self.descr)
        form.addRow("Tipo", tipo_box)
        form.addRow("Risorsa", self.risorsa)
        form.addRow("Importo", self.importo)
        detail = QVBoxLayout()
        detail.addLayout(form)
        detail.addWidget(self.stack)
        box = QGroupBox("Piano di sviluppo")
        box.setLayout(plan)
        detail.addWidget(box)
        note = QLabel("I movimenti vengono creati non saldati. Modificando o eliminando la scadenza "
                      "cambiano solo quelli non ancora saldati.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #666")
        detail.addWidget(note)

        buttons = QHBoxLayout()
        for text, fn in (("&Crea nuova", self._new), ("&Salva e genera", self._save), ("&Elimina", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        buttons.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.accept)
        buttons.addWidget(close)
        body = QHBoxLayout()
        body.addWidget(self.list, 2)
        body.addLayout(detail, 3)
        lay = QVBoxLayout(self)
        lay.addLayout(body)
        lay.addLayout(buttons)
        self._fill_lookups()
        self._reload()

    def _fill_lookups(self):
        res = _resource_items(self.arc)
        self.risorsa.fill(res)
        self.dest.fill(res)
        self.gruppo.fill(group_items(self.arc))
        self.soggetto.fill(lookup_items(self.arc, "soggetti"))
        self.destinazione.fill(lookup_items(self.arc, "destinazioni"))

    def _fill_sub(self):
        g = self.gruppo.value()
        self.sotto.fill(lookup_items(self.arc, "sottogruppi", "gruppo_id = ?", (g,)) if g else [])

    def _fill_mod(self):
        r = self.risorsa.value()
        self.modalita.fill(lookup_items(self.arc, "modalita", "risorsa_id = ?", (r,)) if r else [])

    def _reload(self, select: int | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        for s in sch.list_all(self.arc):
            it = QListWidgetItem(s.descrizione or "(senza descrizione)")
            it.setData(Qt.ItemDataRole.UserRole, s.id)
            it.setToolTip(describe(s.plan))
            self.list.addItem(it)
            if s.id == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None:
            if self.list.count():
                self.list.setCurrentRow(0)
            else:
                self._new()
                return
        self._on_select(self.list.currentItem())

    def _on_select(self, item, _prev=None):
        s = sch.get(self.arc, item.data(Qt.ItemDataRole.UserRole)) if item else None
        self.current = s
        s = s or sch.Schedule("", self.risorsa.itemData(0) or 0, Plan(date.today(), "M", count=12))
        self.descr.setText(s.descrizione)
        (self.tipo_mov if s.tipo == "M" else self.tipo_giro).setChecked(True)
        self.stack.setCurrentIndex(0 if s.tipo == "M" else 1)
        self.risorsa.set_value(s.risorsa_id)
        self._fill_mod()
        self.importo.set_value(s.importo if self.current else None)
        self.gruppo.set_value(s.gruppo_id)
        self._fill_sub()
        self.sotto.set_value(s.sottogruppo_id)
        self.modalita.set_value(s.modalita_id)
        self.soggetto.set_value(s.soggetto_id)
        self.destinazione.set_value(s.destinazione_id)
        self.rif.setText(s.rif)
        self.dest.set_value(s.risorsa_dest_id)
        self.importo_dest.set_value(s.importo_dest if s.importo_dest else None)
        p = s.plan
        self.start.set_date(p.start)
        self.end_by_date.setChecked(p.end is not None)
        self.end_by_count.setChecked(p.end is None)
        self.end.set_date(p.end or p.start)
        self.count.setValue(p.count or 12)
        self.step.setValue(p.step)
        self.unit.setCurrentIndex(self.unit.findData(p.unit))
        self.weekday.setCurrentIndex(p.weekday if p.weekday is not None else p.start.weekday())
        self.m_nth.setChecked(p.ordinal is not None)
        self.m_last.setChecked(p.ordinal is None and p.monthday == -1)
        self.m_day.setChecked(p.ordinal is None and p.monthday != -1)
        self.monthday.setValue(p.monthday if p.monthday and p.monthday > 0 else p.start.day)
        self.ordinal.setCurrentIndex(max(0, self.ordinal.findData(p.ordinal or 1)))
        self.m_weekday.setCurrentIndex(p.weekday if p.weekday is not None else p.start.weekday())
        self._update_plan()

    def _plan(self) -> Plan:
        unit = self.unit.currentData()
        p = Plan(start=self.start.value(), unit=unit, step=self.step.value(),
                 end=self.end.value() if self.end_by_date.isChecked() else None,
                 count=self.count.value() if self.end_by_count.isChecked() else None)
        if unit == "S":
            p.weekday = self.weekday.currentData()
        elif unit == "M":
            if self.m_nth.isChecked():
                p.ordinal, p.weekday = self.ordinal.currentData(), self.m_weekday.currentData()
            elif self.m_last.isChecked():
                p.monthday = -1
            else:
                p.monthday = self.monthday.value()
        return p

    def _update_plan(self):
        unit = self.unit.currentData()
        self.week_row.setVisible(unit == "S")
        self.month_row.setVisible(unit == "M")
        self.end.setEnabled(self.end_by_date.isChecked())
        self.count.setEnabled(self.end_by_count.isChecked())
        try:
            p = self._plan()
            occ = occurrences(p)
            first = occ[0].strftime("%d/%m/%Y") if occ else "—"
            last = occ[-1].strftime("%d/%m/%Y") if occ else "—"
            self.preview.setText(f"{describe(p)}\n→ {len(occ)} date, dal {first} al {last}")
        except ValueError as e:
            self.preview.setText(str(e))

    def _new(self):
        self.list.setCurrentItem(None)
        self._on_select(None)
        self.descr.setFocus()

    def _save(self):
        try:
            tipo = "M" if self.tipo_mov.isChecked() else "G"
            s = sch.Schedule(
                descrizione=self.descr.text().strip(), risorsa_id=self.risorsa.value(), plan=self._plan(), tipo=tipo,
                gruppo_id=self.gruppo.value() if tipo == "M" else None,
                sottogruppo_id=self.sotto.value() if tipo == "M" else None,
                importo=self.importo.value(), modalita_id=self.modalita.value() if tipo == "M" else None,
                destinazione_id=self.destinazione.value() if tipo == "M" else None,
                soggetto_id=self.soggetto.value() if tipo == "M" else None, rif=self.rif.text().strip(),
                risorsa_dest_id=self.dest.value() if tipo == "G" else None,
                importo_dest=self.importo_dest.value() if tipo == "G" and self.importo_dest.text().strip() else ZERO,
                id=self.current.id if self.current else None)
            if s.risorsa_id is None:
                raise ValidationError("La risorsa è obbligatoria")
            n = len(occurrences(s.plan))
            if n > 500 and not ask(self, f"La scadenza genera {n} movimenti. Continuare?"):
                return
            sid = sch.save(self.arc, s)
        except (ValueError, ArchiveError) as e:
            error(self, e)
            return
        self._reload(sid)

    def _delete(self):
        if self.current and ask(self, "Eliminare la scadenza? Verranno cancellati i suoi movimenti non ancora "
                                      "saldati; quelli saldati restano."):
            sch.delete(self.arc, self.current.id)
            self.current = None
            self._reload()


# --- ricerca e spostamento -----------------------------------------------------------
class FindDialog(QDialog):
    MODES = (("tutti", "In tutti i campi"), ("descrizioni", "Nelle descrizioni e nei riferimenti"),
             ("importi", "Negli importi"), ("non_saldato", "Primo movimento non saldato"))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trova")
        self.text = QLineEdit()
        self.mode = QComboBox()
        for k, v in self.MODES:
            self.mode.addItem(v, k)
        self.mode.currentIndexChanged.connect(lambda: self.text.setEnabled(self.mode.currentData() != "non_saldato"))
        self.all_res = QCheckBox("In tutte le risorse")
        form = QFormLayout()
        form.addRow("Cerca", self.text)
        form.addRow("Dove", self.mode)
        form.addRow("", self.all_res)
        self.status = QLabel()
        self.prev_btn = QPushButton("< Precedente")
        self.next_btn = QPushButton("Successivo >")
        self.next_btn.setDefault(True)
        row = QHBoxLayout()
        row.addWidget(self.prev_btn)
        row.addWidget(self.next_btn)
        close = QPushButton("Chiudi")
        close.clicked.connect(self.reject)
        row.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.status)
        lay.addLayout(row)


class MoveDateDialog(QDialog):
    def __init__(self, current: date, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sposta movimento in altra data")
        self.date = DateEdit(current)
        form = QFormLayout(self)
        form.addRow("Nuova data", self.date)
        form.addRow(_buttons(self))


# --- impostazioni e colonne ----------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.setWindowTitle("Impostazioni dell'archivio")
        self.decimals = QSpinBox()
        self.decimals.setRange(0, 4)
        self.decimals.setValue(arc.decimals)
        self.principal = LookupCombo(allow_empty=False)
        self.principal.fill([(r["id"], f"{r['sigla']} – {r['nome']}") for r in arc.rows("valute")],
                            arc.principal()["id"])
        self.settle = QCheckBox("Salda subito i nuovi movimenti")
        self.settle.setChecked(arc.setting("salda_subito") == "1")
        self.open_month = QComboBox()
        self.open_month.addItem("Mese corrente", "corrente")
        self.open_month.addItem("Mese dell'ultimo movimento saldato", "ultimo_saldato")
        self.open_month.setCurrentIndex(max(0, self.open_month.findData(arc.setting("mese_apertura"))))
        self.backup = QCheckBox("Copia di sicurezza automatica alla chiusura dell'archivio")
        self.backup.setChecked(arc.setting("copia_alla_chiusura") == "1")
        from ..tools import START_SECTIONS
        from .start_page import sections
        self.msg1 = QLineEdit(arc.setting("avvio_msg1", "") or "")
        self.msg2 = QLineEdit(arc.setting("avvio_msg2", "") or "")
        self.msg1.setPlaceholderText("Benvenuto in … (nome dell'archivio)")
        self.sec_checks = {}
        sec_box = QVBoxLayout()
        for k, v in START_SECTIONS.items():
            cb = QCheckBox(v)
            cb.setChecked(k in sections(arc))
            self.sec_checks[k] = cb
            sec_box.addWidget(cb)
        self.start_show = QComboBox()
        self.start_show.addItem("La pagina d'avvio", "pagina")
        self.start_show.addItem("Subito l'elenco dei movimenti", "movimenti")
        self.start_show.setCurrentIndex(max(0, self.start_show.findData(arc.setting("avvio_mostra", "pagina"))))
        form = QFormLayout(self)
        form.addRow("Cifre decimali degli importi", self.decimals)
        form.addRow("Valuta principale", self.principal)
        form.addRow("", self.settle)
        form.addRow("All'apertura mostra", self.open_month)
        form.addRow("", self.backup)
        form.addRow(QLabel("<b>Pagina d'avvio</b>"))
        form.addRow("Messaggio di benvenuto", self.msg1)
        form.addRow("Seconda riga", self.msg2)
        form.addRow("Sezioni da mostrare", sec_box)
        form.addRow("All'apertura dell'archivio mostra", self.start_show)
        form.addRow(_buttons(self))

    def accept(self):
        a = self.arc
        a.set_setting("decimali", str(self.decimals.value()))
        a.set_setting("salda_subito", "1" if self.settle.isChecked() else "0")
        a.set_setting("mese_apertura", self.open_month.currentData())
        a.set_setting("copia_alla_chiusura", "1" if self.backup.isChecked() else "0")
        a.set_setting("avvio_msg1", self.msg1.text().strip())
        a.set_setting("avvio_msg2", self.msg2.text().strip())
        a.set_setting("avvio_sezioni", ",".join(k for k, cb in self.sec_checks.items() if cb.isChecked()))
        a.set_setting("avvio_mostra", self.start_show.currentData())
        p = self.principal.value()
        if p is not None and p != a.principal()["id"] and ask(
                self, "Cambiare la valuta principale? I cambi e i budget verranno ricalcolati."):
            a.set_principal(p)
        super().accept()


class ColumnsDialog(QDialog):
    """Colonne facoltative visibili (a sinistra, nell'ordine) e nascoste (a destra)."""

    def __init__(self, visible: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurazione colonne")
        self.shown = QListWidget()
        self.hidden = QListWidget()
        for k in visible:
            self._add(self.shown, k)
        for k in OPTIONAL_COLUMNS:
            if k not in visible:
                self._add(self.hidden, k)
        mid = QVBoxLayout()
        for text, fn in (("→", self._hide), ("←", self._show), ("↑", lambda: self._move(-1)),
                         ("↓", lambda: self._move(1))):
            b = QPushButton(text)
            b.setFixedWidth(36)
            b.clicked.connect(fn)
            mid.addWidget(b)
        mid.addStretch()
        lists = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Visibili"))
        left.addWidget(self.shown)
        right = QVBoxLayout()
        right.addWidget(QLabel("Nascoste"))
        right.addWidget(self.hidden)
        lists.addLayout(left)
        lists.addLayout(mid)
        lists.addLayout(right)
        lay = QVBoxLayout(self)
        lay.addLayout(lists)
        lay.addWidget(_buttons(self))

    @staticmethod
    def _add(lst: QListWidget, key: str, row: int | None = None):
        it = QListWidgetItem(COLUMN_INFO[key][0])
        it.setData(Qt.ItemDataRole.UserRole, key)
        lst.insertItem(lst.count() if row is None else row, it)

    def _transfer(self, a: QListWidget, b: QListWidget):
        it = a.currentItem()
        if it:
            self._add(b, it.data(Qt.ItemDataRole.UserRole))
            a.takeItem(a.row(it))

    def _hide(self):
        self._transfer(self.shown, self.hidden)

    def _show(self):
        self._transfer(self.hidden, self.shown)

    def _move(self, d: int):
        r = self.shown.currentRow()
        if r < 0 or not 0 <= r + d < self.shown.count():
            return
        it = self.shown.takeItem(r)
        self.shown.insertItem(r + d, it)
        self.shown.setCurrentRow(r + d)

    def visible(self) -> list[str]:
        return [self.shown.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.shown.count())]


# --- analisi rapide ----------------------------------------------------------------
class ReportTable(QTableWidget):
    """Tabella di sola lettura per i prospetti; ricorda intestazioni e righe per l'esportazione."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.headers: list[str] = []
        self.data_rows: list[list[str]] = []
        self.right_cols: tuple = ()
        self.bold_rows: tuple = ()

    def fill(self, headers: list[str], rows: list[list[str]], right_cols=(), bold_rows=(), shaded_rows=()):
        self.headers, self.data_rows = headers, rows
        self.right_cols, self.bold_rows = tuple(right_cols), tuple(bold_rows)
        self.clear()
        self.setColumnCount(len(headers))
        self.setRowCount(len(rows))
        self.setHorizontalHeaderLabels(headers)
        bold = QFont()
        bold.setBold(True)
        shade = shade_color(self)
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                it = QTableWidgetItem(v)
                if c in right_cols:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if r in bold_rows:
                    it.setFont(bold)
                if r in shaded_rows:
                    it.setBackground(shade)
                self.setItem(r, c, it)
        self.resizeColumnsToContents()
        self.horizontalHeader().setStretchLastSection(True)


def export_report(parent, title: str, table: ReportTable, note: str = ""):
    from ..interop.tabular import export_table_xlsx
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in title)[:60].strip()
    path, _ = QFileDialog.getSaveFileName(parent, "Esporta in Excel", safe + ".xlsx", "Excel (*.xlsx)")
    if path:
        try:
            export_table_xlsx(path, title, table.headers, table.data_rows, note)
        except OSError as e:
            error(parent, f"Impossibile salvare il file: {e}")


def print_report(parent, title: str, table: ReportTable, note: str = ""):
    from .printing import print_table
    key = "prospetto_" + "".join(ch for ch in title.split("–")[0].lower() if ch.isalnum())[:30]
    print_table(parent, title, table.headers, table.data_rows, key, table.right_cols, table.bold_rows, note,
                landscape=len(table.headers) > 7)


class TableReport(QDialog):
    """Prospetto di sola lettura (righe già formattate), con grafico facoltativo ed esportazione Excel."""

    def __init__(self, title: str, headers: list[str], rows: list[list[str]], right_cols=(), parent=None,
                 note: str = "", chart=None, bold_rows=(), shaded_rows=()):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900 if chart is not None else 680, 560)
        self.title, self.note = title, note
        self.table = ReportTable()
        self.table.fill(headers, rows, right_cols, bold_rows, shaded_rows)
        lay = QVBoxLayout(self)
        if note:
            lab = QLabel(note)
            lab.setWordWrap(True)
            lay.addWidget(lab)
        if chart is not None:
            split = QSplitter(Qt.Orientation.Vertical)
            split.addWidget(chart)
            split.addWidget(self.table)
            split.setSizes([300, 240])
            lay.addWidget(split)
        else:
            lay.addWidget(self.table)
        row = QHBoxLayout()
        exp = QPushButton("Esporta in &Excel…")
        exp.clicked.connect(lambda: export_report(self, self.title, self.table, self.note))
        row.addWidget(exp)
        prn = QPushButton("&Stampa…")
        prn.clicked.connect(lambda: print_report(self, self.title, self.table, self.note))
        row.addWidget(prn)
        row.addStretch()
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        b.rejected.connect(self.reject)
        row.addWidget(b)
        lay.addLayout(row)


def current_balances_report(arc: Archive, parent=None) -> TableReport:
    dec = arc.decimals
    p = arc.principal()["sigla"]
    data = bal.current_balances(arc)
    rows = [[d["risorsa"], d["valuta"], fmt_amount(d["disponibilita"], dec), fmt_amount(d["in_principale"], dec)]
            for d in data]
    rows.append(["Totale", p, "", fmt_amount(sum((d["in_principale"] for d in data), ZERO), dec)])
    ch = Chart(f"Disponibilità per risorsa ({p})", dec)
    ch.bars([d["risorsa"] for d in data], [d["in_principale"] for d in data], horizontal=True)
    return TableReport("Disponibilità correnti", ["Risorsa", "Valuta", "Disponibilità", f"In {p}"], rows, (2, 3),
                       parent, note=f"Movimenti saldati fino a oggi ({date.today():%d/%m/%Y}).", chart=ch,
                       bold_rows=(len(rows) - 1,))


def daily_report(arc: Archive, year: int, month: int, risorsa_id: int | None, parent=None) -> TableReport:
    dec = arc.decimals
    data = bal.daily(arc, year, month, risorsa_id)
    rows = [[f"{GIORNI_BREVI[d['data'].weekday()]} {d['data']:%d/%m}", fmt_amount(d["entrate"], dec, True),
             fmt_amount(d["uscite"], dec, True), fmt_amount(d["disponibilita"], dec)] for d in data]
    who = arc.name_of("risorse", risorsa_id) if risorsa_id else "tutte le risorse"
    ch = Chart("Disponibilità a fine giornata", dec)
    ch.line([str(d["data"].day) for d in data], [d["disponibilita"] for d in data])
    return TableReport(f"Disponibilità giornaliere – {month_label(year, month)} – {who}",
                       ["Giorno", "Entrate", "Uscite", "Disponibilità"], rows, (1, 2, 3), parent, chart=ch)


def trend_report(arc: Archive, year: int, month: int, risorsa_id: int | None, projection: bool,
                 parent=None) -> TableReport:
    dec = arc.decimals
    data = bal.trend(arc, risorsa_id, year, month, 12, projection)
    rows = [[month_label(d["anno"], d["mese"]), fmt_amount(d["entrate"], dec), fmt_amount(d["uscite"], dec),
             fmt_amount(d["differenza"], dec), fmt_amount(d["disponibilita"], dec)] for d in data]
    who = arc.name_of("risorse", risorsa_id) if risorsa_id else "tutte le risorse"
    kind = "Proiezione" if projection else "Andamento"
    return TableReport(f"{kind} disponibilità – 12 mesi da {month_label(year, month)} – {who}",
                       ["Mese", "Entrate", "Uscite", "Differenza", "Disponibilità a fine mese"], rows, (1, 2, 3, 4),
                       parent, note="La proiezione include i movimenti non ancora saldati." if projection else
                       "Solo movimenti saldati.", chart=trend_chart(data, dec))


def unsettled_report(arc: Archive, year: int, month: int, risorsa_id: int | None, parent=None) -> TableReport:
    dec = arc.decimals
    rows = []
    for m in sch.unsettled_in_month(arc, year, month, risorsa_id):
        rows.append([m.data.strftime("%d/%m/%Y"), "‹giroconto›" if m.is_transfer else arc.name_of("gruppi", m.gruppo_id),
                     arc.name_of("risorse", m.risorsa_id), fmt_amount(m.entrata, dec, True),
                     fmt_amount(m.uscita, dec, True), m.descrizione])
    return TableReport(f"Scadenze di {month_label(year, month)}",
                       ["Data", "Gruppo", "Risorsa", "Entrate", "Uscite", "Descrizione"], rows, (3, 4), parent,
                       note="Movimenti del mese non ancora saldati.")


def trend_chart(data: list[dict], decimals: int) -> Chart:
    first, last = data[0], data[-1]
    ch = Chart(f"Disponibilità a fine mese, {MESI[first['mese'] - 1]} {first['anno']} – "
               f"{MESI[last['mese'] - 1]} {last['anno']}", decimals)
    ch.line([MESI[d["mese"] - 1][:3] for d in data], [d["disponibilita"] for d in data])
    return ch
