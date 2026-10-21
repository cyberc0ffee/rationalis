"""Testi in italiano condivisi da motore e interfaccia (nomi dei mesi e dei giorni)."""
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
        "ottobre", "novembre", "dicembre"]
GIORNI_BREVI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


def long_date(d, capital: bool = True) -> str:
    """«Martedì 20 ottobre 2026» senza dipendere dalla lingua del sistema."""
    s = f"{GIORNI[d.weekday()]} {d.day} {MESI[d.month - 1]} {d.year}"
    return s[0].upper() + s[1:] if capital else s


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def month_name(month: int, capital: bool = True) -> str:
    n = MESI[month - 1]
    return n.capitalize() if capital else n
