"""Disponibilità delle risorse, conversioni di valuta e controllo dei limiti.

Disponibilità di una risorsa alla data D = saldo iniziale + somma degli importi saldati con data ≤ D
(proiezione: anche i non saldati). Per «tutte le risorse» ogni disponibilità è convertita
in valuta principale al cambio corrente: importo_principale = importo / cambio.
"""
from datetime import date, timedelta
from decimal import Decimal

from .db import Archive
from .money import ZERO, from_db
from .movements import month_bounds


def convert(arc: Archive, amount: Decimal, from_valuta: int, to_valuta: int) -> Decimal:
    if from_valuta == to_valuta:
        return amount
    return amount / arc.rate(from_valuta) * arc.rate(to_valuta)


def to_principal(arc: Archive, amount: Decimal, valuta_id: int) -> Decimal:
    return amount / arc.rate(valuta_id)


def _sum(arc: Archive, risorsa_id: int, until: date | None, include_unsettled: bool,
         since: date | None = None) -> Decimal:
    where = ["risorsa_id = ?"]
    params: list = [risorsa_id]
    if until is not None:
        where.append("data <= ?")
        params.append(until.isoformat())
    if since is not None:
        where.append("data >= ?")
        params.append(since.isoformat())
    if not include_unsettled:
        where.append("saldato = 1")
    v = arc.conn.execute(f"SELECT COALESCE(SUM(importo), 0) FROM movimenti WHERE {' AND '.join(where)}",
                         params).fetchone()[0]
    return from_db(v)


def balance(arc: Archive, risorsa_id: int, until: date | None = None, include_unsettled: bool = False) -> Decimal:
    """Disponibilità della risorsa nella sua valuta."""
    r = arc.row("risorse", risorsa_id)
    return from_db(r["saldo_iniziale"]) + _sum(arc, risorsa_id, until, include_unsettled)


def balance_all(arc: Archive, until: date | None = None, include_unsettled: bool = False) -> Decimal:
    """Disponibilità complessiva in valuta principale."""
    total = ZERO
    for r in arc.rows("risorse", order="id"):
        total += to_principal(arc, balance(arc, r["id"], until, include_unsettled), r["valuta_id"])
    return total


def balance_any(arc: Archive, risorsa_id: int | None, until: date | None = None,
                include_unsettled: bool = False) -> Decimal:
    if risorsa_id is None:
        return balance_all(arc, until, include_unsettled)
    return balance(arc, risorsa_id, until, include_unsettled)


def last_settled_date(arc: Archive) -> date | None:
    r = arc.conn.execute("SELECT MAX(data) FROM movimenti WHERE saldato = 1").fetchone()[0]
    return date.fromisoformat(r) if r else None


def availability_bar(arc: Archive, year: int, month: int, risorsa_id: int | None,
                     today: date | None = None) -> dict:
    """Valori della barra delle disponibilità: fine mese precedente, fine mese, oggi."""
    first, last = month_bounds(year, month)
    today = today or date.today()
    return {
        "fine_mese_precedente": balance_any(arc, risorsa_id, first - timedelta(days=1)),
        "fine_mese": balance_any(arc, risorsa_id, last),
        "oggi": balance_any(arc, risorsa_id, today),
        "proiezione_fine_mese": balance_any(arc, risorsa_id, last, include_unsettled=True),
    }


def current_balances(arc: Archive, today: date | None = None) -> list[dict]:
    """Disponibilità correnti di tutte le risorse in uso: valuta propria e principale."""
    out = []
    for r in arc.rows("risorse", "in_uso = 1"):
        v = arc.row("valute", r["valuta_id"])
        b = balance(arc, r["id"], today)
        out.append({"risorsa_id": r["id"], "risorsa": r["nome"], "valuta": v["sigla"],
                    "disponibilita": b, "in_principale": to_principal(arc, b, v["id"])})
    return out


def daily(arc: Archive, year: int, month: int, risorsa_id: int | None) -> list[dict]:
    """Andamento giorno per giorno della disponibilità nel mese (solo saldati)."""
    first, last = month_bounds(year, month)
    running = balance_any(arc, risorsa_id, first - timedelta(days=1))
    out = []
    d = first
    while d <= last:
        e = u = ZERO
        risorse = [risorsa_id] if risorsa_id is not None else [r["id"] for r in arc.rows("risorse", order="id")]
        for rid in risorse:
            where = "risorsa_id = ? AND data = ? AND saldato = 1"
            if risorsa_id is None:
                where += " AND giroconto_id IS NULL"
            rows = arc.conn.execute(f"SELECT importo FROM movimenti WHERE {where}", (rid, d.isoformat())).fetchall()
            vid = arc.row("risorse", rid)["valuta_id"]
            for (imp,) in rows:
                val = from_db(imp) if risorsa_id is not None else to_principal(arc, from_db(imp), vid)
                if val > 0:
                    e += val
                else:
                    u -= val
        running = balance_any(arc, risorsa_id, d)
        out.append({"data": d, "entrate": e, "uscite": u, "disponibilita": running})
        d += timedelta(days=1)
    return out


def trend(arc: Archive, risorsa_id: int | None, start_year: int, start_month: int, months: int,
          include_unsettled: bool = False) -> list[dict]:
    """Andamento (o proiezione) mese per mese: entrate, uscite, differenza, disponibilità a fine mese.

    Con tutte le risorse i giroconti sono esclusi da entrate/uscite; eventuali differenze di cambio
    dei giroconti emergono solo nella disponibilità.
    """
    out = []
    y, m = start_year, start_month
    for _ in range(months):
        first, last = month_bounds(y, m)
        e = u = ZERO
        risorse = [risorsa_id] if risorsa_id is not None else [r["id"] for r in arc.rows("risorse", order="id")]
        for rid in risorse:
            where = "risorsa_id = ? AND data BETWEEN ? AND ?"
            if not include_unsettled:
                where += " AND saldato = 1"
            if risorsa_id is None:
                where += " AND giroconto_id IS NULL"
            vid = arc.row("risorse", rid)["valuta_id"]
            for col, sign in (("importo > 0", 1), ("importo < 0", -1)):
                s = from_db(arc.conn.execute(
                    f"SELECT COALESCE(SUM(importo),0) FROM movimenti WHERE {where} AND {col}",
                    (rid, first.isoformat(), last.isoformat())).fetchone()[0])
                if risorsa_id is None:
                    s = to_principal(arc, s, vid)
                if sign > 0:
                    e += s
                else:
                    u -= s
        out.append({"anno": y, "mese": m, "entrate": e, "uscite": u, "differenza": e - u,
                    "disponibilita": balance_any(arc, risorsa_id, last, include_unsettled)})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def limit_state(arc: Archive, risorsa_id: int, include_unsettled: bool = False) -> str:
    """'ok', 'sotto' o 'sopra' rispetto ai limiti di utilizzo della risorsa (se attivi)."""
    r = arc.row("risorse", risorsa_id)
    if not r["limite_attivo"]:
        return "ok"
    b = balance(arc, risorsa_id, None, include_unsettled)
    if b < from_db(r["limite_min"]):
        return "sotto"
    if b > from_db(r["limite_max"]):
        return "sopra"
    return "ok"
