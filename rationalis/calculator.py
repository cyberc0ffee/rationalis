"""Motore della calcolatrice: quattro operazioni con ripetizione, percentuali, IVA, cambio, nastro.

Uso tipico (tasti): press("2"), press("0"), press("+"), ..., press("=").
Tasti accettati: cifre, ",", ".", "+", "-", "*", "/", "=", "%", "back", "canc", "segno",
"iva+", "iva-", "cambio".
"""
from decimal import Decimal, DivisionByZero, InvalidOperation

from .money import fmt_amount

OPS = {"+", "-", "*", "/"}


class Calculator:
    def __init__(self, decimals: int = 2, vat_rate: Decimal = Decimal(22)):
        self.decimals = decimals
        self.vat_rate = Decimal(vat_rate)
        self.rate = Decimal(1)           # cambio corrente: valore * rate
        self.tape: list[str] = []
        self.error = False
        self._clear_all()

    def _clear_all(self):
        self.acc: Decimal | None = None
        self.pending: str | None = None
        self.entry = ""
        self.last_op: str | None = None
        self.last_operand: Decimal | None = None
        self.result: Decimal = Decimal(0)

    # --- valore mostrato -------------------------------------------------
    @property
    def value(self) -> Decimal:
        if self.entry not in ("", "-"):
            return Decimal(self.entry.replace(",", "."))
        return self.result

    @property
    def display(self) -> str:
        if self.error:
            return "Errore"
        if self.entry:
            return self.entry.replace(".", ",")
        return fmt_amount(self.result, self.decimals)

    # --- operazioni ------------------------------------------------------
    @staticmethod
    def _apply(a: Decimal, op: str, b: Decimal) -> Decimal:
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        return a / b

    def _set_result(self, v: Decimal):
        self.result = v
        self.acc = v

    def _log(self, text: str):
        self.tape.append(text)

    def press(self, key: str):
        if self.error:
            if key == "canc":
                self._clear_all()
                self.error = False
            return
        try:
            self._press(key)
        except (DivisionByZero, InvalidOperation, ZeroDivisionError):
            self.error = True
            self._log("Errore")

    def _press(self, key: str):
        if key.isdigit():
            if len(self.entry.replace("-", "").replace(".", "")) < 15:
                self.entry = ("" if self.entry == "0" else self.entry) + key
        elif key in (",", "."):
            if "." not in self.entry:
                self.entry = (self.entry or "0") + "."
        elif key == "back":
            self.entry = self.entry[:-1]
        elif key == "canc":
            if self.entry:
                self.entry = ""
            else:
                self._clear_all()
                self.error = False
                self._log("— Ce —")
        elif key == "segno":
            if self.entry:
                self.entry = self.entry[1:] if self.entry.startswith("-") else "-" + self.entry
            else:
                self._set_result(-self.result)
        elif key in OPS:
            self._operator(key)
        elif key == "=":
            self._equals()
        elif key == "%":
            self._percent()
        elif key in ("iva+", "iva-"):
            v = self.value
            f = 1 + self.vat_rate / 100
            r = v * f if key == "iva+" else v / f
            self._log(f"{fmt_amount(v, self.decimals)} {'+' if key == 'iva+' else '-'} IVA {self.vat_rate}% = "
                      f"{fmt_amount(r, self.decimals)}")
            self.entry = ""
            self._set_result(r)
        elif key == "cambio":
            v = self.value
            r = v * self.rate
            self._log(f"{fmt_amount(v, self.decimals)} × {self.rate} = {fmt_amount(r, self.decimals)}")
            self.entry = ""
            self._set_result(r)
        else:
            raise ValueError(f"Tasto sconosciuto: {key}")

    def _operator(self, op: str):
        if self.entry not in ("", "-"):
            operand = self.value
            self._log(f"{fmt_amount(operand, self.decimals)} {op}")
            if self.pending and self.acc is not None:
                self._set_result(self._apply(self.acc, self.pending, operand))
            else:
                self._set_result(operand)
            self.last_operand = operand
            self.entry = ""
        elif self.pending == op and self.last_operand is not None:
            # ripetizione: 20+10+++ = 20+10+10+10
            self._set_result(self._apply(self.acc, op, self.last_operand))
            self._log(f"{fmt_amount(self.last_operand, self.decimals)} {op}")
        elif self.acc is None:
            self.acc = self.result
        self.pending = op
        self.last_op = op

    def _equals(self):
        if self.entry not in ("", "-") and self.pending and self.acc is not None:
            operand = self.value
            self._set_result(self._apply(self.acc, self.pending, operand))
            self._log(f"{fmt_amount(operand, self.decimals)} =")
            self.last_operand, self.last_op = operand, self.pending
        elif self.entry not in ("", "-"):
            self._set_result(self.value)
        elif self.last_op and self.last_operand is not None:
            self._set_result(self._apply(self.result, self.last_op, self.last_operand))
            self._log(f"{fmt_amount(self.last_operand, self.decimals)} =")
        self.entry = ""
        self.pending = None
        self._log(f"  {fmt_amount(self.result, self.decimals)}")

    def _percent(self):
        if not self.entry or self.acc is None or self.pending is None:
            return
        p = self.value
        base = self.acc
        if self.pending == "+":
            r = base + base * p / 100
        elif self.pending == "-":
            r = base - base * p / 100
        elif self.pending == "*":
            r = base * p / 100
        else:
            r = base / (p / 100)
        self._log(f"{fmt_amount(p, self.decimals)} % =")
        self._log(f"  {fmt_amount(r, self.decimals)}")
        self.entry = ""
        self.pending = None
        self._set_result(r)

    def keys(self, sequence: str):
        """Comodità per i test: "20+10+++" o "200*5%"."""
        for ch in sequence:
            self.press("=" if ch == "\n" else ch)
