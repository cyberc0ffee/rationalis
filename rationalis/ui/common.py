"""Componenti condivisi dall'interfaccia: combo collegate alle tabelle, campi importo, messaggi."""
from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QComboBox, QCompleter, QDateEdit, QLineEdit, QMessageBox, QWidget

from ..db import ArchiveError
from ..money import fmt_amount, parse_amount

from ..ui_text import MESI


def error(parent: QWidget | None, exc: Exception | str, title: str = "Rationalis"):
    QMessageBox.warning(parent, title, str(exc))


def ask(parent: QWidget | None, text: str, title: str = "Rationalis") -> bool:
    return QMessageBox.question(parent, title, text,
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) \
        == QMessageBox.StandardButton.Yes


def guarded(parent: QWidget | None, fn, *args, **kwargs):
    """Esegue fn mostrando gli errori dell'archivio come messaggi. Restituisce (ok, risultato)."""
    try:
        return True, fn(*args, **kwargs)
    except (ArchiveError, ValueError) as e:
        error(parent, e)
        return False, None


def to_qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def from_qdate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


class DateEdit(QDateEdit):
    def __init__(self, value: date | None = None, parent=None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("dd/MM/yyyy")
        self.set_date(value or date.today())

    def set_date(self, d: date):
        self.setDate(to_qdate(d))

    def value(self) -> date:
        return from_qdate(self.date())


class LookupCombo(QComboBox):
    """Combo modificabile con completamento sulle voci di una tabella (id nei dati utente)."""

    def __init__(self, parent=None, allow_empty: bool = True):
        super().__init__(parent)
        self.allow_empty = allow_empty
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        comp = self.completer()
        comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        comp.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def fill(self, items, current: int | None = None):
        """items: iterabile di (id, testo)."""
        self.blockSignals(True)
        self.clear()
        if self.allow_empty:
            self.addItem("", None)
        for id_, text in items:
            self.addItem(text, id_)
        self.set_value(current)
        self.blockSignals(False)

    def set_value(self, id_: int | None):
        i = self.findData(id_)
        self.setCurrentIndex(i if i >= 0 else (0 if self.allow_empty or self.count() else -1))

    def value(self) -> int | None:
        text = self.currentText().strip()
        if not text:
            return None
        i = self.findText(text, Qt.MatchFlag.MatchFixedString)
        if i < 0:
            matches = [j for j in range(self.count()) if self.itemText(j).lower().startswith(text.lower())]
            if len(matches) != 1:
                return None
            i = matches[0]
        return self.itemData(i)


def lookup_items(arc, table: str, where: str = "", params=(), include: int | None = None):
    """Voci in uso della tabella (più `include` anche se disattivata, per non perderla in modifica)."""
    cond = "in_uso = 1" + (f" AND {where}" if where else "")
    if include is not None:
        cond = f"({cond}) OR id = {int(include)}"
    return [(r["id"], r["nome"]) for r in arc.rows(table, cond, params)]


def group_items(arc, include: int | None = None):
    signs = {"E": "+", "U": "−", "M": "±"}
    cond = "in_uso = 1" if include is None else f"in_uso = 1 OR id = {int(include)}"
    return [(r["id"], f"{r['nome']}  {signs[r['tipo']]}") for r in arc.rows("gruppi", cond)]


class AmountEdit(QLineEdit):
    def __init__(self, decimals: int = 2, parent=None, allow_negative: bool = True):
        super().__init__(parent)
        self.decimals = decimals
        self.allow_negative = allow_negative
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.editingFinished.connect(self._reformat)

    def _reformat(self):
        try:
            v = self.value()
        except ValueError:
            return
        self.setText(fmt_amount(v, self.decimals) if self.text().strip() else "")

    def set_value(self, v: Decimal | None):
        self.setText("" if v is None else fmt_amount(v, self.decimals))

    def value(self) -> Decimal:
        v = parse_amount(self.text())
        if v < 0 and not self.allow_negative:
            raise ValueError("L'importo non può essere negativo")
        return v


def is_dark(widget: QWidget | None = None) -> bool:
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    pal = widget.palette() if widget is not None else QApplication.palette()
    return pal.color(QPalette.ColorRole.Base).lightness() < 128


def colors(dark: bool) -> dict[str, str]:
    """Colori per entrate, uscite e movimenti non saldati, leggibili sia con tema chiaro sia scuro."""
    if dark:
        return {"in": "#7ad68a", "in_open": "#5e9a68", "out": "#ff8a80", "out_open": "#b9726c", "open": "#a3a3c2",
                "muted": "#8c8c8c"}
    return {"in": "#1b6e2a", "in_open": "#6d9b74", "out": "#a32020", "out_open": "#c08080", "open": "#6b6b8a",
            "muted": "#7a7a7a"}


def fix_palette(app):
    """Con Fusion e tema scuro le righe alternate prendono il colore d'accento: usa un grigio vicino allo sfondo."""
    from PySide6.QtGui import QPalette
    pal = app.palette()
    base = pal.color(QPalette.ColorRole.Base)
    dark = base.lightness() < 128
    pal.setColor(QPalette.ColorRole.AlternateBase, base.lighter(125) if dark else base.darker(104))
    app.setPalette(pal)


def shade_color(widget: QWidget):
    """Sfondo per le righe da evidenziare nelle tabelle dei prospetti."""
    from PySide6.QtGui import QPalette
    base = widget.palette().color(QPalette.ColorRole.Base)
    return base.lighter(170) if base.lightness() < 128 else base.darker(112)


def month_label(year: int, month: int) -> str:
    return f"{MESI[month - 1].capitalize()} {year}"
