"""Finestre dati: gestione delle tabelle con elenco a sinistra e dettaglio a destra."""
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from ..db import TIPI_RISORSA, Archive, ArchiveError, ValidationError
from ..money import from_db, parse_rate, to_db
from .common import AmountEdit, LookupCombo, ask, error

TIPI_GRUPPO = {"E": "Entrata (+)", "U": "Uscita (−)", "M": "Entrata e uscita (±)"}


@dataclass
class FieldSpec:
    name: str
    label: str
    kind: str = "text"            # text, choice, lookup, amount, rate, check
    maxlen: int = 0
    choices: dict = field(default_factory=dict)
    lookup: str = ""              # tabella per kind=lookup
    lookup_where: str = ""        # filtro SQL; ":id" = id della voce corrente


@dataclass
class TableSpec:
    table: str
    title: str
    fields: list[FieldSpec]
    child_table: str = ""
    child_fk: str = ""
    child_title: str = ""


SPECS = {
    "gruppi": TableSpec("gruppi", "Gruppi e sottogruppi", [
        FieldSpec("nome", "Nome", maxlen=60),
        FieldSpec("tipo", "Tipo", "choice", choices=TIPI_GRUPPO),
        FieldSpec("in_uso", "In uso", "check"),
    ], "sottogruppi", "gruppo_id", "Sottogruppi"),
    "risorse": TableSpec("risorse", "Risorse", [
        FieldSpec("nome", "Nome", maxlen=60),
        FieldSpec("tipo", "Tipo", "choice", choices=TIPI_RISORSA),
        FieldSpec("valuta_id", "Valuta", "lookup", lookup="valute"),
        FieldSpec("saldo_iniziale", "Saldo iniziale", "amount"),
        FieldSpec("limite_attivo", "Avvisa se fuori dai limiti", "check"),
        FieldSpec("limite_min", "Limite minimo", "amount"),
        FieldSpec("limite_max", "Limite massimo", "amount"),
        FieldSpec("banca_id", "Banca associata (carte)", "lookup", lookup="risorse",
                  lookup_where="tipo = 'banca' AND id <> :id"),
        FieldSpec("modalita_predef_id", "Modalità predefinita", "lookup", lookup="modalita",
                  lookup_where="risorsa_id = :id"),
        FieldSpec("in_uso", "In uso", "check"),
    ], "modalita", "risorsa_id", "Modalità di pagamento"),
    "valute": TableSpec("valute", "Valute", [
        FieldSpec("sigla", "Sigla (max 4)", maxlen=4),
        FieldSpec("nome", "Nome", maxlen=40),
        FieldSpec("cambio", "Cambio (unità per 1 della principale)", "rate"),
        FieldSpec("in_uso", "In uso", "check"),
    ]),
    "destinazioni": TableSpec("destinazioni", "Destinazioni", [
        FieldSpec("nome", "Nome", maxlen=60), FieldSpec("in_uso", "In uso", "check")]),
    "soggetti": TableSpec("soggetti", "Soggetti", [
        FieldSpec("nome", "Nome", maxlen=60), FieldSpec("in_uso", "In uso", "check")]),
    "descrizioni": TableSpec("descrizioni", "Descrizioni frequenti", [
        FieldSpec("nome", "Testo", maxlen=80), FieldSpec("in_uso", "In uso", "check")]),
}


class DataWindow(QDialog):
    def __init__(self, arc: Archive, table: str, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.spec = SPECS[table]
        self.current_id: int | None = None
        self.setWindowTitle(self.spec.title)
        self.resize(780, 480)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_select)
        self.widgets: dict[str, QWidget] = {}
        form = QFormLayout()
        for f in self.spec.fields:
            w = self._make_widget(f)
            self.widgets[f.name] = w
            form.addRow("" if f.kind == "check" else f.label, w)
        detail = QGroupBox("Dettaglio")
        dl = QVBoxLayout(detail)
        dl.addLayout(form)
        self.principal_btn = None
        if table == "valute":
            self.principal_btn = QPushButton("Imposta come valuta principale")
            self.principal_btn.clicked.connect(self._make_principal)
            dl.addWidget(self.principal_btn)
            self.principal_lbl = QLabel()
            dl.addWidget(self.principal_lbl)
        if self.spec.child_table:
            box = QGroupBox(self.spec.child_title)
            bl = QVBoxLayout(box)
            self.child_list = QListWidget()
            self.child_list.itemDoubleClicked.connect(lambda *_: self._child_rename())
            bl.addWidget(self.child_list)
            row = QHBoxLayout()
            for text, fn in (("Aggiungi", self._child_add), ("Rinomina", self._child_rename),
                             ("In uso sì/no", self._child_toggle), ("Elimina", self._child_delete)):
                b = QPushButton(text)
                b.clicked.connect(fn)
                row.addWidget(b)
            bl.addLayout(row)
            dl.addWidget(box)
        dl.addStretch()

        buttons = QHBoxLayout()
        for text, fn in (("&Crea nuovo", self._new), ("&Salva", self._save), ("&Elimina", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            buttons.addWidget(b)
        buttons.addStretch()
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)
        buttons.addWidget(close)

        body = QHBoxLayout()
        body.addWidget(self.list, 2)
        body.addWidget(detail, 3)
        lay = QVBoxLayout(self)
        lay.addLayout(body)
        lay.addLayout(buttons)
        self._reload()

    # --- costruzione -------------------------------------------------------
    def _make_widget(self, f: FieldSpec) -> QWidget:
        if f.kind == "text":
            w = QLineEdit()
            if f.maxlen:
                w.setMaxLength(f.maxlen)
            return w
        if f.kind == "choice":
            w = QComboBox()
            for k, v in f.choices.items():
                w.addItem(v, k)
            return w
        if f.kind == "lookup":
            return LookupCombo(allow_empty=f.name != "valuta_id")
        if f.kind == "amount":
            return AmountEdit(self.arc.decimals)
        if f.kind == "rate":
            return QLineEdit()
        return QCheckBox(f.label)

    def _fill_lookups(self, id_: int | None):
        for f in self.spec.fields:
            if f.kind != "lookup":
                continue
            where = f.lookup_where.replace(":id", str(id_ if id_ is not None else -1))
            rows = self.arc.rows(f.lookup, where)
            label = (lambda r: f"{r['sigla']} – {r['nome']}") if f.lookup == "valute" else (lambda r: r["nome"])
            self.widgets[f.name].fill([(r["id"], label(r)) for r in rows])

    def _reload(self, select: int | None = None):
        self.list.blockSignals(True)
        self.list.clear()
        order = "sigla COLLATE NOCASE" if self.spec.table == "valute" else "nome COLLATE NOCASE"
        for r in self.arc.rows(self.spec.table, order=order):
            text = r["sigla"] + (f"  ({r['nome']})" if r["nome"] else "") if self.spec.table == "valute" else r["nome"]
            if self.spec.table == "gruppi":
                text += {"E": "  +", "U": "  −", "M": "  ±"}[r["tipo"]]
            if self.spec.table == "valute" and r["principale"]:
                text += "  [principale]"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            if not r["in_uso"]:
                it.setForeground(QBrush(QColor("#999")))
            self.list.addItem(it)
            if r["id"] == select:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._on_select(self.list.currentItem())

    def _on_select(self, item, _prev=None):
        self.current_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        r = self.arc.row(self.spec.table, self.current_id) if self.current_id else None
        self._fill_lookups(self.current_id)
        for f in self.spec.fields:
            w = self.widgets[f.name]
            v = r[f.name] if r else None
            if f.kind == "text":
                w.setText(v or "")
            elif f.kind == "choice":
                w.setCurrentIndex(max(0, w.findData(v)))
            elif f.kind == "lookup":
                w.set_value(v if r else (self.arc.principal()["id"] if f.name == "valuta_id" else None))
            elif f.kind == "amount":
                w.set_value(from_db(v) if r else None)
            elif f.kind == "rate":
                w.setText((v or "1").replace(".", ","))
            else:
                w.setChecked(bool(v) if r else True)
        if self.principal_btn is not None:
            is_p = bool(r and r["principale"])
            self.widgets["cambio"].setEnabled(not is_p)
            self.principal_btn.setEnabled(bool(r) and not is_p)
            self.principal_lbl.setText(f"Valuta principale: {self.arc.principal()['sigla']}")
        self._reload_children()

    def _reload_children(self):
        if not self.spec.child_table:
            return
        self.child_list.clear()
        if self.current_id is None:
            return
        for r in self.arc.rows(self.spec.child_table, f"{self.spec.child_fk} = ?", (self.current_id,)):
            it = QListWidgetItem(r["nome"])
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            if not r["in_uso"]:
                it.setForeground(QBrush(QColor("#999")))
            self.child_list.addItem(it)

    # --- azioni ---------------------------------------------------------------
    def _new(self):
        self.list.clearSelection()
        self.list.setCurrentItem(None)
        self.current_id = None
        self._on_select(None)
        self.widgets[self.spec.fields[0].name].setFocus()

    def _values(self) -> dict:
        out = {}
        for f in self.spec.fields:
            w = self.widgets[f.name]
            if f.kind == "text":
                out[f.name] = w.text().strip()
            elif f.kind == "choice":
                out[f.name] = w.currentData()
            elif f.kind == "lookup":
                out[f.name] = w.value()
            elif f.kind == "amount":
                out[f.name] = to_db(w.value())
            elif f.kind == "rate":
                out[f.name] = str(parse_rate(w.text()))
            else:
                out[f.name] = int(w.isChecked())
        return out

    def _validate(self, v: dict):
        first = self.spec.fields[0].name
        if not v[first]:
            raise ValidationError(f"Il campo «{self.spec.fields[0].label}» è obbligatorio")
        t, i = self.spec.table, self.current_id
        if t == "gruppi" and i is not None:
            if v["tipo"] == "E" and self.arc.conn.execute(
                    "SELECT 1 FROM movimenti WHERE gruppo_id=? AND importo<0", (i,)).fetchone():
                raise ValidationError("Il gruppo ha già movimenti di uscita: può diventare solo «entrata e uscita»")
            if v["tipo"] == "U" and self.arc.conn.execute(
                    "SELECT 1 FROM movimenti WHERE gruppo_id=? AND importo>0", (i,)).fetchone():
                raise ValidationError("Il gruppo ha già movimenti di entrata: può diventare solo «entrata e uscita»")
        if t == "risorse":
            if v["valuta_id"] is None:
                raise ValidationError("La valuta è obbligatoria")
            if v["tipo"] == "carta" and v["banca_id"] is None:
                raise ValidationError("Una carta di credito richiede una banca associata (risorsa di tipo banca c/c)")
            if v["tipo"] != "carta":
                v["banca_id"] = None
            if v["limite_attivo"] and v["limite_min"] > v["limite_max"]:
                raise ValidationError("Il limite minimo supera il massimo")
            if i is not None:
                old = self.arc.row("risorse", i)
                if old["valuta_id"] != v["valuta_id"] and self.arc.usage_count("risorse", i) and not ask(
                        self, "La risorsa ha già movimenti: cambiando valuta gli importi esistenti verranno "
                              "interpretati nella nuova valuta. Continuare?"):
                    raise ValidationError("Modifica annullata")
        if t == "valute" and i is not None and self.arc.row("valute", i)["principale"]:
            v["cambio"] = "1"

    def _save(self):
        try:
            v = self._values()
            self._validate(v)
            with self.arc.tx():
                if self.current_id is None:
                    self.current_id = self.arc.insert(self.spec.table, **v)
                else:
                    self.arc.update(self.spec.table, self.current_id, **v)
        except (ArchiveError, ValueError) as e:
            error(self, e)
            return
        self._reload(self.current_id)

    def _delete(self):
        if self.current_id is None:
            return
        if not ask(self, "Eliminare la voce selezionata?"):
            return
        try:
            self.arc.delete(self.spec.table, self.current_id)
        except ArchiveError as e:
            error(self, e)
            return
        self._reload()

    def _make_principal(self):
        if self.current_id is None:
            return
        if ask(self, "Impostare questa valuta come principale? I cambi delle altre valute e i budget verranno "
                     "ricalcolati."):
            self.arc.set_principal(self.current_id)
            self._reload(self.current_id)

    # --- voci collegate (sottogruppi, modalità) ---------------------------------
    def _child_id(self) -> int | None:
        it = self.child_list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _child_add(self):
        if self.current_id is None:
            error(self, "Salvare prima la voce principale")
            return
        name, ok = QInputDialog.getText(self, self.spec.child_title, "Nome:")
        if ok and name.strip():
            self.arc.insert(self.spec.child_table, **{self.spec.child_fk: self.current_id, "nome": name.strip()})
            self._reload_children()
            self._fill_lookups(self.current_id)

    def _child_rename(self):
        cid = self._child_id()
        if cid is None:
            return
        old = self.arc.row(self.spec.child_table, cid)["nome"]
        name, ok = QInputDialog.getText(self, self.spec.child_title, "Nuovo nome:", text=old)
        if ok and name.strip():
            self.arc.update(self.spec.child_table, cid, nome=name.strip())
            self._reload_children()

    def _child_toggle(self):
        cid = self._child_id()
        if cid is not None:
            r = self.arc.row(self.spec.child_table, cid)
            self.arc.update(self.spec.child_table, cid, in_uso=int(not r["in_uso"]))
            self._reload_children()

    def _child_delete(self):
        cid = self._child_id()
        if cid is None or not ask(self, "Eliminare la voce selezionata?"):
            return
        try:
            self.arc.delete(self.spec.child_table, cid)
        except ArchiveError as e:
            error(self, e)
        self._reload_children()
