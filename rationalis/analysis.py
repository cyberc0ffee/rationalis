"""Analisi dei movimenti: filtri, riepiloghi per periodi, monitor statistiche, dati per grafici, budget.

Regole comuni:
- i giroconti non sono entrate né uscite e sono sempre esclusi;
- salvo filtro diverso si considerano solo i movimenti saldati;
- gli importi di risorse diverse sono sommati in valuta principale (importo / cambio corrente);
  con una sola risorsa selezionata si può restare nella sua valuta (vedi `single_currency`).
"""
import calendar
import json
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from . import movements as mv
from .db import Archive, ValidationError
from .money import ZERO, from_db, to_db
from .ui_text import month_name

# --- filtri ---------------------------------------------------------------------


@dataclass
class Filter:
    data_da: date | None = None
    data_a: date | None = None
    saldato: str = "saldati"          # 'saldati', 'non_saldati', 'tutti'
    tipo: str = "tutti"               # 'entrate', 'uscite', 'tutti'
    gruppi: list[int] | None = None
    sottogruppi: list[int] | None = None
    raggruppamento_id: int | None = None
    risorse: list[int] | None = None
    destinazioni: list[int] | None = None
    soggetti: list[int] | None = None
    modalita: list[int] | None = None
    descrizione: str = ""             # contenuto in descrizione (maiuscole indifferenti)
    rif: str = ""
    controllo: str = ""               # carattere esatto della colonna C

    def validate(self):
        if self.raggruppamento_id is not None and (self.gruppi or self.sottogruppi):
            raise ValidationError("Non si possono usare insieme il filtro dei raggruppamenti e quello dei gruppi")
        if self.data_da and self.data_a and self.data_da > self.data_a:
            raise ValidationError("La data iniziale del filtro segue quella finale")

    def to_sql(self) -> tuple[str, list]:
        """Clausola WHERE sulla tabella movimenti (alias m)."""
        self.validate()
        w, p = ["m.giroconto_id IS NULL"], []
        if self.data_da:
            w.append("m.data >= ?")
            p.append(self.data_da.isoformat())
        if self.data_a:
            w.append("m.data <= ?")
            p.append(self.data_a.isoformat())
        if self.saldato == "saldati":
            w.append("m.saldato = 1")
        elif self.saldato == "non_saldati":
            w.append("m.saldato = 0")
        if self.tipo == "entrate":
            w.append("m.importo > 0")
        elif self.tipo == "uscite":
            w.append("m.importo < 0")

        def in_list(col, ids):
            if ids is not None:
                if not ids:
                    w.append("0")
                else:
                    w.append(f"{col} IN ({','.join('?' * len(ids))})")
                    p.extend(ids)

        if self.gruppi is not None and self.sottogruppi:
            # gruppi interi oppure singoli sottogruppi
            parts = []
            if self.gruppi:
                parts.append(f"m.gruppo_id IN ({','.join('?' * len(self.gruppi))})")
                p.extend(self.gruppi)
            parts.append(f"m.sottogruppo_id IN ({','.join('?' * len(self.sottogruppi))})")
            p.extend(self.sottogruppi)
            w.append("(" + " OR ".join(parts) + ")")
        else:
            in_list("m.gruppo_id", self.gruppi)
            in_list("m.sottogruppo_id", self.sottogruppi)
        if self.raggruppamento_id is not None:
            w.append("(m.gruppo_id IN (SELECT gruppo_id FROM raggruppamenti_voci WHERE raggruppamento_id = ? "
                     "AND sottogruppo_id IS NULL) OR m.sottogruppo_id IN (SELECT sottogruppo_id FROM "
                     "raggruppamenti_voci WHERE raggruppamento_id = ? AND sottogruppo_id IS NOT NULL))")
            p += [self.raggruppamento_id, self.raggruppamento_id]
        in_list("m.risorsa_id", self.risorse)
        in_list("m.destinazione_id", self.destinazioni)
        in_list("m.soggetto_id", self.soggetti)
        in_list("m.modalita_id", self.modalita)
        if self.descrizione:
            w.append("m.descrizione LIKE ?")
            p.append(f"%{self.descrizione}%")
        if self.rif:
            w.append("m.rif LIKE ?")
            p.append(f"%{self.rif}%")
        if self.controllo:
            w.append("m.controllo = ?")
            p.append(self.controllo[:1])
        return " AND ".join(w), p

    def single_currency(self, arc: Archive) -> int | None:
        """Valuta comune se tutte le risorse filtrate hanno la stessa valuta, altrimenti None."""
        if not self.risorse:
            return None
        vals = {arc.row("risorse", r)["valuta_id"] for r in self.risorse}
        return vals.pop() if len(vals) == 1 else None

    def to_json(self) -> str:
        d = asdict(self)
        for k in ("data_da", "data_a"):
            d[k] = d[k].isoformat() if d[k] else None
        return json.dumps(d)

    @classmethod
    def from_json(cls, text: str) -> "Filter":
        d = json.loads(text)
        for k in ("data_da", "data_a"):
            d[k] = date.fromisoformat(d[k]) if d.get(k) else None
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def save_search(arc: Archive, nome: str, flt: Filter, id_: int | None = None) -> int:
    if not nome.strip():
        raise ValidationError("Dare un nome alla ricerca")
    flt.validate()
    with arc.tx():
        if id_ is None:
            return arc.insert("ricerche", nome=nome.strip(), filtro=flt.to_json())
        arc.update("ricerche", id_, nome=nome.strip(), filtro=flt.to_json())
        return id_


def load_search(arc: Archive, id_: int) -> Filter:
    return Filter.from_json(arc.row("ricerche", id_)["filtro"])


# --- estrazione e conversione ---------------------------------------------------------
class _Converter:
    """Converte gli importi di una risorsa nella valuta di destinazione (principale se None)."""

    def __init__(self, arc: Archive, target_valuta: int | None = None):
        self.arc = arc
        self.target_rate = arc.rate(target_valuta) if target_valuta else Decimal(1)
        self.res_rate: dict[int, Decimal] = {}

    def __call__(self, risorsa_id: int, amount: Decimal) -> Decimal:
        r = self.res_rate.get(risorsa_id)
        if r is None:
            r = self.arc.rate(self.arc.row("risorse", risorsa_id)["valuta_id"])
            self.res_rate[risorsa_id] = r
        return amount / r * self.target_rate


def filtered(arc: Archive, flt: Filter) -> list[mv.Movement]:
    where, params = flt.to_sql()
    rows = arc.conn.execute(f"SELECT m.* FROM movimenti m WHERE {where} ORDER BY m.data, m.id", params).fetchall()
    return [mv.Movement.from_row(r) for r in rows]


def totals(arc: Archive, movs: list[mv.Movement], valuta_id: int | None = None) -> dict:
    conv = _Converter(arc, valuta_id)
    e = u = ZERO
    for m in movs:
        v = conv(m.risorsa_id, m.importo)
        if v > 0:
            e += v
        else:
            u -= v
    return {"entrate": e, "uscite": u, "saldo": e - u, "numero": len(movs)}


def month_totals(arc: Archive, year: int, month: int, risorsa_id: int | None) -> dict:
    """Totali di entrate e uscite saldate dell'anno e del mese, per la risorsa (o tutte)."""
    flt_year = Filter(date(year, 1, 1), date(year, 12, 31), risorse=[risorsa_id] if risorsa_id else None)
    first, last = mv.month_bounds(year, month)
    flt_month = Filter(first, last, risorse=[risorsa_id] if risorsa_id else None)
    cur = arc.row("risorse", risorsa_id)["valuta_id"] if risorsa_id else None
    return {"anno": totals(arc, filtered(arc, flt_year), cur), "mese": totals(arc, filtered(arc, flt_month), cur)}


# --- voci di raggruppamento --------------------------------------------------------------
GROUP_BY = {
    "gruppo": "Gruppo", "sottogruppo": "Sottogruppo", "risorsa": "Risorsa", "destinazione": "Destinazione",
    "soggetto": "Soggetto", "mese": "Mese", "valore": "Fascia di valore",
}
VALUE_BANDS = [Decimal(x) for x in (10, 50, 100, 500, 1000, 5000)]
NONE_LABEL = "(non indicato)"


def _band(v: Decimal) -> tuple[int, str]:
    a = abs(v)
    lo = ZERO
    for i, hi in enumerate(VALUE_BANDS):
        if a < hi:
            return i, f"da {lo:,.0f} a {hi:,.0f}".replace(",", ".")
        lo = hi
    return len(VALUE_BANDS), f"oltre {lo:,.0f}".replace(",", ".")


class _Labeler:
    def __init__(self, arc: Archive):
        self.arc = arc
        self.cache: dict = {}

    def name(self, table, id_):
        k = (table, id_)
        if k not in self.cache:
            self.cache[k] = self.arc.name_of(table, id_) if id_ else ""
        return self.cache[k]

    def key(self, by: str, m: mv.Movement, value: Decimal) -> tuple:
        """(chiave di ordinamento, etichetta) della voce per il movimento."""
        if by == "gruppo":
            n = self.name("gruppi", m.gruppo_id)
            return (n.lower(),), n
        if by == "sottogruppo":
            g, s = self.name("gruppi", m.gruppo_id), self.name("sottogruppi", m.sottogruppo_id)
            return (g.lower(), s.lower()), f"{g} / {s or NONE_LABEL}"
        if by == "mese":
            return (m.data.year, m.data.month), f"{month_name(m.data.month)} {m.data.year}"
        if by == "valore":
            i, label = _band(value)
            return (i,), label
        table = {"risorsa": "risorse", "destinazione": "destinazioni", "soggetto": "soggetti"}[by]
        n = self.name(table, getattr(m, f"{by}_id"))
        return ((1, "") if not n else (0, n.lower())), n or NONE_LABEL


# --- periodi ---------------------------------------------------------------------------
PERIOD_MONTHS = {"mese": 1, "bimestre": 2, "trimestre": 3, "quadrimestre": 4, "semestre": 6, "anno": 12}
PERIOD_NAMES = {"mese": "Mese", "bimestre": "Bimestre", "trimestre": "Trimestre", "quadrimestre": "Quadrimestre",
                "semestre": "Semestre", "anno": "Anno"}


@dataclass
class Period:
    label: str
    start: date
    end: date


def period(kind: str, year: int, index: int = 1) -> Period:
    """index: 1..12 per i mesi, 1..6 bimestri, 1..4 trimestri, 1..3 quadrimestri, 1..2 semestri (ignorato per l'anno)."""
    n = PERIOD_MONTHS[kind]
    if kind == "anno":
        index = 1
    count = 12 // n
    if not 1 <= index <= count:
        raise ValidationError(f"{PERIOD_NAMES[kind]} {index} non esiste")
    m1 = (index - 1) * n + 1
    m2 = m1 + n - 1
    start, end = date(year, m1, 1), date(year, m2, calendar.monthrange(year, m2)[1])
    if kind == "anno":
        label = str(year)
    elif kind == "mese":
        label = f"{month_name(m1)} {year}"
    else:
        label = f"{index}° {kind} {year}"
    return Period(label, start, end)


def twelve_months(year: int, month: int) -> list[Period]:
    out = []
    for _ in range(12):
        out.append(period("mese", year, month))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


# --- riepiloghi -----------------------------------------------------------------------
@dataclass
class SummaryRow:
    label: str
    values: list[Decimal]
    sort_key: tuple = field(default=(), repr=False)

    @property
    def total(self) -> Decimal:
        return sum(self.values, ZERO)

    @property
    def mean(self) -> Decimal:
        return self.total / len(self.values) if self.values else ZERO


def summary(arc: Archive, by: str, periods: list[Period], flt: Filter | None = None) -> tuple[list[SummaryRow], SummaryRow]:
    """Riepilogo: per ogni voce (gruppo, sottogruppo, risorsa, destinazione, soggetto) la differenza
    entrate − uscite in ciascun periodo, in valuta principale. Restituisce (righe, riga dei totali)."""
    if by not in ("gruppo", "sottogruppo", "risorsa", "destinazione", "soggetto"):
        raise ValidationError("Tipo di riepilogo non valido")
    base = flt or Filter()
    conv = _Converter(arc, base.single_currency(arc))
    lab = _Labeler(arc)
    rows: dict[str, SummaryRow] = {}
    for i, per in enumerate(periods):
        f = Filter(**{**asdict(base), "data_da": per.start, "data_a": per.end})
        for m in filtered(arc, f):
            v = conv(m.risorsa_id, m.importo)
            key, label = lab.key(by, m, v)
            r = rows.get(label)
            if r is None:
                r = rows[label] = SummaryRow(label, [ZERO] * len(periods), key)
            r.values[i] += v
    out = sorted(rows.values(), key=lambda r: r.sort_key)
    tot = SummaryRow("Totale", [sum((r.values[i] for r in out), ZERO) for i in range(len(periods))])
    return out, tot


# --- monitor statistiche -----------------------------------------------------------------
@dataclass
class MonitorRow:
    label: str
    n_entrate: int = 0
    entrate: Decimal = ZERO
    n_uscite: int = 0
    uscite: Decimal = ZERO
    sort_key: tuple = field(default=(), repr=False)

    @property
    def n(self) -> int:
        return self.n_entrate + self.n_uscite

    @property
    def saldo(self) -> Decimal:
        return self.entrate - self.uscite


def monitor(arc: Archive, start: date, end: date, by: str, risorsa_id: int | None = None,
            flt: Filter | None = None) -> tuple[list[MonitorRow], MonitorRow]:
    """Movimenti saldati del periodo raggruppati per voce, con conteggi e importi di entrate e uscite.
    Con una risorsa gli importi sono nella sua valuta, altrimenti in valuta principale."""
    if by not in GROUP_BY:
        raise ValidationError("Criterio di raggruppamento non valido")
    base = flt or Filter()
    f = Filter(**{**asdict(base), "data_da": start, "data_a": end,
                  "risorse": [risorsa_id] if risorsa_id else base.risorse})
    cur = arc.row("risorse", risorsa_id)["valuta_id"] if risorsa_id else f.single_currency(arc)
    conv = _Converter(arc, cur)
    lab = _Labeler(arc)
    rows: dict[str, MonitorRow] = {}
    tot = MonitorRow("Totale")
    for m in filtered(arc, f):
        v = conv(m.risorsa_id, m.importo)
        key, label = lab.key(by, m, v)
        r = rows.get(label)
        if r is None:
            r = rows[label] = MonitorRow(label, sort_key=key)
        for row in (r, tot):
            if v > 0:
                row.n_entrate += 1
                row.entrate += v
            elif v < 0:
                row.n_uscite += 1
                row.uscite -= v
    return sorted(rows.values(), key=lambda r: r.sort_key), tot


def share(part: Decimal | int, whole: Decimal | int) -> Decimal:
    return Decimal(part) / Decimal(whole) * 100 if whole else ZERO


# --- dati per i grafici -------------------------------------------------------------------
def chart_data(arc: Archive, start: date, end: date, by: str, kind: str = "uscite",
               risorsa_id: int | None = None, max_items: int = 0) -> list[tuple[str, Decimal]]:
    """Coppie (voce, importo) ordinate per importo decrescente; kind 'uscite' o 'entrate'.
    Con max_items > 0 le voci oltre il limite sono riunite in «Altro»."""
    rows, _ = monitor(arc, start, end, by, risorsa_id)
    pairs = [(r.label, r.uscite if kind == "uscite" else r.entrate) for r in rows]
    pairs = [(lbl, v) for lbl, v in pairs if v > 0]
    if by in ("mese",):
        return pairs
    pairs.sort(key=lambda p: p[1], reverse=True)
    if max_items and len(pairs) > max_items:
        rest = sum((v for _, v in pairs[max_items - 1:]), ZERO)
        pairs = pairs[:max_items - 1] + [("Altro", rest)]
    return pairs


# --- budget -----------------------------------------------------------------------------
def budget_of(arc: Archive, gruppo_id: int) -> list[Decimal]:
    """Budget mensile del gruppo (12 importi positivi, in valuta principale)."""
    vals = [ZERO] * 12
    for r in arc.conn.execute("SELECT mese, importo FROM budget WHERE gruppo_id = ?", (gruppo_id,)).fetchall():
        vals[r["mese"] - 1] = from_db(r["importo"])
    return vals


def set_budget(arc: Archive, gruppo_id: int, values: list[Decimal]):
    if len(values) != 12:
        raise ValidationError("Il budget richiede 12 importi mensili")
    with arc.tx():
        arc.conn.execute("DELETE FROM budget WHERE gruppo_id = ?", (gruppo_id,))
        for i, v in enumerate(values, 1):
            if v:
                arc.conn.execute("INSERT INTO budget VALUES (?, ?, ?)", (gruppo_id, i, to_db(v)))


def assisted_budget(amount: Decimal, mode: str) -> list[Decimal]:
    """'annuale': importo diviso in 12 mesi (l'arrotondamento va sull'ultimo); 'mensile': ripetuto 12 volte."""
    if mode == "mensile":
        return [amount] * 12
    each = (amount / 12).quantize(Decimal("0.01"))
    return [each] * 11 + [amount - each * 11]


def signed_budget(tipo: str, v: Decimal) -> Decimal:
    """Budget con il segno del movimento atteso: entrata +, uscita −, misto come inserito."""
    return v if tipo in ("E", "M") else -v


@dataclass
class BudgetLine:
    gruppo_id: int
    gruppo: str
    tipo: str
    consuntivo: list[Decimal]
    budget: list[Decimal]

    @property
    def scostamento(self) -> list[Decimal]:
        """Consuntivo − budget (con segno): positivo = meno spesa o più entrata del previsto."""
        return [c - b for c, b in zip(self.consuntivo, self.budget)]


def budget_sheet(arc: Archive) -> list[tuple[str, str, list[Decimal]]]:
    """Prospetto annuale: (gruppo, tipo, 12 importi con segno) dei gruppi con budget."""
    out = []
    for g in arc.rows("gruppi"):
        vals = budget_of(arc, g["id"])
        if any(vals):
            out.append((g["nome"], g["tipo"], [signed_budget(g["tipo"], v) for v in vals]))
    return out


def budget_variance(arc: Archive, year: int, month_from: int = 1, month_to: int = 12,
                    only_with_budget: bool = True) -> list[BudgetLine]:
    """Confronto mese per mese tra movimenti saldati (in valuta principale) e budget di ogni gruppo."""
    if not 1 <= month_from <= month_to <= 12:
        raise ValidationError("Intervallo di mesi non valido")
    months = list(range(month_from, month_to + 1))
    conv = _Converter(arc)
    actual: dict[int, list[Decimal]] = {}
    f = Filter(date(year, month_from, 1), date(year, month_to, calendar.monthrange(year, month_to)[1]))
    for m in filtered(arc, f):
        a = actual.setdefault(m.gruppo_id, [ZERO] * len(months))
        a[m.data.month - month_from] += conv(m.risorsa_id, m.importo)
    out = []
    for g in arc.rows("gruppi"):
        b = [signed_budget(g["tipo"], v) for v in budget_of(arc, g["id"])][month_from - 1:month_to]
        c = actual.get(g["id"], [ZERO] * len(months))
        if only_with_budget and not any(b):
            continue
        if not any(b) and not any(c):
            continue
        out.append(BudgetLine(g["id"], g["nome"], g["tipo"], c, b))
    return out


# --- elenco gruppi e sottogruppi -------------------------------------------------------------
def groups_outline(arc: Archive) -> dict[str, list[tuple[str, list[str]]]]:
    """Gruppi e sottogruppi in ordine alfabetico, divisi per tipo."""
    out = {"E": [], "U": [], "M": []}
    for g in arc.rows("gruppi"):
        subs = [s["nome"] for s in arc.rows("sottogruppi", "gruppo_id = ?", (g["id"],))]
        out[g["tipo"]].append((g["nome"], subs))
    return out
