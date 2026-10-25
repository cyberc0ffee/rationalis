"""Importazione di archivi Danea Professional Manager 5 (.dpm) e delle loro copie (.dpz).

Il .dpm è (probabilmente) un database Microsoft Access 97 / Jet 3.5. Struttura dedotta dai soli nomi
di tabelle e campi, ai soli fini di interoperabilità: NON ancora verificata su un archivio
reale. Per questo la lettura è tollerante:
- i nomi di colonna sono cercati senza distinguere maiuscole e con più candidati per campo;
- i tipi dei gruppi e delle risorse, se non decifrabili, sono dedotti dai movimenti e dai nomi;
- ciò che non è riconosciuto finisce negli avvisi del rapporto invece di bloccare l'importazione.

Uso:
    report = import_dpm("vecchio.dpm", "nuovo.rtl")
    print(report.summary())
"""
import tempfile
import zipfile
import zlib
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .. import movements as mv
from .. import transfers as tr
from ..db import Archive, ArchiveError, ValidationError
from ..money import ZERO, to_db
from . import ImportReport
from .resolver import guess_resource_type

JET_SIGNATURE = b"Standard Jet DB"

# Tipi di colonna Jet (access_parser.utils)
T_BOOL, T_MONEY, T_FLOAT32, T_FLOAT64, T_DATETIME, T_TEXT, T_MEMO = 1, 5, 6, 7, 8, 10, 12

FALLBACK_GROUP = "Non classificato (importazione)"


class DpmFormatError(ArchiveError):
    """Il file non è un archivio DPM leggibile."""


# --- lettura del contenitore --------------------------------------------------
def _extract_dpz(src: Path, tmpdir: Path) -> Path:
    """Estrae il .dpm da una copia di sicurezza .dpz (zip o zlib; altri formati non supportati)."""
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".dpm")] or z.namelist()
            if not names:
                raise DpmFormatError("La copia .dpz è vuota")
            out = tmpdir / "archivio.dpm"
            out.write_bytes(z.read(names[0]))
            return out
    data = src.read_bytes()
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS, zlib.MAX_WBITS | 16):
        try:
            raw = zlib.decompress(data, wbits)
        except zlib.error:
            continue
        if JET_SIGNATURE in raw[:64]:
            out = tmpdir / "archivio.dpm"
            out.write_bytes(raw)
            return out
    raise DpmFormatError("Formato della copia .dpz non riconosciuto: ripristinarla prima con il programma "
                         "originale e importare il file .dpm")


def _check_signature(path: Path):
    head = path.read_bytes()[:32]
    if JET_SIGNATURE not in head:
        raise DpmFormatError(f"{path.name} non è un database Access/Jet (firma non trovata)")


# --- normalizzazione dei valori -------------------------------------------------
def _fix_text(s: str) -> str:
    try:
        return s.encode("latin1").decode("cp1252")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _norm(value, col_type: int | None):
    if value is None or value == "":
        return None
    if col_type == T_MONEY:
        if isinstance(value, int):
            return Decimal(value) / 10_000
        s = "".join(ch for ch in str(value) if ch.isdigit() or ch in ".-")
        try:
            return Decimal(s) if s else None
        except InvalidOperation:
            return None
    if col_type in (T_FLOAT32, T_FLOAT64):
        return Decimal(str(round(value, 6)))
    if col_type == T_DATETIME:
        if isinstance(value, datetime):
            return value.date()
        s = str(value)
        if s.startswith("("):
            return None
        try:
            return datetime.fromisoformat(s[:19]).date()
        except ValueError:
            return None
    if col_type in (T_TEXT, T_MEMO) and isinstance(value, str):
        return _fix_text(value).strip()
    return value


class Table:
    """Una tabella letta dal MDB come lista di righe {nome_colonna_minuscolo: valore normalizzato}."""

    def __init__(self, name: str, rows: list[dict], columns: list[str]):
        self.name = name
        self.rows = rows
        self.columns = columns
        self.used: set[str] = set()

    def __len__(self):
        return len(self.rows)

    def col(self, *candidates: str) -> str | None:
        for c in candidates:
            if c.lower() in self.columns:
                self.used.add(c.lower())
                return c.lower()
        return None

    def unused(self) -> list[str]:
        return [c for c in self.columns if c not in self.used]


class MdbReader:
    def __init__(self, path: Path):
        try:
            from access_parser import AccessParser
        except ImportError:  # pragma: no cover
            raise DpmFormatError("Manca la libreria access-parser (pip install access-parser)") from None
        try:
            self.db = AccessParser(str(path))
        except Exception as e:  # la libreria solleva eccezioni generiche su file non validi
            raise DpmFormatError(f"Impossibile leggere il database: {e}. Se l'archivio è cifrato, "
                                 "decifrarlo prima con il programma originale.") from e
        self.catalog = {n.lower(): n for n in self.db.catalog if not n.startswith("MSys")}

    def table(self, *names: str) -> Table | None:
        for n in names:
            real = self.catalog.get(n.lower())
            if real is None:
                continue
            t = self.db.get_table(real)
            types = {c.col_name_str.lower(): c.type for c in t.columns.values()}
            data = t.parse()
            cols = list(types)
            n_rows = max((len(v) for v in data.values()), default=0)
            rows = []
            for i in range(n_rows):
                rows.append({c.lower(): _norm(v[i] if i < len(v) else None, types.get(c.lower()))
                             for c, v in data.items()})
            return Table(real, rows, cols)
        return None


# --- importazione -----------------------------------------------------------
def _get(row: dict, col: str | None, default=None):
    if col is None:
        return default
    v = row.get(col)
    return default if v is None else v


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip() in ("*", "-1", "1", "S", "s", "True", "true", "Vero", "vero")
    return bool(v) and v != 0


def _as_int(v) -> int | None:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def _group_type(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if s in ("E", "+", "ENTRATA", "ENTRATE"):
        return "E"
    if s in ("U", "-", "USCITA", "USCITE"):
        return "U"
    if s in ("M", "+/-", "-/+", "MISTO", "ENTRAMBI"):
        return "M"
    return None  # codici numerici: significato non noto, si deduce dai movimenti


class DpmImporter:
    def __init__(self, reader: MdbReader, arc: Archive):
        self.r = reader
        self.arc = arc
        self.report = ImportReport()
        self.maps: dict[str, dict] = defaultdict(dict)
        self._fallback_group: int | None = None

    def run(self) -> ImportReport:
        with self.arc.tx():
            self._valute()
            mov = self.r.table("T_Mov")
            signs = self._group_signs(mov)
            self._gruppi(signs)
            self._sottogruppi()
            self._risorse()
            self._simple("destinazioni", ("T_Destinazioni",), "DestinazioneID", "Destinazioni")
            self._simple("soggetti", ("T_Soggetti",), "SoggettoID", "Soggetti")
            self._simple("descrizioni", ("T_Descrizioni",), "DescrizioneID", "Descrizioni")
            self._modalita_table = self.r.table("T_Modalita")
            self._modalita_names = self._load_modalita_names()
            self._raggruppamenti()
            if mov is None:
                self.report.warn("Tabella dei movimenti (T_Mov) non trovata")
            else:
                self._movimenti(mov)
                if mov.unused():
                    self.report.warn("Colonne dei movimenti non riconosciute: " + ", ".join(mov.unused()))
            self._not_imported()
        return self.report

    # tabelle anagrafiche
    def _valute(self):
        t = self.r.table("T_Valute")
        if not t:
            eur = self.arc.insert("valute", sigla="EUR", nome="Euro", cambio="1", principale=1)
            self.maps["valute"][None] = eur
            self.report.warn("Tabella valute non trovata: creata Euro come valuta principale")
            return
        c_id, c_sigla = t.col("ValutaID", "ID"), t.col("Valuta", "Sigla")
        c_nome, c_cambio, c_princ = t.col("Desc", "Descrizione", "Nome"), t.col("Cambio"), t.col("Principale")
        principal_set = False
        for row in t.rows:
            sigla = str(_get(row, c_sigla, "") or _get(row, c_nome, "?"))[:4]
            cambio = _get(row, c_cambio, Decimal(1))
            try:
                cambio = Decimal(str(cambio)) if Decimal(str(cambio)) > 0 else Decimal(1)
            except InvalidOperation:
                cambio = Decimal(1)
            princ = _truthy(_get(row, c_princ, False)) and not principal_set
            principal_set |= princ
            vid = self.arc.insert("valute", sigla=sigla, nome=str(_get(row, c_nome, "")), cambio=str(cambio),
                                  principale=int(princ))
            self.maps["valute"][_as_int(_get(row, c_id))] = vid
        if not principal_set:
            first = next(iter(self.maps["valute"].values()))
            self.arc.update("valute", first, principale=1)
            self.report.warn("Nessuna valuta principale indicata: impostata la prima valuta")
        p = self.arc.principal()
        if Decimal(p["cambio"]) != 1:
            self.arc.set_principal(p["id"])
        self.report.add("Valute", len(t))

    def _group_signs(self, mov: Table | None) -> dict[int, set[int]]:
        signs: dict[int, set[int]] = defaultdict(set)
        if mov is None:
            return signs
        c_g = mov.col("GruppoID")
        for row in mov.rows:
            imp = self._amount(mov, row)
            if imp:
                signs[_as_int(_get(row, c_g))].add(1 if imp > 0 else -1)
        return signs

    def _gruppi(self, signs):
        t = self.r.table("T_Gruppi")
        if not t:
            self.report.warn("Tabella gruppi non trovata")
            return
        c_id, c_nome = t.col("GruppoID", "ID"), t.col("Desc", "Gruppo", "Nome", "Descrizione")
        c_tipo, c_uso = t.col("tpo", "Tipo"), t.col("InUso")
        undecoded = False
        for row in t.rows:
            old = _as_int(_get(row, c_id))
            tipo = _group_type(_get(row, c_tipo))
            seen = signs.get(old, set())
            if tipo is None:
                undecoded = True
                tipo = "E" if seen == {1} else "U" if seen == {-1} else "M"
            elif (tipo == "E" and -1 in seen) or (tipo == "U" and 1 in seen):
                tipo = "M"
            gid = self.arc.insert("gruppi", nome=str(_get(row, c_nome, f"Gruppo {old}")), tipo=tipo,
                                  in_uso=int(_truthy(_get(row, c_uso, True))))
            self.maps["gruppi"][old] = gid
        if undecoded:
            self.report.warn("Tipo dei gruppi (entrata/uscita/misto) dedotto dai movimenti: controllare la tabella "
                             "gruppi, soprattutto quelli ancora senza movimenti (impostati come misti)")
        self.report.add("Gruppi", len(t))

    def _sottogruppi(self):
        t = self.r.table("T_SottoGruppi", "T_Sottogruppi")
        if not t:
            return
        c_id, c_g = t.col("SottogruppoID", "ID"), t.col("GruppoID")
        c_nome, c_uso = t.col("Desc", "Sottogruppo", "Nome", "Descrizione"), t.col("InUso")
        n = 0
        for row in t.rows:
            gid = self.maps["gruppi"].get(_as_int(_get(row, c_g)))
            if gid is None:
                continue
            sid = self.arc.insert("sottogruppi", gruppo_id=gid, nome=str(_get(row, c_nome, "")),
                                  in_uso=int(_truthy(_get(row, c_uso, True))))
            self.maps["sottogruppi"][_as_int(_get(row, c_id))] = sid
            n += 1
        self.report.add("Sottogruppi", n)

    def _risorse(self):
        t = self.r.table("T_Risorse")
        if not t:
            self.report.warn("Tabella risorse non trovata")
            return
        c_id, c_nome = t.col("RisorsaID", "ID"), t.col("Desc", "Risorsa", "Nome", "Descrizione")
        c_val, c_saldo = t.col("ValutaID"), t.col("SaldoIni", "SaldoIniziale", "Saldo")
        c_lim, c_inf, c_sup = t.col("LimiteAttivo"), t.col("LimiteInf"), t.col("LimiteSup")
        c_link, c_uso = t.col("RisorsaLinkID", "LinkID"), t.col("InUso")
        t.col("ModalitaPredefID", "TipoRisorsa", "Tipo")  # letti più avanti o non necessari
        links = {}
        principal = self.arc.principal()["id"]
        for row in t.rows:
            old = _as_int(_get(row, c_id))
            nome = str(_get(row, c_nome, f"Risorsa {old}"))
            link = _as_int(_get(row, c_link))
            tipo = "carta" if link else guess_resource_type(nome)
            if tipo == "carta" and not link:
                tipo = "altro"
            rid = self.arc.insert(
                "risorse", nome=nome, tipo=tipo,
                valuta_id=self.maps["valute"].get(_as_int(_get(row, c_val)), principal),
                saldo_iniziale=to_db(_get(row, c_saldo, ZERO)),
                limite_attivo=int(_truthy(_get(row, c_lim, False))),
                limite_min=to_db(_get(row, c_inf, ZERO)), limite_max=to_db(_get(row, c_sup, ZERO)),
                in_uso=int(_truthy(_get(row, c_uso, True))))
            self.maps["risorse"][old] = rid
            if link:
                links[rid] = link
        for rid, old_bank in links.items():
            bank = self.maps["risorse"].get(old_bank)
            if bank is not None and bank != rid:
                self.arc.update("risorse", rid, banca_id=bank)
                self.arc.update("risorse", bank, tipo="banca")
            else:
                self.arc.update("risorse", rid, tipo="altro")
        self.report.add("Risorse", len(t))
        self.report.warn("Tipo delle risorse dedotto dal nome e dai collegamenti carta→banca: controllarlo")

    def _simple(self, table: str, names: tuple, id_col: str, label: str):
        t = self.r.table(*names)
        if not t:
            return
        c_id, c_nome = t.col(id_col, "ID"), t.col("Desc", "Descrizione", "Nome", label[:-1])
        c_uso = t.col("InUso")
        for row in t.rows:
            nome = str(_get(row, c_nome, "")).strip()
            if not nome:
                continue
            new = self.arc.insert(table, nome=nome, in_uso=int(_truthy(_get(row, c_uso, True))))
            self.maps[table][_as_int(_get(row, c_id))] = new
        self.report.add(label, len(t))

    def _load_modalita_names(self) -> dict[int, str]:
        t = self._modalita_table
        if not t:
            return {}
        c_id, c_nome = t.col("ModalitaID", "ID"), t.col("Desc", "Modalita", "Modalità", "Nome", "Descrizione")
        return {_as_int(_get(r, c_id)): str(_get(r, c_nome, "")) for r in t.rows}

    def _modalita(self, old_id: int | None, risorsa_id: int) -> int | None:
        if old_id is None or old_id not in self._modalita_names:
            return None
        key = (old_id, risorsa_id)
        if key not in self.maps["modalita"]:
            self.maps["modalita"][key] = self.arc.insert("modalita", risorsa_id=risorsa_id,
                                                          nome=self._modalita_names[old_id] or f"Modalità {old_id}")
            self.report.add("Modalità di pagamento")
        return self.maps["modalita"][key]

    def _raggruppamenti(self):
        t = self.r.table("T_Raggruppamenti")
        rr = self.r.table("T_RaggruppamentiRighe")
        if not t:
            return
        c_id, c_nome = t.col("RaggruppamentoID", "ID"), t.col("Desc", "Descrizione", "Nome")
        for row in t.rows:
            self.maps["raggruppamenti"][_as_int(_get(row, c_id))] = self.arc.insert(
                "raggruppamenti", nome=str(_get(row, c_nome, "")))
        self.report.add("Raggruppamenti", len(t))
        if not rr:
            return
        c_r, c_g, c_s = rr.col("RaggruppamentoID"), rr.col("GruppoID"), rr.col("SottogruppoID")
        rr.col("RaggruppamentoRigaID", "GruppoIntero")
        for row in rr.rows:
            rid = self.maps["raggruppamenti"].get(_as_int(_get(row, c_r)))
            sid = self.maps["sottogruppi"].get(_as_int(_get(row, c_s)))
            gid = self.maps["gruppi"].get(_as_int(_get(row, c_g)))
            if gid is None and sid is not None:
                gid = self.arc.row("sottogruppi", sid)["gruppo_id"]
            if rid and gid:
                self.arc.insert("raggruppamenti_voci", raggruppamento_id=rid, gruppo_id=gid, sottogruppo_id=sid)

    # movimenti
    def _amount(self, t: Table, row: dict) -> Decimal:
        c_e, c_u = t.col("Entrata", "Entrate", "Ent", "Entr"), t.col("Usc", "Uscita", "Uscite")
        if c_e or c_u:
            e = _get(row, c_e, ZERO) or ZERO
            u = _get(row, c_u, ZERO) or ZERO
            return Decimal(str(e)) - Decimal(str(u))
        c_i = t.col("Importo", "Imp")
        return Decimal(str(_get(row, c_i, ZERO) or ZERO))

    def _fallback(self) -> int:
        if self._fallback_group is None:
            self._fallback_group = self.arc.insert("gruppi", nome=FALLBACK_GROUP, tipo="M")
        return self._fallback_group

    def _movimenti(self, t: Table):
        c = {
            "id": t.col("MovID", "ID"), "data": t.col("dta", "Data"), "g": t.col("GruppoID"),
            "s": t.col("SottogruppoID"), "r": t.col("RisorsaID"), "mod": t.col("ModalitaID"),
            "dest": t.col("DestinazioneID"), "sogg": t.col("SoggettoID"),
            "desc": t.col("Desc", "Descrizione"), "rif": t.col("Rif", "Riferimento"),
            "ctrl": t.col("C", "Ctrl", "Controllo"), "sal": t.col("Sal", "Saldato", "Saldata", "S"),
            "giro": t.col("Giroconto", "IDGiroconto"),
        }
        t.col("ScadenzaID")
        transfers: dict[int, list[dict]] = defaultdict(list)
        n_mov = n_bad = 0
        for row in t.rows:
            d = _get(row, c["data"])
            rid = self.maps["risorse"].get(_as_int(_get(row, c["r"])))
            if not isinstance(d, date) or rid is None:
                n_bad += 1
                continue
            rec = {"data": d, "risorsa_id": rid, "importo": self._amount(t, row),
                   "saldato": _truthy(_get(row, c["sal"], False)),
                   "descrizione": str(_get(row, c["desc"], ""))[:mv.MAX_DESCRIZIONE],
                   "rif": str(_get(row, c["rif"], ""))[:mv.MAX_RIF],
                   "controllo": str(_get(row, c["ctrl"], ""))[:1]}
            giro = _as_int(_get(row, c["giro"])) or 0
            if giro:
                transfers[giro].append(rec)
                continue
            gid = self.maps["gruppi"].get(_as_int(_get(row, c["g"])))
            if gid is None:
                gid = self._fallback()
                self.report.warn(f"Movimenti senza gruppo riconosciuto assegnati a «{FALLBACK_GROUP}»")
            sid = self.maps["sottogruppi"].get(_as_int(_get(row, c["s"])))
            if sid is not None and self.arc.row("sottogruppi", sid)["gruppo_id"] != gid:
                sid = None
            m = mv.Movement(
                gruppo_id=gid, sottogruppo_id=sid,
                modalita_id=self._modalita(_as_int(_get(row, c["mod"])), rid),
                destinazione_id=self.maps["destinazioni"].get(_as_int(_get(row, c["dest"]))),
                soggetto_id=self.maps["soggetti"].get(_as_int(_get(row, c["sogg"]))), **rec)
            try:
                mv.validate(self.arc, m)
            except ValidationError as e:
                self.report.warn(f"Movimento del {m.data:%d/%m/%Y} non importato: {e}")
                continue
            self.arc.insert("movimenti", **m.to_fields())
            n_mov += 1
        self.report.add("Movimenti", n_mov)
        if n_bad:
            self.report.warn(f"{n_bad} movimenti senza data o risorsa valida non importati")
        self._transfers(transfers)

    def _transfers(self, transfers: dict[int, list[dict]]):
        n = 0
        for giro_id, legs in transfers.items():
            outs = [lg for lg in legs if lg["importo"] < 0]
            ins = [lg for lg in legs if lg["importo"] > 0]
            if len(outs) == 1 and 1 <= len(ins) <= tr.MAX_VERSAMENTI and \
                    len({lg["risorsa_id"] for lg in outs + ins}) == len(outs) + len(ins):
                o = outs[0]
                tr.save(self.arc, tr.Transfer(o["data"], tr.Leg(o["risorsa_id"], -o["importo"]),
                                              [tr.Leg(lg["risorsa_id"], lg["importo"]) for lg in ins],
                                              saldato=o["saldato"], descrizione=o["descrizione"]),
                        check_balance=False)
                n += 1
            else:
                gid = self._fallback()
                for lg in legs:
                    self.arc.insert("movimenti", **mv.Movement(gruppo_id=gid, **lg).to_fields())
                self.report.warn(f"Giroconto {giro_id} con struttura inattesa: importato come movimenti "
                                 f"nel gruppo «{FALLBACK_GROUP}»")
        self.report.add("Giroconti", n)

    def _not_imported(self):
        for names, label in ((("T_Scadenze",), "scadenze (i movimenti già generati sono stati importati, "
                                               "le scadenze vanno ricreate)"),
                             (("T_Rubrica",), "voci di rubrica"), (("T_Agenda",), "note di agenda"),
                             (("T_Note",), "annotazioni del mese"), (("T_SchedeLibere",), "schede libere"),
                             (("T_Investimenti",), "calcoli di rendimento"), (("T_Ricerche",), "ricerche salvate")):
            if names[0].lower() in self.r.catalog:
                t = self.r.table(*names)
                if t and len(t):
                    self.report.warn(f"Non ancora importate: {len(t)} {label}")


def import_dpm(src: Path | str, dest: Path | str | None) -> tuple[Archive, ImportReport]:
    """Crea un nuovo archivio Rationalis `dest` (None = in memoria) con i dati del .dpm/.dpz `src`."""
    src = Path(src)
    with tempfile.TemporaryDirectory() as tmp:
        path = _extract_dpz(src, Path(tmp)) if src.suffix.lower() == ".dpz" else src
        _check_signature(path)
        reader = MdbReader(path)
        arc = Archive.create(dest, with_defaults=False)
        try:
            report = DpmImporter(reader, arc).run()
        except Exception:
            arc.close()
            if dest is not None:
                Path(dest).unlink(missing_ok=True)
            raise
    return arc, report
