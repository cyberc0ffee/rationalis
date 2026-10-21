"""Piano di sviluppo delle scadenze: calcolo delle date di ripetizione.

Unità: 'G' giorni, 'S' settimane, 'M' mesi (annuale = mesi con passo 12).
Per i mesi si indica un giorno del mese (1..31, -1 = ultimo) oppure un giorno della
settimana con un ordinale (1..4 = primo..quarto, -1 = ultimo), es. "primo lunedì".
La fine è una data oppure un numero di ripetizioni.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta

MAX_OCCURRENCES = 10_000

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
ORDINALI = {1: "primo", 2: "secondo", 3: "terzo", 4: "quarto", -1: "ultimo"}


@dataclass
class Plan:
    start: date
    unit: str  # 'G', 'S', 'M'
    step: int = 1
    end: date | None = None
    count: int | None = None
    weekday: int | None = None    # 0 = lunedì
    monthday: int | None = None   # 1..31 oppure -1 = ultimo
    ordinal: int | None = None    # 1..4 oppure -1, insieme a weekday

    def validate(self):
        if self.unit not in ("G", "S", "M"):
            raise ValueError("Unità di ripetizione non valida")
        if self.step < 1:
            raise ValueError("La ripetizione deve essere almeno ogni 1")
        if (self.end is None) == (self.count is None):
            raise ValueError("Indicare una data di fine oppure un numero di ripetizioni")
        if self.count is not None and self.count < 1:
            raise ValueError("Il numero di ripetizioni deve essere almeno 1")
        if self.end is not None and self.end < self.start:
            raise ValueError("La data di fine precede la data di inizio")
        if self.ordinal is not None and self.weekday is None:
            raise ValueError("Con l'ordinale va indicato il giorno della settimana")


def _clamp_day(year: int, month: int, day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, last if day == -1 else min(day, last))


def _nth_weekday(year: int, month: int, weekday: int, ordinal: int) -> date:
    if ordinal == -1:
        d = date(year, month, calendar.monthrange(year, month)[1])
        return d - timedelta(days=(d.weekday() - weekday) % 7)
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=ordinal - 1)


def _add_months(year: int, month: int, n: int) -> tuple[int, int]:
    m = month - 1 + n
    return year + m // 12, m % 12 + 1


def _candidates(plan: Plan):
    if plan.unit == "G":
        d = plan.start
        while True:
            yield d
            d += timedelta(days=plan.step)
    elif plan.unit == "S":
        wd = plan.start.weekday() if plan.weekday is None else plan.weekday
        d = plan.start + timedelta(days=(wd - plan.start.weekday()) % 7)
        while True:
            yield d
            d += timedelta(weeks=plan.step)
    else:
        y, m = plan.start.year, plan.start.month
        while True:
            if plan.ordinal is not None:
                d = _nth_weekday(y, m, plan.weekday, plan.ordinal)
            else:
                d = _clamp_day(y, m, plan.start.day if plan.monthday is None else plan.monthday)
            if d >= plan.start:
                yield d
            y, m = _add_months(y, m, plan.step)


def occurrences(plan: Plan) -> list[date]:
    plan.validate()
    out = []
    for d in _candidates(plan):
        if plan.end is not None and d > plan.end:
            break
        out.append(d)
        if plan.count is not None and len(out) >= plan.count:
            break
        if len(out) >= MAX_OCCURRENCES:
            raise ValueError(f"Il piano genera più di {MAX_OCCURRENCES} date")
    return out


def describe(plan: Plan) -> str:
    """Descrizione leggibile del piano, es. "ogni 2 mesi, il primo lunedì, dal 01/01/2003 al 31/12/2003"."""
    unit = {"G": ("giorno", "giorni"), "S": ("settimana", "settimane"), "M": ("mese", "mesi")}[plan.unit]
    s = f"ogni {unit[0]}" if plan.step == 1 else f"ogni {plan.step} {unit[1]}"
    if plan.unit == "S":
        s += f", di {GIORNI[plan.start.weekday() if plan.weekday is None else plan.weekday]}"
    elif plan.unit == "M":
        if plan.ordinal is not None:
            s += f", il {ORDINALI[plan.ordinal]} {GIORNI[plan.weekday]} del mese"
        elif plan.monthday == -1:
            s += ", l'ultimo giorno del mese"
        else:
            s += f", il giorno {plan.start.day if plan.monthday is None else plan.monthday}"
    s += f", dal {plan.start:%d/%m/%Y}"
    s += f" al {plan.end:%d/%m/%Y}" if plan.end else f" per {plan.count} volte"
    return s
