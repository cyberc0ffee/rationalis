"""Pannello dei filtri sui movimenti, riusato da elenco filtrato, riepiloghi e monitor."""
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from ..analysis import Filter
from ..db import Archive
from .common import DateEdit, LookupCombo


class CheckListDialog(QDialog):
    def __init__(self, title: str, items: list[tuple[int, str]], selected: list[int] | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(360, 420)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Cerca…")
        self.search.textChanged.connect(self._filter)
        self.list = QListWidget()
        sel = set(selected or [])
        for id_, text in items:
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, id_)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if id_ in sel else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        row = QHBoxLayout()
        for text, state in (("Tutti", Qt.CheckState.Checked), ("Nessuno", Qt.CheckState.Unchecked)):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, st=state: self._set_all(st))
            row.addWidget(b)
        row.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.list)
        lay.addLayout(row)
        lay.addWidget(bb)

    def _filter(self, text: str):
        t = text.lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def _set_all(self, state):
        for i in range(self.list.count()):
            if not self.list.item(i).isHidden():
                self.list.item(i).setCheckState(state)

    def selected(self) -> list[int]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


class MultiPick(QWidget):
    """Casella «filtra per …» con scelta multipla delle voci."""

    def __init__(self, title: str, items_fn, parent=None):
        super().__init__(parent)
        self.title = title
        self.items_fn = items_fn
        self.ids: list[int] = []
        self.check = QCheckBox(title)
        self.btn = QPushButton("Scegli…")
        self.lbl = QLabel()
        self.lbl.setStyleSheet("color: palette(placeholder-text)")
        self.btn.clicked.connect(self._pick)
        self.check.toggled.connect(self._update)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.check)
        lay.addWidget(self.btn)
        lay.addWidget(self.lbl, 1)
        self._update()

    def _pick(self):
        dlg = CheckListDialog(self.title, self.items_fn(), self.ids, self)
        if dlg.exec():
            self.ids = dlg.selected()
            self.check.setChecked(True)
            self._update()

    def _update(self):
        self.btn.setEnabled(self.check.isChecked())
        if not self.check.isChecked():
            self.lbl.setText("")
            return
        names = dict(self.items_fn())
        chosen = [names.get(i, "?") for i in self.ids]
        self.lbl.setText("nessuna voce scelta" if not chosen else ", ".join(chosen[:3]) +
                         (f" e altre {len(chosen) - 3}" if len(chosen) > 3 else ""))

    def value(self) -> list[int] | None:
        return list(self.ids) if self.check.isChecked() else None

    def set_value(self, ids: list[int] | None):
        self.ids = list(ids or [])
        self.check.setChecked(ids is not None)
        self._update()


class FilterWidget(QWidget):
    def __init__(self, arc: Archive, with_dates: bool = True, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.with_dates = with_dates
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        row = 0
        if with_dates:
            self.use_from, self.use_to = QCheckBox("Dal"), QCheckBox("Al")
            y = date.today().year
            self.d_from, self.d_to = DateEdit(date(y, 1, 1)), DateEdit(date(y, 12, 31))
            self.use_from.setChecked(True)
            self.use_to.setChecked(True)
            dates = QHBoxLayout()
            for w in (self.use_from, self.d_from, self.use_to, self.d_to):
                dates.addWidget(w)
            dates.addStretch()
            g.addLayout(dates, row, 0, 1, 2)
            row += 1
        self.saldato = QComboBox()
        for k, v in (("saldati", "Solo saldati"), ("non_saldati", "Solo non saldati"), ("tutti", "Saldati e non")):
            self.saldato.addItem(v, k)
        self.tipo = QComboBox()
        for k, v in (("tutti", "Entrate e uscite"), ("entrate", "Solo entrate"), ("uscite", "Solo uscite")):
            self.tipo.addItem(v, k)
        sel = QHBoxLayout()
        sel.addWidget(self.saldato)
        sel.addWidget(self.tipo)
        sel.addStretch()
        g.addLayout(sel, row, 0, 1, 2)
        row += 1

        def items(table, label=None):
            return lambda: [(r["id"], label(r) if label else r["nome"]) for r in arc.rows(table)]

        def sub_label(r):
            return f"{arc.name_of('gruppi', r['gruppo_id'])} / {r['nome']}"

        def mod_label(r):
            return f"{arc.name_of('risorse', r['risorsa_id'])} / {r['nome']}"

        self.gruppi = MultiPick("Gruppi", items("gruppi"))
        self.sottogruppi = MultiPick("Sottogruppi", lambda: sorted(
            [(r["id"], sub_label(r)) for r in arc.rows("sottogruppi")], key=lambda x: x[1].lower()))
        self.use_ragg = QCheckBox("Raggruppamento")
        self.ragg = LookupCombo(allow_empty=False)
        self.ragg.fill([(r["id"], r["nome"]) for r in arc.rows("raggruppamenti")])
        self.ragg.setEnabled(False)
        self.use_ragg.toggled.connect(self._ragg_toggled)
        self.gruppi.check.toggled.connect(lambda on: on and self.use_ragg.setChecked(False))
        self.sottogruppi.check.toggled.connect(lambda on: on and self.use_ragg.setChecked(False))
        self.risorse = MultiPick("Risorse", items("risorse"))
        self.destinazioni = MultiPick("Destinazioni", items("destinazioni"))
        self.soggetti = MultiPick("Soggetti", items("soggetti"))
        self.modalita = MultiPick("Modalità", lambda: sorted(
            [(r["id"], mod_label(r)) for r in arc.rows("modalita")], key=lambda x: x[1].lower()))
        for w in (self.gruppi, self.sottogruppi):
            g.addWidget(w, row, 0, 1, 2)
            row += 1
        rg = QHBoxLayout()
        rg.addWidget(self.use_ragg)
        rg.addWidget(self.ragg, 1)
        g.addLayout(rg, row, 0, 1, 2)
        row += 1
        for w in (self.risorse, self.destinazioni, self.soggetti, self.modalita):
            g.addWidget(w, row, 0, 1, 2)
            row += 1
        self.descr = QLineEdit()
        self.descr.setPlaceholderText("contiene…")
        self.rif = QLineEdit()
        self.rif.setPlaceholderText("contiene…")
        self.ctrl = QLineEdit()
        self.ctrl.setMaxLength(1)
        self.ctrl.setFixedWidth(40)
        txt = QHBoxLayout()
        for lbl, w in (("Descrizione", self.descr), ("Rif", self.rif), ("C", self.ctrl)):
            txt.addWidget(QLabel(lbl))
            txt.addWidget(w)
        g.addLayout(txt, row, 0, 1, 2)

    def _ragg_toggled(self, on: bool):
        self.ragg.setEnabled(on)
        if on:
            self.gruppi.set_value(None)
            self.sottogruppi.set_value(None)

    def value(self) -> Filter:
        f = Filter(
            saldato=self.saldato.currentData(), tipo=self.tipo.currentData(),
            gruppi=self.gruppi.value(), sottogruppi=self.sottogruppi.value(),
            raggruppamento_id=self.ragg.value() if self.use_ragg.isChecked() else None,
            risorse=self.risorse.value(), destinazioni=self.destinazioni.value(), soggetti=self.soggetti.value(),
            modalita=self.modalita.value(), descrizione=self.descr.text().strip(), rif=self.rif.text().strip(),
            controllo=self.ctrl.text().strip())
        if self.with_dates:
            f.data_da = self.d_from.value() if self.use_from.isChecked() else None
            f.data_a = self.d_to.value() if self.use_to.isChecked() else None
        return f

    def set_value(self, f: Filter):
        if self.with_dates:
            self.use_from.setChecked(f.data_da is not None)
            self.use_to.setChecked(f.data_a is not None)
            if f.data_da:
                self.d_from.set_date(f.data_da)
            if f.data_a:
                self.d_to.set_date(f.data_a)
        self.saldato.setCurrentIndex(max(0, self.saldato.findData(f.saldato)))
        self.tipo.setCurrentIndex(max(0, self.tipo.findData(f.tipo)))
        self.gruppi.set_value(f.gruppi)
        self.sottogruppi.set_value(f.sottogruppi)
        self.use_ragg.setChecked(f.raggruppamento_id is not None)
        if f.raggruppamento_id is not None:
            self.ragg.set_value(f.raggruppamento_id)
        self.risorse.set_value(f.risorse)
        self.destinazioni.set_value(f.destinazioni)
        self.soggetti.set_value(f.soggetti)
        self.modalita.set_value(f.modalita)
        self.descr.setText(f.descrizione)
        self.rif.setText(f.rif)
        self.ctrl.setText(f.controllo)
