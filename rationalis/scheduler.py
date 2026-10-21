"""Scadenzario: movimenti o giroconti che si ripetono secondo un piano di sviluppo.

Alla conferma vengono generati tutti i movimenti, non saldati. Modificare o cancellare una scadenza
agisce solo sui movimenti non ancora saldati: quelli saldati restano come sono.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from . import movements as mv
from . import transfers as tr
from .balances import convert
from .db import Archive, ValidationError
from .money import ZERO, from_db, to_db
from .recurrence import Plan, occurrences


@dataclass
class Schedule:
    descrizione: str
    risorsa_id: int
    plan: Plan
    tipo: str = "M"                     # 'M' movimento, 'G' giroconto
    gruppo_id: int | None = None
    sottogruppo_id: int | None = None
    importo: Decimal = ZERO             # per i gruppi misti il segno decide entrata/uscita
    modalita_id: int | None = None
    destinazione_id: int | None = None
    soggetto_id: int | None = None
    rif: str = ""
    risorsa_dest_id: int | None = None  # solo giroconto
    importo_dest: Decimal = ZERO        # solo giroconto; 0 = calcolato col cambio
    id: int | None = None

    def to_fields(self) -> dict:
        p = self.plan
        return dict(
            descrizione=self.descrizione, tipo=self.tipo, risorsa_id=self.risorsa_id, gruppo_id=self.gruppo_id,
            sottogruppo_id=self.sottogruppo_id, importo=to_db(self.importo), modalita_id=self.modalita_id,
            destinazione_id=self.destinazione_id, soggetto_id=self.soggetto_id, rif=self.rif,
            risorsa_dest_id=self.risorsa_dest_id, importo_dest=to_db(self.importo_dest),
            data_inizio=p.start.isoformat(), data_fine=p.end.isoformat() if p.end else None,
            ripetizioni=p.count, unita=p.unit, passo=p.step, giorno_settimana=p.weekday,
            giorno_mese=p.monthday, ordinale=p.ordinal)

    @classmethod
    def from_row(cls, r) -> "Schedule":
        plan = Plan(start=date.fromisoformat(r["data_inizio"]), unit=r["unita"], step=r["passo"],
                    end=date.fromisoformat(r["data_fine"]) if r["data_fine"] else None, count=r["ripetizioni"],
                    weekday=r["giorno_settimana"], monthday=r["giorno_mese"], ordinal=r["ordinale"])
        return cls(id=r["id"], descrizione=r["descrizione"], tipo=r["tipo"], risorsa_id=r["risorsa_id"],
                   plan=plan, gruppo_id=r["gruppo_id"], sottogruppo_id=r["sottogruppo_id"],
                   importo=from_db(r["importo"]), modalita_id=r["modalita_id"],
                   destinazione_id=r["destinazione_id"], soggetto_id=r["soggetto_id"], rif=r["rif"],
                   risorsa_dest_id=r["risorsa_dest_id"], importo_dest=from_db(r["importo_dest"]))


def signed_amount(arc: Archive, s: Schedule) -> Decimal:
    tipo = arc.row("gruppi", s.gruppo_id)["tipo"]
    if tipo == "E":
        return abs(s.importo)
    if tipo == "U":
        return -abs(s.importo)
    return s.importo


def _validate(arc: Archive, s: Schedule):
    s.plan.validate()
    if arc.row("risorse", s.risorsa_id) is None:
        raise ValidationError("La risorsa è obbligatoria")
    if s.tipo == "M":
        if arc.row("gruppi", s.gruppo_id) is None:
            raise ValidationError("Il gruppo è obbligatorio")
    else:
        if arc.row("risorse", s.risorsa_dest_id) is None or s.risorsa_dest_id == s.risorsa_id:
            raise ValidationError("Il giroconto richiede una risorsa di destinazione diversa")
        if s.importo <= 0:
            raise ValidationError("L'importo del giroconto deve essere maggiore di zero")


def save(arc: Archive, s: Schedule) -> int:
    """Salva la scadenza e rigenera i suoi movimenti non saldati."""
    _validate(arc, s)
    with arc.tx():
        if s.id is None:
            s.id = arc.insert("scadenze", **s.to_fields())
        else:
            arc.update("scadenze", s.id, **s.to_fields())
        regenerate(arc, s)
    return s.id


def regenerate(arc: Archive, s: Schedule):
    with arc.tx():
        arc.conn.execute("DELETE FROM movimenti WHERE scadenza_id=? AND saldato=0 AND giroconto_id IS NULL", (s.id,))
        for (gid,) in arc.conn.execute("SELECT id FROM giroconti WHERE scadenza_id=? AND saldato=0", (s.id,)).fetchall():
            tr.delete(arc, gid)
        settled = {r[0] for r in arc.conn.execute(
            "SELECT data FROM movimenti WHERE scadenza_id=? AND saldato=1", (s.id,)).fetchall()}
        for d in occurrences(s.plan):
            if d.isoformat() in settled:
                continue
            if s.tipo == "M":
                mv.save(arc, mv.Movement(
                    data=d, risorsa_id=s.risorsa_id, gruppo_id=s.gruppo_id, sottogruppo_id=s.sottogruppo_id,
                    importo=signed_amount(arc, s), saldato=False, modalita_id=s.modalita_id,
                    destinazione_id=s.destinazione_id, soggetto_id=s.soggetto_id,
                    descrizione=s.descrizione[:mv.MAX_DESCRIZIONE], rif=s.rif[:mv.MAX_RIF], scadenza_id=s.id))
            else:
                dest = s.importo_dest
                if dest <= 0:
                    dest = convert(arc, s.importo, arc.row("risorse", s.risorsa_id)["valuta_id"],
                                   arc.row("risorse", s.risorsa_dest_id)["valuta_id"])
                tr.save(arc, tr.Transfer(d, tr.Leg(s.risorsa_id, s.importo), [tr.Leg(s.risorsa_dest_id, dest)],
                                         saldato=False, descrizione=s.descrizione, scadenza_id=s.id),
                        check_balance=False)


def get(arc: Archive, id_: int) -> Schedule | None:
    r = arc.row("scadenze", id_)
    return Schedule.from_row(r) if r else None


def list_all(arc: Archive) -> list[Schedule]:
    return [Schedule.from_row(r) for r in arc.rows("scadenze", order="descrizione COLLATE NOCASE")]


def delete(arc: Archive, id_: int):
    """Cancella la scadenza e i suoi movimenti non saldati; quelli saldati restano (senza legame)."""
    with arc.tx():
        arc.conn.execute("DELETE FROM movimenti WHERE scadenza_id=? AND saldato=0 AND giroconto_id IS NULL", (id_,))
        for (gid,) in arc.conn.execute("SELECT id FROM giroconti WHERE scadenza_id=? AND saldato=0", (id_,)).fetchall():
            tr.delete(arc, gid)
        arc.conn.execute("DELETE FROM scadenze WHERE id=?", (id_,))


def unsettled_in_month(arc: Archive, year: int, month: int, risorsa_id: int | None = None) -> list[mv.Movement]:
    """Scadenze del mese: tutti i movimenti non ancora saldati del mese."""
    return [m for m in mv.list_month(arc, year, month, risorsa_id) if not m.saldato]
