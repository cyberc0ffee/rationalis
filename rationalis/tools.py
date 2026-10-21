"""Strumenti dell'archivio: rubrica, agenda, annotazioni del mese, schede libere, investimenti,
dati della pagina d'avvio."""
import csv
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from . import balances as bal
from . import movements as mv
from .db import Archive, ValidationError
from .finance import Investment
from .money import ZERO, from_db, to_db

MAX_NOTE = 32_000

# --- rubrica ------------------------------------------------------------------------
CONTACT_FIELDS = ["nome", "indirizzo", "cap", "citta", "provincia", "tel1", "desc1", "tel2", "desc2", "tel3", "desc3",
                  "piva", "riferimento", "libero", "email", "web", "soggetto_id", "note"]
CONTACT_LABELS = {"nome": "Denominazione", "indirizzo": "Indirizzo", "cap": "CAP", "citta": "Città",
                  "provincia": "Provincia", "tel1": "Telefono 1", "desc1": "Descr. 1", "tel2": "Telefono 2",
                  "desc2": "Descr. 2", "tel3": "Telefono 3", "desc3": "Descr. 3", "piva": "P.IVA / C.F.",
                  "riferimento": "Riferimento", "libero": "Libero", "email": "E-mail", "web": "Web",
                  "soggetto_id": "Soggetto", "note": "Note"}
SEARCH_FIELDS = ["nome", "indirizzo", "citta", "tel1", "tel2", "tel3", "riferimento", "libero", "email", "note"]


def save_contact(arc: Archive, fields: dict, id_: int | None = None) -> int:
    f = {k: fields.get(k, "" if k != "soggetto_id" else None) for k in CONTACT_FIELDS}
    f["nome"] = (f["nome"] or "").strip()
    if not f["nome"]:
        raise ValidationError("La denominazione è obbligatoria")
    if len(f["note"] or "") > MAX_NOTE:
        raise ValidationError(f"Le note superano {MAX_NOTE} caratteri")
    with arc.tx():
        if id_ is None:
            return arc.insert("rubrica", **f)
        arc.update("rubrica", id_, **f)
        return id_


def contacts(arc: Archive, soggetto_id: int | None = None, letter: str | None = None):
    """Voci della rubrica, eventualmente di un soggetto e con iniziale data ('#' = non lettera)."""
    where, params = [], []
    if soggetto_id is not None:
        where.append("soggetto_id = ?")
        params.append(soggetto_id)
    rows = arc.rows("rubrica", " AND ".join(where), params)
    if letter == "#":
        rows = [r for r in rows if not r["nome"][:1].isalpha()]
    elif letter:
        rows = [r for r in rows if r["nome"][:1].upper() == letter.upper()]
    return rows


def search_contacts(arc: Archive, text: str, fields: list[str] | None = None, match: str = "contiene",
                    soggetto_id: int | None = None, after_id: int | None = None):
    """Prima voce (dopo after_id nell'ordine alfabetico) che corrisponde: match 'inizio', 'contiene', 'uguale'."""
    t = text.strip().lower()
    if not t:
        return None
    fields = fields or SEARCH_FIELDS
    rows = contacts(arc, soggetto_id)
    if after_id is not None:
        ids = [r["id"] for r in rows]
        if after_id in ids:
            rows = rows[ids.index(after_id) + 1:]
    for r in rows:
        for f in fields:
            v = (r[f] or "").lower()
            if (match == "inizio" and v.startswith(t)) or (match == "uguale" and v == t) or \
                    (match == "contiene" and t in v):
                return r
    return None


def export_contacts(arc: Archive, path: Path | str, soggetto_id: int | None = None):
    """Testo delimitato: campi separati da punto e virgola, testi tra doppi apici."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_NONNUMERIC)
        w.writerow([CONTACT_LABELS[k] for k in CONTACT_FIELDS])
        for r in contacts(arc, soggetto_id):
            w.writerow([arc.name_of("soggetti", r["soggetto_id"]) if k == "soggetto_id" else (r[k] or "")
                        for k in CONTACT_FIELDS])


def contacts_for_print(arc: Archive, kind: str = "completa", soggetto_id: int | None = None,
                       from_name: str = "", to_name: str = "") -> tuple[list[str], list[list[str]]]:
    """Righe per la stampa della rubrica: 'completa', 'ridotta' o 'mini' (minirubrica telefonica)."""
    rows = contacts(arc, soggetto_id)
    lo, hi = from_name.strip().lower(), to_name.strip().lower()
    rows = [r for r in rows if (not lo or r["nome"].lower() >= lo) and (not hi or r["nome"].lower() <= hi)]

    def tel(r, i):
        t = r[f"tel{i}"]
        return f"{t} ({r[f'desc{i}']})" if t and r[f"desc{i}"] else t

    def addr(r):
        return ", ".join(x for x in (r["indirizzo"], " ".join(x for x in (r["cap"], r["citta"]) if x),
                                     f"({r['provincia']})" if r["provincia"] else "") if x)

    if kind == "mini":
        return (["Nominativo", "Telefoni"],
                [[r["nome"] + (f" – {r['riferimento']}" if r["riferimento"] else ""),
                  "  ".join(x for x in (tel(r, 1), tel(r, 2), tel(r, 3)) if x)] for r in rows])
    if kind == "ridotta":
        return (["Nominativo", "Indirizzo", "Telefoni", "E-mail"],
                [[r["nome"] + (f"\n{r['riferimento']}" if r["riferimento"] else ""), addr(r),
                  "\n".join(x for x in (tel(r, 1), tel(r, 2)) if x), r["email"]] for r in rows])
    return (["Nominativo", "Indirizzo", "Telefoni", "P.IVA / C.F.", "E-mail / Web", "Soggetto", "Note"],
            [[r["nome"] + (f"\n{r['riferimento']}" if r["riferimento"] else ""), addr(r),
              "\n".join(x for x in (tel(r, 1), tel(r, 2), tel(r, 3)) if x), r["piva"],
              "\n".join(x for x in (r["email"], r["web"]) if x), arc.name_of("soggetti", r["soggetto_id"]),
              "\n".join(x for x in (r["libero"], r["note"]) if x)] for r in rows])


# --- agenda e annotazioni ------------------------------------------------------------
def agenda_get(arc: Archive, d: date) -> tuple[str, bool]:
    r = arc.conn.execute("SELECT testo, ricorda FROM agenda WHERE data = ?", (d.isoformat(),)).fetchone()
    return (r["testo"], bool(r["ricorda"])) if r else ("", False)


def agenda_set(arc: Archive, d: date, text: str, remind: bool = False):
    if len(text) > MAX_NOTE:
        raise ValidationError(f"La nota supera {MAX_NOTE} caratteri")
    with arc.tx():
        if text.strip():
            arc.conn.execute("INSERT OR REPLACE INTO agenda VALUES (?, ?, ?)", (d.isoformat(), text, int(remind)))
        else:
            arc.conn.execute("DELETE FROM agenda WHERE data = ?", (d.isoformat(),))


def agenda_days(arc: Archive, year: int, month: int) -> set[int]:
    first, last = mv.month_bounds(year, month)
    return {date.fromisoformat(r[0]).day for r in arc.conn.execute(
        "SELECT data FROM agenda WHERE data BETWEEN ? AND ?", (first.isoformat(), last.isoformat())).fetchall()}


def agenda_neighbour(arc: Archive, d: date, backwards: bool = False, text: str = "") -> date | None:
    """Giorno con nota precedente o successivo a d; con text, il primo che contiene il testo."""
    op, order = ("<", "DESC") if backwards else (">", "ASC")
    sql = f"SELECT data FROM agenda WHERE data {op} ?"
    params: list = [d.isoformat()]
    if text:
        sql += " AND testo LIKE ?"
        params.append(f"%{text}%")
    r = arc.conn.execute(sql + f" ORDER BY data {order} LIMIT 1", params).fetchone()
    return date.fromisoformat(r[0]) if r else None


def reminders(arc: Archive, d: date) -> list[tuple[date, str]]:
    """Note dell'agenda segnate «ricorda» per il giorno d."""
    return [(date.fromisoformat(r["data"]), r["testo"]) for r in arc.conn.execute(
        "SELECT data, testo FROM agenda WHERE ricorda = 1 AND data = ?", (d.isoformat(),)).fetchall()]


def month_note_get(arc: Archive, year: int, month: int) -> str:
    r = arc.conn.execute("SELECT testo FROM note_mese WHERE anno = ? AND mese = ?", (year, month)).fetchone()
    return r[0] if r else ""


def month_note_set(arc: Archive, year: int, month: int, text: str):
    if len(text) > MAX_NOTE:
        raise ValidationError(f"L'annotazione supera {MAX_NOTE} caratteri")
    with arc.tx():
        if text.strip():
            arc.conn.execute("INSERT OR REPLACE INTO note_mese VALUES (?, ?, ?)", (year, month, text))
        else:
            arc.conn.execute("DELETE FROM note_mese WHERE anno = ? AND mese = ?", (year, month))


# --- schede libere -----------------------------------------------------------------------
MAX_CARD_ROWS = 1000
MAX_CARD_TEXT = 100


@dataclass
class CardRow:
    data: date | None = None
    descrizione: str = ""
    valore: Decimal | None = None

    def is_empty(self) -> bool:
        return self.data is None and not self.descrizione.strip() and self.valore is None


def card_rows(arc: Archive, scheda_id: int) -> list[CardRow]:
    return [CardRow(date.fromisoformat(r["data"]) if r["data"] else None, r["descrizione"],
                    from_db(r["valore"]) if r["valore"] is not None else None)
            for r in arc.rows("schede_righe", "scheda_id = ?", (scheda_id,), order="pos")]


def save_card(arc: Archive, nome: str, rows: list[CardRow], data: date | None = None, decimali: int = 2,
              moltiplicatore: Decimal | None = None, id_: int | None = None) -> int:
    nome = nome.strip()
    if not nome:
        raise ValidationError("Il nome della scheda è obbligatorio")
    if len(nome) > MAX_CARD_TEXT:
        raise ValidationError(f"Il nome supera {MAX_CARD_TEXT} caratteri")
    rows = [r for r in rows if not r.is_empty()]
    if len(rows) > MAX_CARD_ROWS:
        raise ValidationError(f"Una scheda può contenere al massimo {MAX_CARD_ROWS} registrazioni")
    if any(len(r.descrizione) > MAX_CARD_TEXT for r in rows):
        raise ValidationError(f"Una descrizione supera {MAX_CARD_TEXT} caratteri")
    if not 0 <= decimali <= 4:
        raise ValidationError("I decimali vanno da 0 a 4")
    fields = dict(nome=nome, data=data.isoformat() if data else None, decimali=decimali,
                  usa_moltiplicatore=int(moltiplicatore is not None),
                  moltiplicatore=str(moltiplicatore if moltiplicatore is not None else 1))
    with arc.tx():
        if id_ is None:
            id_ = arc.insert("schede", **fields)
        else:
            arc.update("schede", id_, **fields)
            arc.conn.execute("DELETE FROM schede_righe WHERE scheda_id = ?", (id_,))
        for i, r in enumerate(rows):
            arc.insert("schede_righe", scheda_id=id_, pos=i, data=r.data.isoformat() if r.data else None,
                       descrizione=r.descrizione, valore=to_db(r.valore) if r.valore is not None else None)
    return id_


def card_totals(rows: list[CardRow], moltiplicatore: Decimal | None) -> tuple[Decimal, Decimal | None]:
    """(TOTALE dei valori, Importo = totale × moltiplicatore se usato)."""
    tot = sum((r.valore for r in rows if r.valore is not None), ZERO)
    return tot, (tot * moltiplicatore if moltiplicatore is not None else None)


def sort_card_by_date(rows: list[CardRow]) -> list[CardRow]:
    """Ordina per data; le registrazioni senza data restano in fondo nell'ordine originale."""
    dated = sorted((r for r in rows if r.data), key=lambda r: r.data)
    return dated + [r for r in rows if not r.data]


# --- investimenti (rendimenti) -------------------------------------------------------------
def save_investment(arc: Archive, nome: str, inv: Investment, capitalizzazioni: int = 1,
                    id_: int | None = None) -> int:
    if not nome.strip():
        raise ValidationError("Dare un nome all'investimento")
    if inv.data_fine <= inv.data_inizio:
        raise ValidationError("La data di fine deve seguire la data di inizio")
    fields = dict(nome=nome.strip(), capitale_iniziale=to_db(inv.capitale_iniziale),
                  data_inizio=inv.data_inizio.isoformat(), capitale_finale=to_db(inv.capitale_finale),
                  data_fine=inv.data_fine.isoformat(), rendite=to_db(inv.rendite), tasse=to_db(inv.tasse),
                  bolli=to_db(inv.bolli), spese=to_db(inv.spese), capitalizzazioni=capitalizzazioni)
    with arc.tx():
        if id_ is None:
            return arc.insert("investimenti", **fields)
        arc.update("investimenti", id_, **fields)
        return id_


def load_investment(arc: Archive, id_: int) -> tuple[str, Investment, int]:
    r = arc.row("investimenti", id_)
    inv = Investment(from_db(r["capitale_iniziale"]), date.fromisoformat(r["data_inizio"]),
                     from_db(r["capitale_finale"]), date.fromisoformat(r["data_fine"]), from_db(r["rendite"]),
                     from_db(r["tasse"]), from_db(r["bolli"]), from_db(r["spese"]))
    return r["nome"], inv, r["capitalizzazioni"]


# --- pagina d'avvio ---------------------------------------------------------------------------
START_SECTIONS = {"situazione": "Situazione delle risorse", "avvisi": "Avvisi del giorno",
                  "scadenze": "Prossime scadenze", "iniziare": "Per iniziare"}


def start_page_data(arc: Archive, today: date | None = None, days_ahead: int = 7) -> dict:
    today = today or date.today()
    soon = today + timedelta(days=days_ahead)
    overdue = [mv.Movement.from_row(r) for r in arc.rows(
        "movimenti", "saldato = 0 AND data < ?", (today.isoformat(),), order="data, id")]
    due = [mv.Movement.from_row(r) for r in arc.rows(
        "movimenti", "saldato = 0 AND data BETWEEN ? AND ?", (today.isoformat(), soon.isoformat()), order="data, id")]
    n_mov = arc.conn.execute("SELECT COUNT(*) FROM movimenti WHERE giroconto_id IS NULL").fetchone()[0]
    return {
        "oggi": today,
        "risorse": bal.current_balances(arc, today),
        "totale": bal.balance_all(arc, today),
        "promemoria": reminders(arc, today),
        "scadute": overdue,
        "in_scadenza": due,
        "statistiche": {"movimenti": n_mov,
                        "giroconti": arc.conn.execute("SELECT COUNT(*) FROM giroconti").fetchone()[0],
                        "scadenze": arc.conn.execute("SELECT COUNT(*) FROM scadenze").fetchone()[0],
                        "risorse": arc.conn.execute("SELECT COUNT(*) FROM risorse").fetchone()[0],
                        "gruppi": arc.conn.execute("SELECT COUNT(*) FROM gruppi").fetchone()[0]},
    }
