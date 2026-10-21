"""Griglia dei movimenti del mese: modello, editor delle celle e vista."""
import calendar
from dataclasses import replace
from datetime import date

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLineEdit, QSpinBox, QStyledItemDelegate, QTableView

from .. import movements as mv
from ..db import Archive, ArchiveError
from ..money import ZERO, fmt_amount, parse_amount
from ..ui_text import GIORNI_BREVI
from .common import LookupCombo, colors, error, group_items, is_dark, lookup_items

TRANSFER_LABEL = "‹giroconto›"
NEW_LABEL = "‹nuovo mov.›"

# chiave, intestazione, larghezza, configurabile
ALL_COLUMNS = [
    ("giorno", "Gio", 66, False),
    ("gruppo", "Gruppo", 170, False),
    ("sottogruppo", "Sottogruppo", 150, False),
    ("risorsa", "Risorsa", 130, False),
    ("valuta", "Val.", 44, False),
    ("entrata", "Entrate", 95, False),
    ("uscita", "Uscite", 95, False),
    ("s", "S", 26, False),
    ("modalita", "Modalità", 110, True),
    ("c", "C", 26, True),
    ("rif", "Rif", 80, True),
    ("descrizione", "Descrizione", 260, True),
    ("soggetto", "Soggetto", 110, True),
    ("destinazione", "Destinazione", 110, True),
]
COLUMN_INFO = {k: (h, w, c) for k, h, w, c in ALL_COLUMNS}
FIXED_COLUMNS = [k for k, *_, c in ALL_COLUMNS if not c]
OPTIONAL_COLUMNS = [k for k, *_, c in ALL_COLUMNS if c]
SORT_KEYS = {
    "giorno": lambda m, a: (m.data, m.id or 0),
    "gruppo": lambda m, a: (a.name_of("gruppi", m.gruppo_id).lower(), m.data),
    "sottogruppo": lambda m, a: (a.name_of("sottogruppi", m.sottogruppo_id).lower(), m.data),
    "risorsa": lambda m, a: (a.name_of("risorse", m.risorsa_id).lower(), m.data),
    "entrata": lambda m, a: (m.entrata, m.data),
    "uscita": lambda m, a: (m.uscita, m.data),
    "s": lambda m, a: (m.saldato, m.data),
    "modalita": lambda m, a: (a.name_of("modalita", m.modalita_id).lower(), m.data),
    "c": lambda m, a: (m.controllo, m.data),
    "rif": lambda m, a: (m.rif.lower(), m.data),
    "descrizione": lambda m, a: (m.descrizione.lower(), m.data),
    "soggetto": lambda m, a: (a.name_of("soggetti", m.soggetto_id).lower(), m.data),
    "destinazione": lambda m, a: (a.name_of("destinazioni", m.destinazione_id).lower(), m.data),
}


class MovementsModel(QAbstractTableModel):
    changed = Signal()   # un movimento è stato inserito o modificato

    def __init__(self, arc: Archive, parent=None):
        super().__init__(parent)
        self.arc = arc
        self.year = date.today().year
        self.month = date.today().month
        self.risorsa_id: int | None = None
        self.columns = FIXED_COLUMNS + OPTIONAL_COLUMNS
        self.sort_key = "giorno"
        self.rows: list[mv.Movement] = []
        self.draft: dict = {}
        self.last_day: int | None = None
        self.colors = colors(is_dark())

    # --- caricamento -----------------------------------------------------
    def set_columns(self, optional_visible: list[str]):
        self.beginResetModel()
        self.columns = FIXED_COLUMNS + [c for c in optional_visible if c in OPTIONAL_COLUMNS]
        self.endResetModel()

    def load(self, year: int | None = None, month: int | None = None, risorsa_id: int | None | str = "same"):
        self.beginResetModel()
        if year is not None:
            self.year, self.month = year, month
        if risorsa_id != "same":
            self.risorsa_id = risorsa_id
        self.rows = mv.list_month(self.arc, self.year, self.month, self.risorsa_id)
        self._sort()
        self.draft = {}
        self.endResetModel()

    def _sort(self):
        key = SORT_KEYS.get(self.sort_key, SORT_KEYS["giorno"])
        self.rows.sort(key=lambda m: key(m, self.arc))

    def resort(self, key: str | None = None):
        if key:
            self.sort_key = key
        self.beginResetModel()
        self._sort()
        self.endResetModel()

    def refresh_row(self, row: int):
        if 0 <= row < len(self.rows):
            self.rows[row] = mv.get(self.arc, self.rows[row].id)
            self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))

    # --- dimensioni e intestazioni -----------------------------------------
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows) + 1

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            key = self.columns[section]
            return COLUMN_INFO[key][0] + (" *" if key == self.sort_key else "")
        return None

    def is_new_row(self, row: int) -> bool:
        return row == len(self.rows)

    def movement(self, row: int) -> mv.Movement | None:
        return self.rows[row] if 0 <= row < len(self.rows) else None

    # --- visualizzazione -------------------------------------------------
    def _display(self, m: mv.Movement, key: str) -> str:
        a, dec = self.arc, self.arc.decimals
        if key == "giorno":
            return f"{m.data.day:02d} {GIORNI_BREVI[m.data.weekday()]}"
        if key == "gruppo":
            return TRANSFER_LABEL if m.is_transfer else a.name_of("gruppi", m.gruppo_id)
        if key == "sottogruppo":
            return a.name_of("sottogruppi", m.sottogruppo_id)
        if key == "risorsa":
            return a.name_of("risorse", m.risorsa_id)
        if key == "valuta":
            return a.resource_currency(m.risorsa_id)["sigla"]
        if key == "entrata":
            return fmt_amount(m.entrata, dec, blank_zero=True)
        if key == "uscita":
            return fmt_amount(m.uscita, dec, blank_zero=True)
        if key == "s":
            return "*" if m.saldato else ""
        if key == "modalita":
            return a.name_of("modalita", m.modalita_id)
        if key == "c":
            return m.controllo
        if key == "rif":
            return m.rif
        if key == "descrizione":
            return m.descrizione
        if key == "soggetto":
            return a.name_of("soggetti", m.soggetto_id)
        if key == "destinazione":
            return a.name_of("destinazioni", m.destinazione_id)
        return ""

    def _draft_display(self, key: str) -> str:
        d = self.draft
        if key == "giorno" and d.get("giorno"):
            return f"{d['giorno']:02d}"
        if key == "gruppo":
            return self.arc.name_of("gruppi", d.get("gruppo_id")) or NEW_LABEL
        if key == "sottogruppo":
            return self.arc.name_of("sottogruppi", d.get("sottogruppo_id"))
        if key == "risorsa":
            return self.arc.name_of("risorse", d.get("risorsa_id", self.risorsa_id))
        if key in ("entrata", "uscita") and d.get("importo"):
            imp = d["importo"]
            v = imp if key == "entrata" and imp > 0 else -imp if key == "uscita" and imp < 0 else ZERO
            return fmt_amount(v, self.arc.decimals, blank_zero=True)
        if key == "descrizione":
            return d.get("descrizione", "")
        return ""

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        key = self.columns[index.column()]
        row = index.row()
        if self.is_new_row(row):
            if role == Qt.ItemDataRole.DisplayRole:
                return self._draft_display(key)
            if role == Qt.ItemDataRole.ForegroundRole:
                return QBrush(QColor(self.colors["muted"]))
            if role == Qt.ItemDataRole.FontRole and key == "gruppo" and not self.draft.get("gruppo_id"):
                f = QFont()
                f.setItalic(True)
                return f
            return None
        m = self.rows[row]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            text = self._display(m, key)
            if role == Qt.ItemDataRole.ToolTipRole:
                return text if key in ("descrizione", "gruppo", "sottogruppo") and text else None
            return text
        if role == Qt.ItemDataRole.EditRole:
            return self._display(m, key)
        if role == Qt.ItemDataRole.TextAlignmentRole and key in ("entrata", "uscita"):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.TextAlignmentRole and key in ("s", "c", "valuta"):
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.ForegroundRole:
            c = self.colors
            if key == "entrata":
                return QBrush(QColor(c["in"] if m.saldato else c["in_open"]))
            if key == "uscita":
                return QBrush(QColor(c["out"] if m.saldato else c["out_open"]))
            if not m.saldato:
                return QBrush(QColor(c["open"]))
        if role == Qt.ItemDataRole.FontRole and m.is_transfer:
            f = QFont()
            f.setItalic(True)
            return f
        return None

    def flags(self, index):
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        key = self.columns[index.column()]
        if key == "valuta":
            return base
        m = self.movement(index.row())
        if m is not None and m.is_transfer:
            return base
        if key == "s":
            return base
        return base | Qt.ItemFlag.ItemIsEditable

    # --- modifica --------------------------------------------------------
    def days_in_month(self) -> int:
        return calendar.monthrange(self.year, self.month)[1]

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        key = self.columns[index.column()]
        row = index.row()
        try:
            if self.is_new_row(row):
                return self._set_draft(key, value)
            m = self.rows[row]
            new = self._apply(m, key, value)
            if new is None or new == m:
                return False
            mv.save(self.arc, new)
        except (ArchiveError, ValueError) as e:
            error(None, e)
            return False
        self.rows[row] = mv.get(self.arc, m.id)
        self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))
        self.changed.emit()
        return True

    def _apply(self, m: mv.Movement, key: str, value) -> mv.Movement | None:
        if key == "giorno":
            return replace(m, data=m.data.replace(day=int(value)))
        if key == "gruppo":
            if value is None:
                raise ValueError("Il gruppo è obbligatorio")
            sub = m.sottogruppo_id
            if sub is not None and self.arc.row("sottogruppi", sub)["gruppo_id"] != value:
                sub = None
            return replace(m, gruppo_id=value, sottogruppo_id=sub)
        if key == "sottogruppo":
            return replace(m, sottogruppo_id=value)
        if key == "risorsa":
            if value is None:
                raise ValueError("La risorsa è obbligatoria")
            mod = m.modalita_id
            if mod is not None and self.arc.row("modalita", mod)["risorsa_id"] != value:
                mod = None
            return replace(m, risorsa_id=value, modalita_id=mod)
        if key in ("entrata", "uscita"):
            v = abs(parse_amount(str(value)))
            if key == "entrata":
                imp = v if v else (m.importo if m.importo < 0 else ZERO)
            else:
                imp = -v if v else (m.importo if m.importo > 0 else ZERO)
            return replace(m, importo=imp)
        if key in ("modalita", "soggetto", "destinazione"):
            return replace(m, **{f"{key}_id": value})
        if key == "descrizione":
            return replace(m, descrizione=str(value)[:mv.MAX_DESCRIZIONE])
        if key == "rif":
            return replace(m, rif=str(value)[:mv.MAX_RIF])
        if key == "c":
            return replace(m, controllo=str(value)[:1])
        return None

    def _set_draft(self, key: str, value) -> bool:
        d = self.draft
        if key == "giorno":
            d["giorno"] = int(value)
        elif key in ("gruppo", "sottogruppo", "risorsa", "modalita", "soggetto", "destinazione"):
            d[f"{key}_id"] = value
            if key == "gruppo":
                d.pop("sottogruppo_id", None)
        elif key in ("entrata", "uscita"):
            v = abs(parse_amount(str(value)))
            d["importo"] = v if key == "entrata" else -v
        elif key in ("descrizione", "rif", "c"):
            d[key] = str(value)
        r = len(self.rows)
        self.dataChanged.emit(self.index(r, 0), self.index(r, self.columnCount() - 1))
        return self._commit_draft_if_ready()

    def draft_defaults(self) -> dict:
        today = date.today()
        day = self.last_day or (today.day if (today.year, today.month) == (self.year, self.month) else 1)
        return {"giorno": min(day, self.days_in_month()), "risorsa_id": self.risorsa_id}

    def _commit_draft_if_ready(self) -> bool:
        d = {**self.draft_defaults(), **{k: v for k, v in self.draft.items() if v is not None}}
        if not (d.get("gruppo_id") and d.get("risorsa_id")):
            return True
        m = mv.Movement(
            data=date(self.year, self.month, d["giorno"]), risorsa_id=d["risorsa_id"], gruppo_id=d["gruppo_id"],
            sottogruppo_id=d.get("sottogruppo_id"), importo=d.get("importo", ZERO),
            saldato=self.arc.setting("salda_subito") == "1", modalita_id=d.get("modalita_id"),
            destinazione_id=d.get("destinazione_id"), soggetto_id=d.get("soggetto_id"),
            descrizione=d.get("descrizione", "")[:mv.MAX_DESCRIZIONE], rif=d.get("rif", "")[:mv.MAX_RIF],
            controllo=d.get("c", "")[:1])
        mv.save(self.arc, m)
        self.last_day = d["giorno"]
        r = len(self.rows)
        self.beginInsertRows(QModelIndex(), r, r)
        self.rows.append(m)
        self.draft = {}
        self.endInsertRows()
        self.changed.emit()
        return True

    # --- editor -------------------------------------------------------------
    def context_for(self, row: int) -> dict:
        """Gruppo e risorsa della riga, per filtrare sottogruppi e modalità negli editor."""
        m = self.movement(row)
        if m is not None:
            return {"gruppo_id": m.gruppo_id, "risorsa_id": m.risorsa_id, "giorno": m.data.day}
        d = {**self.draft_defaults(), **self.draft}
        return {"gruppo_id": d.get("gruppo_id"), "risorsa_id": d.get("risorsa_id"), "giorno": d.get("giorno")}


class MovementsDelegate(QStyledItemDelegate):
    def __init__(self, model: MovementsModel, parent=None):
        super().__init__(parent)
        self.model = model

    def _key(self, index) -> str:
        return self.model.columns[index.column()]

    def createEditor(self, parent, option, index):
        key = self._key(index)
        arc = self.model.arc
        ctx = self.model.context_for(index.row())
        m = self.model.movement(index.row())
        if key == "giorno":
            e = QSpinBox(parent)
            e.setRange(1, self.model.days_in_month())
            return e
        if key in ("gruppo", "sottogruppo", "risorsa", "modalita", "soggetto", "destinazione"):
            e = LookupCombo(parent, allow_empty=key not in ("gruppo", "risorsa"))
            cur = getattr(m, f"{key}_id") if m else self.model.draft.get(f"{key}_id")
            if key == "gruppo":
                items = group_items(arc, cur)
            elif key == "sottogruppo":
                if not ctx["gruppo_id"]:
                    return None
                items = lookup_items(arc, "sottogruppi", "gruppo_id = ?", (ctx["gruppo_id"],), cur)
            elif key == "risorsa":
                items = lookup_items(arc, "risorse", include=cur)
            elif key == "modalita":
                if not ctx["risorsa_id"]:
                    return None
                items = lookup_items(arc, "modalita", "risorsa_id = ?", (ctx["risorsa_id"],), cur)
            else:
                items = lookup_items(arc, {"soggetto": "soggetti", "destinazione": "destinazioni"}[key], include=cur)
            e.fill(items, cur)
            return e
        if key == "descrizione":
            e = LookupCombo(parent)
            e.completer().setFilterMode(Qt.MatchFlag.MatchContains)
            e.fill([(None, r["nome"]) for r in arc.rows("descrizioni", "in_uso = 1")])
            e.lineEdit().setMaxLength(mv.MAX_DESCRIZIONE)
            return e
        if key in ("entrata", "uscita"):
            from .calculator_dialog import AmountCellEdit
            e = AmountCellEdit(parent)
            e.setAlignment(Qt.AlignmentFlag.AlignRight)
            e.setToolTip("F2: calcolatrice")
            return e
        e = QLineEdit(parent)
        if key == "rif":
            e.setMaxLength(mv.MAX_RIF)
        elif key == "c":
            e.setMaxLength(1)
        return e

    def setEditorData(self, editor, index):
        key = self._key(index)
        m = self.model.movement(index.row())
        if key == "giorno":
            editor.setValue(m.data.day if m else self.model.context_for(index.row())["giorno"] or 1)
        elif isinstance(editor, LookupCombo) and key != "descrizione":
            pass  # già impostata in createEditor
        elif key == "descrizione":
            editor.setEditText(m.descrizione if m else self.model.draft.get("descrizione", ""))
            editor.lineEdit().selectAll()
        else:
            editor.setText(index.data(Qt.ItemDataRole.EditRole) or (index.data() if m else ""))
            editor.selectAll()

    def setModelData(self, editor, model, index):
        key = self._key(index)
        if key == "giorno":
            model.setData(index, editor.value())
        elif key == "descrizione":
            model.setData(index, editor.currentText().strip())
        elif isinstance(editor, LookupCombo):
            text = editor.currentText().strip()
            v = editor.value()
            if text and v is None:
                error(None, f"«{text}» non è presente in tabella")
                return
            model.setData(index, v)
        else:
            model.setData(index, editor.text().strip())


class MovementsView(QTableView):
    toggleSettled = Signal()

    def __init__(self, model: MovementsModel, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self.setItemDelegate(MovementsDelegate(model, self))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
                             | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setDefaultSectionSize(22)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.horizontalHeader().setHighlightSections(False)
        model.modelReset.connect(self.apply_widths)
        self.apply_widths()

    def apply_widths(self):
        for i, key in enumerate(self.model().columns):
            self.setColumnWidth(i, round(COLUMN_INFO[key][1] * getattr(self, "zoom", 100) / 100))

    def selected_rows(self) -> list[int]:
        rows = {i.row() for i in self.selectedIndexes()}
        if not rows and self.currentIndex().isValid():
            rows = {self.currentIndex().row()}
        return sorted(r for r in rows if not self.model().is_new_row(r))

    def selected_movements(self) -> list[mv.Movement]:
        return [self.model().rows[r] for r in self.selected_rows()]

    def go_to_new_row(self):
        m = self.model()
        col = m.columns.index("giorno")
        idx = m.index(m.rowCount() - 1, col)
        self.setCurrentIndex(idx)
        self.scrollTo(idx)

    def select_movement(self, id_: int):
        m = self.model()
        for r, mov in enumerate(m.rows):
            if mov.id == id_:
                idx = m.index(r, 0)
                self.setCurrentIndex(idx)
                self.scrollTo(idx)
                return

    ZOOM = {Qt.Key.Key_F5: 85, Qt.Key.Key_F6: 100, Qt.Key.Key_F7: 120, Qt.Key.Key_F8: 145}

    def set_zoom(self, percent: int):
        """Scala di visualizzazione dell'elenco (F5…F8)."""
        f = self.font()
        if not hasattr(self, "_base_pt"):
            self._base_pt = f.pointSizeF()
        f.setPointSizeF(self._base_pt * percent / 100)
        self.setFont(f)
        self.verticalHeader().setDefaultSectionSize(round(22 * percent / 100))
        m = self.model()
        for i, key in enumerate(m.columns):
            self.setColumnWidth(i, round(COLUMN_INFO[key][1] * percent / 100))
        self.zoom = percent

    def keyPressEvent(self, ev):
        key = ev.key()
        if key in self.ZOOM and not ev.modifiers():
            self.set_zoom(self.ZOOM[key])
            return
        if key == Qt.Key.Key_Delete and not ev.modifiers():
            idx = self.currentIndex()
            k = self.model().columns[idx.column()] if idx.isValid() else None
            if idx.isValid() and k in ("sottogruppo", "modalita", "soggetto", "destinazione", "descrizione", "rif",
                                       "c", "entrata", "uscita") and self.model().flags(idx) & Qt.ItemFlag.ItemIsEditable:
                self.model().setData(idx, None if k in ("sottogruppo", "modalita", "soggetto", "destinazione") else "")
                return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.state() != QAbstractItemView.State.EditingState:
            idx = self.currentIndex()
            if idx.isValid():
                nxt = self.model().index(min(idx.row() + 1, self.model().rowCount() - 1)
                                         if idx.column() == self.model().columnCount() - 1 else idx.row(),
                                         (idx.column() + 1) % self.model().columnCount())
                self.setCurrentIndex(nxt)
                return
        super().keyPressEvent(ev)
