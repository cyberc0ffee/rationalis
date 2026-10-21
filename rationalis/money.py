"""Importi: conversione tra Decimal e intero memorizzato, lettura e formattazione all'italiana.

Gli importi sono salvati come interi in decimillesimi (4 decimali), così da supportare
fino a 4 cifre decimali di visualizzazione senza errori di arrotondamento.
"""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

SCALE = 10_000
ZERO = Decimal(0)

_THOUSANDS = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def to_db(value: Decimal | int | str | None) -> int:
    if value is None or value == "":
        return 0
    return int((Decimal(value) * SCALE).quantize(Decimal(1), ROUND_HALF_UP))


def from_db(value: int | None) -> Decimal:
    return Decimal(value or 0) / SCALE


def parse_amount(text: str) -> Decimal:
    """Legge un importo digitato: "1.350,50", "1350.5", "1.350", "-7,6", "€ 12"."""
    t = text.strip().replace("€", "").replace(" ", "").replace(" ", "")
    if not t:
        return ZERO
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif _THOUSANDS.match(t):
        t = t.replace(".", "")
    try:
        return Decimal(t)
    except InvalidOperation:
        raise ValueError(f"Importo non valido: {text!r}") from None


def parse_rate(text: str) -> Decimal:
    """Legge un tasso di cambio: la virgola o il punto sono sempre il separatore decimale."""
    t = text.strip().replace(" ", "").replace(",", ".")
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise ValueError(f"Cambio non valido: {text!r}") from None
    if d <= 0:
        raise ValueError("Il cambio deve essere maggiore di zero")
    return d


def fmt_amount(value: Decimal | None, decimals: int = 2, blank_zero: bool = False) -> str:
    if value is None or (blank_zero and value == 0):
        return ""
    q = Decimal(1).scaleb(-decimals)
    s = f"{value.quantize(q, ROUND_HALF_UP):,.{decimals}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def round_to(value: Decimal, decimals: int = 2) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-decimals), ROUND_HALF_UP)
