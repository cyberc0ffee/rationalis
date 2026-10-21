"""Giroconti: un prelievo da una risorsa e fino a tre versamenti verso altre risorse.

Ogni ramo è un movimento con giroconto_id valorizzato e senza gruppo: il prelievo ha importo
negativo, i versamenti positivo, ciascuno nella valuta della propria risorsa.
Alla creazione lo sbilancio deve essere zero; in seguito può diventare diverso da zero se cambiano
i tassi (utile o perdita su cambi), e il giroconto non va ricalcolato.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from . import movements as mv
from .balances import balance, convert
from .db import Archive, ValidationError
from .money import ZERO, from_db, to_db

MAX_VERSAMENTI = 3


@dataclass
class Leg:
    risorsa_id: int
    importo: Decimal  # sempre positivo


@dataclass
class Transfer:
    data: date
    prelievo: Leg
    versamenti: list[Leg]
    saldato: bool = False
    descrizione: str = ""
    scadenza_id: int | None = None
    id: int | None = None


def imbalance(arc: Archive, t: Transfer) -> Decimal:
    """Prelievo meno versamenti convertiti nella valuta del prelievo (0 = bilanciato)."""
    v_from = arc.row("risorse", t.prelievo.risorsa_id)["valuta_id"]
    total = ZERO
    for leg in t.versamenti:
        total += convert(arc, leg.importo, arc.row("risorse", leg.risorsa_id)["valuta_id"], v_from)
    return t.prelievo.importo - total


def balancing_amount(arc: Archive, t: Transfer, index: int) -> Decimal:
    """Importo del versamento `index` che azzera lo sbilancio, nella valuta della sua risorsa."""
    others = [leg for i, leg in enumerate(t.versamenti) if i != index]
    rest = imbalance(arc, Transfer(t.data, t.prelievo, others))
    v_from = arc.row("risorse", t.prelievo.risorsa_id)["valuta_id"]
    v_to = arc.row("risorse", t.versamenti[index].risorsa_id)["valuta_id"]
    return convert(arc, rest, v_from, v_to)


def _validate(arc: Archive, t: Transfer, check_balance: bool):
    if not 1 <= len(t.versamenti) <= MAX_VERSAMENTI:
        raise ValidationError(f"Un giroconto ha da 1 a {MAX_VERSAMENTI} versamenti")
    ids = [t.prelievo.risorsa_id] + [leg.risorsa_id for leg in t.versamenti]
    if any(arc.row("risorse", i) is None for i in ids):
        raise ValidationError("Risorsa non valida nel giroconto")
    if len(set(ids)) != len(ids):
        raise ValidationError("Prelievo e versamenti devono riguardare risorse diverse")
    if t.prelievo.importo <= 0 or any(leg.importo <= 0 for leg in t.versamenti):
        raise ValidationError("Gli importi del giroconto devono essere maggiori di zero")
    if check_balance:
        tol = Decimal(1).scaleb(-arc.decimals) / 2
        if abs(imbalance(arc, t)) >= tol:
            raise ValidationError("Il giroconto non è bilanciato: lo sbilancio deve essere zero")


def _write_legs(arc: Archive, t: Transfer):
    common = dict(data=t.data.isoformat(), saldato=int(t.saldato), descrizione=t.descrizione[:mv.MAX_DESCRIZIONE],
                  giroconto_id=t.id, scadenza_id=t.scadenza_id)
    arc.insert("movimenti", risorsa_id=t.prelievo.risorsa_id, importo=-to_db(t.prelievo.importo), **common)
    for leg in t.versamenti:
        arc.insert("movimenti", risorsa_id=leg.risorsa_id, importo=to_db(leg.importo), **common)


def save(arc: Archive, t: Transfer, check_balance: bool | None = None) -> int:
    """Crea o aggiorna un giroconto. Lo sbilancio è verificato sempre alla creazione e in modifica
    solo se richiesto (un giroconto vecchio può risultare sbilanciato per cambi variati)."""
    if check_balance is None:
        check_balance = t.id is None
    _validate(arc, t, check_balance)
    with arc.tx():
        fields = dict(data=t.data.isoformat(), saldato=int(t.saldato), descrizione=t.descrizione,
                      scadenza_id=t.scadenza_id)
        if t.id is None:
            t.id = arc.insert("giroconti", **fields)
        else:
            arc.update("giroconti", t.id, **fields)
            arc.conn.execute("DELETE FROM movimenti WHERE giroconto_id=?", (t.id,))
        _write_legs(arc, t)
    return t.id


def get(arc: Archive, id_: int) -> Transfer | None:
    g = arc.row("giroconti", id_)
    if g is None:
        return None
    legs = arc.rows("movimenti", "giroconto_id = ?", (id_,), order="id")
    out = [lg for lg in legs if lg["importo"] < 0]
    ins = [lg for lg in legs if lg["importo"] >= 0]
    return Transfer(
        id=id_, data=date.fromisoformat(g["data"]), saldato=bool(g["saldato"]), descrizione=g["descrizione"],
        scadenza_id=g["scadenza_id"],
        prelievo=Leg(out[0]["risorsa_id"], -from_db(out[0]["importo"])),
        versamenti=[Leg(lg["risorsa_id"], from_db(lg["importo"])) for lg in ins])


def delete(arc: Archive, id_: int):
    with arc.tx():
        arc.conn.execute("DELETE FROM movimenti WHERE giroconto_id=?", (id_,))
        arc.conn.execute("DELETE FROM giroconti WHERE id=?", (id_,))


def list_period(arc: Archive, start: date, end: date) -> list[Transfer]:
    ids = [r["id"] for r in arc.rows("giroconti", "data BETWEEN ? AND ?", (start.isoformat(), end.isoformat()),
                                     order="data, id")]
    return [get(arc, i) for i in ids]


def list_month(arc: Archive, year: int, month: int) -> list[Transfer]:
    return list_period(arc, *mv.month_bounds(year, month))


def default_card_charge_date(today: date | None = None) -> date:
    """Ultimo giorno del mese precedente a oggi: la data in cui di solito le banche addebitano la carta."""
    today = today or date.today()
    return today.replace(day=1) - timedelta(days=1)


def card_balance(arc: Archive, carta_id: int, until: date | None = None) -> Decimal:
    """Saldo attuale della carta (negativo = speso e non ancora addebitato)."""
    return balance(arc, carta_id, until)


def charge_credit_card(arc: Archive, carta_id: int, importo: Decimal, data: date | None = None,
                       commissione: Decimal = ZERO, gruppo_id: int | None = None,
                       sottogruppo_id: int | None = None, descrizione: str = "") -> tuple[int, int | None]:
    """Addebita in banca le spese della carta: giroconto saldato banca → carta, più eventuale
    movimento di uscita per le commissioni. Restituisce (id giroconto, id movimento commissioni)."""
    carta = arc.row("risorse", carta_id)
    if carta is None or carta["tipo"] != "carta":
        raise ValidationError("La risorsa scelta non è una carta di credito")
    if carta["banca_id"] is None:
        raise ValidationError("Alla carta non è associata una banca")
    if importo <= 0:
        raise ValidationError("L'importo da addebitare deve essere maggiore di zero")
    data = data or default_card_charge_date()
    owed = -card_balance(arc, carta_id)
    if importo > owed + Decimal("0.005"):
        raise ValidationError("L'importo supera le spese ancora da addebitare sulla carta")
    banca_v = arc.row("risorse", carta["banca_id"])["valuta_id"]
    importo_banca = convert(arc, importo, carta["valuta_id"], banca_v)
    with arc.tx():
        tid = save(arc, Transfer(data, Leg(carta["banca_id"], importo_banca), [Leg(carta_id, importo)],
                                 saldato=True, descrizione=descrizione or f"Addebito {carta['nome']}"),
                   check_balance=False)
        mid = None
        if commissione > 0:
            if gruppo_id is None:
                raise ValidationError("Per le commissioni va indicato un gruppo")
            mid = mv.save(arc, mv.Movement(data=data, risorsa_id=carta["banca_id"], gruppo_id=gruppo_id,
                                           sottogruppo_id=sottogruppo_id, importo=-commissione, saldato=True,
                                           descrizione=f"Commissioni {carta['nome']}"))
    return tid, mid

