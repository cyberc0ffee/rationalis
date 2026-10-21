"""Codici per intestazione e piè di pagina delle stampe.

    &L &C &R  testo che segue allineato a sinistra, al centro, a destra
    &D &T     data e ora correnti
    &P &N     numero di pagina e numero totale di pagine
    &B &I &U  grassetto, corsivo, sottolineato (per la sezione in cui compaiono)
    &nn       dimensione del carattere in punti (es. &12)
    &&        il carattere & stesso

Esempio: "&LProva &B&RPagina &P" → "Prova" a sinistra, "Pagina 1" in grassetto a destra.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Section:
    text: str = ""
    bold: bool = False
    italic: bool = False
    underline: bool = False
    size: int | None = None


def parse(spec: str, page: int, pages: int, now: datetime | None = None) -> dict[str, Section]:
    """Restituisce le sezioni 'L', 'C', 'R' con testo già espanso e formattazione."""
    now = now or datetime.now()
    out = {"L": Section(), "C": Section(), "R": Section()}
    cur = "L"
    pending: dict = {}
    i = 0
    while i < len(spec):
        ch = spec[i]
        if ch != "&" or i + 1 >= len(spec):
            out[cur].text += ch
            i += 1
            continue
        code = spec[i + 1]
        up = code.upper()
        if code == "&":
            out[cur].text += "&"
            i += 2
        elif up in "LCR":
            cur = up
            for k, v in pending.items():
                setattr(out[cur], k, v)
            pending = {}
            i += 2
        elif up == "D":
            out[cur].text += now.strftime("%d/%m/%Y")
            i += 2
        elif up == "T":
            out[cur].text += now.strftime("%H:%M")
            i += 2
        elif up == "P":
            out[cur].text += str(page)
            i += 2
        elif up == "N":
            out[cur].text += str(pages)
            i += 2
        elif up in "BIU":
            attr = {"B": "bold", "I": "italic", "U": "underline"}[up]
            # un codice di formato prima di &L/&C/&R vale per la sezione che segue (come nell'esempio)
            nxt = spec[i + 2:i + 4].upper()
            if nxt[:1] == "&" and nxt[1:2] in ("L", "C", "R"):
                pending[attr] = True
            else:
                setattr(out[cur], attr, True)
            i += 2
        elif code.isdigit():
            j = i + 1
            while j < len(spec) and spec[j].isdigit() and j - i <= 3:
                j += 1
            size = int(spec[i + 1:j])
            nxt = spec[j:j + 2].upper()
            if nxt[:1] == "&" and nxt[1:2] in ("L", "C", "R"):
                pending["size"] = size
            else:
                out[cur].size = size
            i = j
        else:
            out[cur].text += spec[i:i + 2]
            i += 2
    for s in out.values():
        s.text = s.text.strip()
    return out
