"""Movimenti: validazione, inserimento, modifica, saldo, copia/incolla, ricerca."""
import calendar
from dataclasses import dataclass, field, fields, replace
from datetime import date
from decimal import Decimal

from .db import Archive, ValidationError
from .money import ZERO, from_db, to_db

MAX_DESCRIZIONE = 80
MAX_RIF = 30


@dataclass
class Movement:
    data: date
    risorsa_id: int
    gruppo_id: int | None = None
    sottogruppo_id: int | None = None
    importo: Decimal = ZERO          # > 0 entrata, < 0 uscita
    saldato: bool = False
    modalita_id: int | None = None
    destinazione_id: int | None = None
    soggetto_id: int | None = None
    descrizione: str = ""
    rif: str = ""
    controllo: str = ""
    giroconto_id: int | None = None
    scadenza_id: int | None = None
    id: int | None = field(default=None, compare=False)

    @property
    def entrata(self) -> Decimal:
        return self.importo if self.importo > 0 else ZERO

    @property
    def uscita(self) -> Decimal:
        return -self.importo if self.importo < 0 else ZERO

    @property
    def is_transfer(self) -> bool:
        return self.giroconto_id is not None

    @classmethod
    def from_row(cls, r) -> "Movement":
        return cls(
            id=r["id"], data=date.fromisoformat(r["data"]), risorsa_id=r["risorsa_id"],
            gruppo_id=r["gruppo_id"], sottogruppo_id=r["sottogruppo_id"], importo=from_db(r["importo"]),
            saldato=bool(r["saldato"]), modalita_id=r["modalita_id"], destinazione_id=r["destinazione_id"],
            soggetto_id=r["soggetto_id"], descrizione=r["descrizione"], rif=r["rif"],
            controllo=r["controllo"], giroconto_id=r["giroconto_id"], scadenza_id=r["scadenza_id"])

    def to_fields(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "id"}
        d["data"] = self.data.isoformat()
        d["importo"] = to_db(self.importo)
        d["saldato"] = int(self.saldato)
        return d


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def clamp_to_month(d: date, year: int, month: int) -> date:
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def validate(arc: Archive, m: Movement):
    if m.data is None:
        raise ValidationError("La data è obbligatoria")
    if arc.row("risorse", m.risorsa_id) is None:
        raise ValidationError("La risorsa è obbligatoria")
    if m.giroconto_id is None:
        g = arc.row("gruppi", m.gruppo_id)
        if g is None:
            raise ValidationError("Il gruppo è obbligatorio")
        if g["tipo"] == "E" and m.importo < 0:
            raise ValidationError(f"Il gruppo «{g['nome']}» è di entrata: non ammette uscite")
        if g["tipo"] == "U" and m.importo > 0:
            raise ValidationError(f"Il gruppo «{g['nome']}» è di uscita: non ammette entrate")
    if m.sottogruppo_id is not None:
        s = arc.row("sottogruppi", m.sottogruppo_id)
        if s is None or s["gruppo_id"] != m.gruppo_id:
            raise ValidationError("Il sottogruppo non appartiene al gruppo scelto")
    if m.modalita_id is not None:
        mo = arc.row("modalita", m.modalita_id)
        if mo is None or mo["risorsa_id"] != m.risorsa_id:
            raise ValidationError("La modalità di pagamento non appartiene alla risorsa scelta")
    if len(m.descrizione) > MAX_DESCRIZIONE:
        raise ValidationError(f"La descrizione supera {MAX_DESCRIZIONE} caratteri")
    if len(m.rif) > MAX_RIF:
        raise ValidationError(f"Il riferimento supera {MAX_RIF} caratteri")
    if len(m.controllo) > 1:
        raise ValidationError("La colonna di controllo accetta un solo carattere")


def save(arc: Archive, m: Movement) -> int:
    """Inserisce o aggiorna un movimento normale (non un ramo di giroconto)."""
    if m.is_transfer:
        raise ValidationError("I giroconti si modificano dalla gestione giroconti")
    r = arc.row("risorse", m.risorsa_id)
    if m.id is None and m.modalita_id is None and r is not None:
        m.modalita_id = r["modalita_predef_id"]
    validate(arc, m)
    with arc.tx():
        if m.id is None:
            m.id = arc.insert("movimenti", **m.to_fields())
        else:
            if get(arc, m.id).is_transfer:
                raise ValidationError("I giroconti si modificano dalla gestione giroconti")
            arc.update("movimenti", m.id, **m.to_fields())
    return m.id


def get(arc: Archive, id_: int) -> Movement | None:
    r = arc.row("movimenti", id_)
    return Movement.from_row(r) if r else None


def list_period(arc: Archive, start: date, end: date, risorsa_id: int | None = None,
                include_transfers: bool | None = None) -> list[Movement]:
    """Movimenti del periodo. Con risorsa=None (tutte) i rami dei giroconti sono esclusi."""
    if include_transfers is None:
        include_transfers = risorsa_id is not None
    where = "data BETWEEN ? AND ?"
    params: list = [start.isoformat(), end.isoformat()]
    if risorsa_id is not None:
        where += " AND risorsa_id = ?"
        params.append(risorsa_id)
    if not include_transfers:
        where += " AND giroconto_id IS NULL"
    return [Movement.from_row(r) for r in arc.rows("movimenti", where, params, order="data, id")]


def list_month(arc: Archive, year: int, month: int, risorsa_id: int | None = None) -> list[Movement]:
    return list_period(arc, *month_bounds(year, month), risorsa_id)


def delete(arc: Archive, ids) -> tuple[int, int]:
    """Cancella movimenti normali. Restituisce (cancellati, saltati perché giroconti)."""
    done = skipped = 0
    with arc.tx():
        for i in ids:
            m = get(arc, i)
            if m is None:
                continue
            if m.is_transfer:
                skipped += 1
                continue
            arc.conn.execute("DELETE FROM movimenti WHERE id=?", (i,))
            done += 1
    return done, skipped


def toggle_settled(arc: Archive, ids, value: bool | None = None):
    """Inverte (o imposta) lo stato di saldo. Per un ramo di giroconto vale per l'intero giroconto."""
    seen_transfers = set()
    with arc.tx():
        for i in ids:
            m = get(arc, i)
            if m is None:
                continue
            new = (not m.saldato) if value is None else value
            if m.is_transfer:
                if m.giroconto_id in seen_transfers:
                    continue
                seen_transfers.add(m.giroconto_id)
                arc.update("giroconti", m.giroconto_id, saldato=int(new))
                arc.conn.execute("UPDATE movimenti SET saldato=? WHERE giroconto_id=?", (int(new), m.giroconto_id))
            else:
                arc.update("movimenti", i, saldato=int(new))


def move_to_date(arc: Archive, id_: int, new_date: date):
    m = get(arc, id_)
    if m.is_transfer:
        raise ValidationError("I giroconti si spostano dalla gestione giroconti")
    arc.update("movimenti", id_, data=new_date.isoformat())


def paste_into_month(arc: Archive, movements: list[Movement], year: int, month: int) -> list[int]:
    """Incolla e accoda: copie nel mese indicato, giorno adattato all'ultimo del mese se serve."""
    new_ids = []
    with arc.tx():
        for m in movements:
            if m.is_transfer:
                continue
            c = replace(m, id=None, data=clamp_to_month(m.data, year, month), scadenza_id=None)
            new_ids.append(save(arc, c))
    return new_ids


def duplicate_last(arc: Archive, year: int, month: int, risorsa_id: int | None) -> int | None:
    movs = [m for m in list_month(arc, year, month, risorsa_id) if not m.is_transfer]
    if not movs:
        return None
    last = max(movs, key=lambda m: m.id)
    return save(arc, replace(last, id=None, scadenza_id=None))


def find(arc: Archive, text: str, mode: str = "tutti", risorsa_id: int | None = None,
         after: tuple[date, int] | None = None, backwards: bool = False) -> Movement | None:
    """Trova il prossimo movimento che corrisponde (maiuscole e minuscole indifferenti).

    mode: 'tutti' (tutti i campi di testo), 'descrizioni' (descrizione e riferimento),
    'importi' (entrata o uscita uguale al valore), 'non_saldato' (primo non saldato).
    """
    where, params = [], []
    if risorsa_id is not None:
        where.append("m.risorsa_id = ?")
        params.append(risorsa_id)
    if mode == "non_saldato":
        where.append("m.saldato = 0")
    elif mode == "importi":
        from .money import parse_amount
        v = to_db(abs(parse_amount(text)))
        where.append("ABS(m.importo) = ?")
        params.append(v)
    else:
        like = f"%{text}%"
        cols = ["m.descrizione", "m.rif"]
        if mode == "tutti":
            cols += ["m.controllo", "g.nome", "s.nome", "r.nome", "d.nome", "so.nome", "mo.nome"]
        where.append("(" + " OR ".join(f"{c} LIKE ?" for c in cols) + ")")
        params += [like] * len(cols)
    if after is not None:
        op = "<" if backwards else ">"
        where.append(f"(m.data {op} ? OR (m.data = ? AND m.id {op} ?))")
        params += [after[0].isoformat(), after[0].isoformat(), after[1]]
    order = "DESC" if backwards else "ASC"
    sql = f"""SELECT m.* FROM movimenti m
        LEFT JOIN gruppi g ON g.id = m.gruppo_id LEFT JOIN sottogruppi s ON s.id = m.sottogruppo_id
        JOIN risorse r ON r.id = m.risorsa_id LEFT JOIN destinazioni d ON d.id = m.destinazione_id
        LEFT JOIN soggetti so ON so.id = m.soggetto_id LEFT JOIN modalita mo ON mo.id = m.modalita_id
        WHERE {' AND '.join(where) or '1'} ORDER BY m.data {order}, m.id {order} LIMIT 1"""
    r = arc.conn.execute(sql, params).fetchone()
    return Movement.from_row(r) if r else None


def delete_all(arc: Archive):
    """Cancella tutti i movimenti, i giroconti e le scadenze lasciando intatte le tabelle."""
    with arc.tx():
        arc.conn.execute("DELETE FROM movimenti")
        arc.conn.execute("DELETE FROM giroconti")
        arc.conn.execute("DELETE FROM scadenze")


def bulk_change(arc: Archive, field_name: str, old_id: int, new_id: int | None = None,
                old_sub_id: int | None = None, new_sub_id: int | None = None, delete_them: bool = False) -> int:
    """Variazioni automatiche: sostituisce o cancella in tutti i movimenti un gruppo/sottogruppo,
    una risorsa, una destinazione o un soggetto. Restituisce il numero di movimenti toccati."""
    col = {"gruppo": "gruppo_id", "risorsa": "risorsa_id", "destinazione": "destinazione_id",
           "soggetto": "soggetto_id"}[field_name]
    where = f"{col} = ? AND giroconto_id IS NULL"
    params: list = [old_id]
    if field_name == "gruppo" and old_sub_id is not None:
        where += " AND sottogruppo_id = ?"
        params.append(old_sub_id)
    with arc.tx():
        if delete_them:
            return arc.conn.execute(f"DELETE FROM movimenti WHERE {where}", params).rowcount
        if new_id is None and field_name in ("gruppo", "risorsa"):
            raise ValidationError("Gruppo e risorsa non possono restare vuoti")
        if field_name == "gruppo":
            g = arc.row("gruppi", new_id)
            if g["tipo"] == "E" and arc.conn.execute(f"SELECT 1 FROM movimenti WHERE {where} AND importo < 0", params).fetchone():
                raise ValidationError(f"Il gruppo «{g['nome']}» è di entrata ma alcuni movimenti sono uscite")
            if g["tipo"] == "U" and arc.conn.execute(f"SELECT 1 FROM movimenti WHERE {where} AND importo > 0", params).fetchone():
                raise ValidationError(f"Il gruppo «{g['nome']}» è di uscita ma alcuni movimenti sono entrate")
            sets, vals = "gruppo_id = ?, sottogruppo_id = ?", [new_id, new_sub_id]
        elif field_name == "risorsa":
            sets, vals = "risorsa_id = ?, modalita_id = NULL", [new_id]
        else:
            sets, vals = f"{col} = ?", [new_id]
        return arc.conn.execute(f"UPDATE movimenti SET {sets} WHERE {where}", vals + params).rowcount
