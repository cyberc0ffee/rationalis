"""Calcolatrice: tastiera e mouse, IVA, cambio valute, nastro dei calcoli.

Tasti: cifre e , . | + − * / | Invio (=) | % | Backspace | Canc (cancella numero, poi tutto) | Fine (±)
Pag Su / Pag Giù (aggiungi / scorpora IVA) | F2 nastro | F3 modalità di cambio | F4 opzioni |
F5…F9 decimali 0…4 | T sempre in primo piano | M riduci a icona | Ctrl+C / Ctrl+V | Esc chiudi.
In modalità «scelta importo» (dalla griglia dei movimenti) Invio calcola e restituisce il risultato.
"""
import json
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QPushButton, QRadioButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..calculator import Calculator
from ..money import fmt_amount, parse_amount, parse_rate

DEFAULT_RATES = [["EUR", "USD", "1.08"], ["EUR", "GBP", "0.85"], ["EUR", "CHF", "0.95"], ["EUR", "JPY", "160"],
                 ["EUR", "ITL", "1936.27"]]


def load_options() -> dict:
    s = QSettings()
    try:
        rates = json.loads(s.value("calcolatrice/cambi") or "null") or DEFAULT_RATES
    except ValueError:
        rates = DEFAULT_RATES
    return {"iva": Decimal(str(s.value("calcolatrice/iva", "22"))), "decimali": int(s.value("calcolatrice/decimali", 2)),
            "cambi": rates, "cambio_scelto": int(s.value("calcolatrice/cambio_scelto", 0))}


def save_options(o: dict):
    s = QSettings()
    s.setValue("calcolatrice/iva", str(o["iva"]))
    s.setValue("calcolatrice/decimali", o["decimali"])
    s.setValue("calcolatrice/cambi", json.dumps(o["cambi"]))
    s.setValue("calcolatrice/cambio_scelto", o["cambio_scelto"])


class CalculatorOptions(QDialog):
    def __init__(self, opts: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Opzioni della calcolatrice")
        self.iva = QDoubleSpinBox()
        self.iva.setRange(0, 100)
        self.iva.setDecimals(2)
        self.iva.setSuffix(" %")
        self.iva.setValue(float(opts["iva"]))
        self.dec = QSpinBox()
        self.dec.setRange(0, 4)
        self.dec.setValue(opts["decimali"])
        self.rates = QTableWidget(5, 4)
        self.rates.setHorizontalHeaderLabels(["Usa", "Valuta 1", "Valuta 2", "1 valuta 1 = … valuta 2"])
        self.radios = []
        for r, (a, b, rate) in enumerate(opts["cambi"][:5]):
            rb = QRadioButton()
            rb.setChecked(r == opts["cambio_scelto"])
            self.radios.append(rb)
            self.rates.setCellWidget(r, 0, rb)
            for c, v in enumerate((a, b, rate.replace(".", ",")), 1):
                self.rates.setItem(r, c, QTableWidgetItem(v))
        self.rates.resizeColumnsToContents()
        form = QFormLayout()
        form.addRow("Aliquota IVA", self.iva)
        form.addRow("Decimali visualizzati", self.dec)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(QLabel("Cambi e valute"))
        lay.addWidget(self.rates)
        lay.addWidget(bb)

    def values(self) -> dict:
        rates = []
        for r in range(5):
            a, b, rate = (self.rates.item(r, c).text().strip() if self.rates.item(r, c) else "" for c in (1, 2, 3))
            try:
                rate = str(parse_rate(rate))
            except ValueError:
                rate = "1"
            rates.append([a[:4] or "?", b[:4] or "?", rate])
        chosen = next((i for i, rb in enumerate(self.radios) if rb.isChecked()), 0)
        return {"iva": Decimal(str(round(self.iva.value(), 2))), "decimali": self.dec.value(), "cambi": rates,
                "cambio_scelto": chosen}


class CalculatorDialog(QDialog):
    KEYMAP = {Qt.Key.Key_Plus: "+", Qt.Key.Key_Minus: "-", Qt.Key.Key_Asterisk: "*", Qt.Key.Key_Slash: "/",
              Qt.Key.Key_Percent: "%", Qt.Key.Key_Comma: ",", Qt.Key.Key_Period: ".", Qt.Key.Key_Return: "=",
              Qt.Key.Key_Enter: "=", Qt.Key.Key_Equal: "=", Qt.Key.Key_Backspace: "back", Qt.Key.Key_Delete: "canc",
              Qt.Key.Key_End: "segno", Qt.Key.Key_PageUp: "iva+", Qt.Key.Key_PageDown: "iva-"}

    def __init__(self, parent=None, initial: Decimal | None = None, picker: bool = False):
        super().__init__(parent)
        self.picker = picker
        self.result_value: Decimal | None = None
        self.opts = load_options()
        self.calc = Calculator(self.opts["decimali"], self.opts["iva"])
        self.rate_mode = 0          # 0 nessun cambio, 1 valuta1→valuta2, 2 valuta2→valuta1
        self.setWindowTitle("Calcolatrice" + (" – Invio inserisce il risultato" if picker else ""))
        self.display = QLabel()
        f = QFont()
        f.setPointSize(20)
        f.setBold(True)
        self.display.setFont(f)
        self.display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.display.setMinimumWidth(280)
        self.display.setStyleSheet("padding: 6px; border: 1px solid palette(mid); background: palette(base)")
        self.info = QLabel()
        self.info.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.info.setStyleSheet("color: palette(placeholder-text)")
        grid = QGridLayout()
        keys = [("Ce", "canc"), ("←", "back"), ("%", "%"), ("/", "/"),
                ("7", "7"), ("8", "8"), ("9", "9"), ("×", "*"),
                ("4", "4"), ("5", "5"), ("6", "6"), ("−", "-"),
                ("1", "1"), ("2", "2"), ("3", "3"), ("+", "+"),
                ("±", "segno"), ("0", "0"), (",", ","), ("=", "="),
                ("+IVA", "iva+"), ("−IVA", "iva-"), ("⇄", "cambio"), ("Nastro", "tape")]
        for i, (label, key) in enumerate(keys):
            b = QPushButton(label)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setMinimumHeight(34)
            b.clicked.connect(lambda _=False, k=key: self._press(k))
            grid.addWidget(b, i // 4, i % 4)
        self.tape = QListWidget()
        self.tape.setVisible(False)
        tape_row = QHBoxLayout()
        for text, fn in (("Pulisci", self._tape_clear), ("Copia", self._tape_copy)):
            b = QPushButton(text)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(fn)
            tape_row.addWidget(b)
        self.tape_box = QVBoxLayout()
        self.tape_box.addWidget(self.tape)
        self.tape_box.addLayout(tape_row)
        self.tape_buttons = [tape_row.itemAt(i).widget() for i in range(tape_row.count())]
        for b in self.tape_buttons:
            b.setVisible(False)
        lay = QVBoxLayout(self)
        lay.addWidget(self.display)
        lay.addWidget(self.info)
        lay.addLayout(grid)
        lay.addLayout(self.tape_box)
        if picker:
            use = QPushButton("Inserisci il risultato")
            use.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            use.clicked.connect(self._use)
            lay.addWidget(use)
        if initial:
            for ch in fmt_amount(abs(initial), 4).replace(".", "").rstrip("0").rstrip(","):
                self.calc.press(ch)
            if initial < 0:
                self.calc.press("segno")
        self._refresh()

    # --- stato ---------------------------------------------------------------
    def _pair(self):
        a, b, rate = self.opts["cambi"][self.opts["cambio_scelto"]]
        return a, b, Decimal(rate)

    def _sync_rate(self) -> Decimal:
        _a, _b, rate = self._pair()
        self.calc.rate = rate if self.rate_mode != 2 else 1 / rate
        return self.calc.rate

    def _refresh(self):
        self.display.setText(self.calc.display)
        parts = [f"IVA {fmt_amount(self.opts['iva'], 2).rstrip('0').rstrip(',')}%", f"{self.calc.decimals} dec."]
        if self.rate_mode:
            a, b, _rate = self._pair()
            src, dst = (a, b) if self.rate_mode == 1 else (b, a)
            r = self._sync_rate()
            try:
                conv = fmt_amount(self.calc.value * r, self.calc.decimals)
            except InvalidOperation:
                conv = "—"
            parts.append(f"{src}→{dst}: {conv}")
        else:
            parts.append("cambio: no (F3)")
        if self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint:
            parts.append("in primo piano")
        self.info.setText("   ·   ".join(parts))
        self.tape.clear()
        self.tape.addItems(self.calc.tape[-200:])
        self.tape.scrollToBottom()

    def _press(self, key: str):
        if key == "tape":
            self._toggle_tape()
            return
        if key == "cambio":
            if not self.rate_mode:
                self.rate_mode = 1
            self._sync_rate()
        self.calc.press(key)
        self._refresh()

    def _toggle_tape(self):
        vis = not self.tape.isVisible()
        self.tape.setVisible(vis)
        for b in self.tape_buttons:
            b.setVisible(vis)
        self.adjustSize()

    def _tape_clear(self):
        self.calc.tape.clear()
        self._refresh()

    def _tape_copy(self):
        QGuiApplication.clipboard().setText("\n".join(self.calc.tape))

    def _use(self):
        if self.calc.pending or self.calc.entry:
            self.calc.press("=")
        if self.calc.error:
            return
        self.result_value = self.calc.value
        self.accept()

    # --- tastiera ---------------------------------------------------------------
    def keyPressEvent(self, ev):
        k, text = ev.key(), ev.text()
        if ev.matches(QKeySequence.StandardKey.Copy):
            QGuiApplication.clipboard().setText(self.calc.display)
            return
        if ev.matches(QKeySequence.StandardKey.Paste):
            try:
                v = parse_amount(QGuiApplication.clipboard().text())
            except ValueError:
                return
            self.calc.press("canc")
            for ch in fmt_amount(abs(v), 4).replace(".", "").rstrip("0").rstrip(","):
                self.calc.press(ch)
            if v < 0:
                self.calc.press("segno")
            self._refresh()
            return
        if k == Qt.Key.Key_Escape:
            self.reject()
            return
        if self.picker and k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (self.calc.pending or self.calc.entry):
            self._use()
            return
        if self.picker and k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.calc.press("=")
            self._use()
            return
        if Qt.Key.Key_F5 <= k <= Qt.Key.Key_F9:
            if not self.calc.entry:
                self.calc.decimals = k - Qt.Key.Key_F5
            self._refresh()
            return
        if k == Qt.Key.Key_F2:
            self._toggle_tape()
            return
        if k == Qt.Key.Key_F3:
            self.rate_mode = (self.rate_mode + 1) % 3
            self._refresh()
            return
        if k == Qt.Key.Key_F4:
            dlg = CalculatorOptions(self.opts, self)
            if dlg.exec():
                self.opts = dlg.values()
                save_options(self.opts)
                self.calc.vat_rate = self.opts["iva"]
                self.calc.decimals = self.opts["decimali"]
                self._refresh()
            return
        if text.lower() == "t":
            on = not (self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
            self.show()
            self._refresh()
            return
        if text.lower() == "m":
            self.showMinimized()
            return
        if text.isdigit():
            self._press(text)
            return
        key = self.KEYMAP.get(k)
        if key:
            self._press(key)
            return
        super().keyPressEvent(ev)


class AmountCellEdit(QLineEdit):
    """Editor degli importi nella griglia: F2 apre la calcolatrice e ne riporta il risultato."""

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_F2:
            try:
                start = parse_amount(self.text()) if self.text().strip() else None
            except ValueError:
                start = None
            dlg = CalculatorDialog(self, start, picker=True)
            if dlg.exec() and dlg.result_value is not None:
                self.setText(fmt_amount(abs(dlg.result_value), 4).rstrip("0").rstrip(","))
            return
        super().keyPressEvent(ev)
