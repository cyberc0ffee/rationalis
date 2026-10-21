"""Archivio Rationalis: un file SQLite con tabelle, movimenti, giroconti e scadenze.

Uso:
    arc = Archive.create("casa.rtl")      # nuovo archivio con tabelle iniziali
    arc = Archive.open("casa.rtl")        # archivio esistente
    with arc.tx(): ...                    # operazioni atomiche
"""
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from .money import from_db, to_db

EXTENSION = ".rtl"
SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE valute(
    id INTEGER PRIMARY KEY, sigla TEXT NOT NULL, nome TEXT NOT NULL DEFAULT '',
    cambio TEXT NOT NULL DEFAULT '1', principale INTEGER NOT NULL DEFAULT 0,
    in_uso INTEGER NOT NULL DEFAULT 1);
CREATE TABLE gruppi(
    id INTEGER PRIMARY KEY, nome TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('E','U','M')), in_uso INTEGER NOT NULL DEFAULT 1);
CREATE TABLE sottogruppi(
    id INTEGER PRIMARY KEY, gruppo_id INTEGER NOT NULL REFERENCES gruppi(id),
    nome TEXT NOT NULL, in_uso INTEGER NOT NULL DEFAULT 1);
CREATE TABLE risorse(
    id INTEGER PRIMARY KEY, nome TEXT NOT NULL, tipo TEXT NOT NULL DEFAULT 'altro',
    valuta_id INTEGER NOT NULL REFERENCES valute(id), saldo_iniziale INTEGER NOT NULL DEFAULT 0,
    limite_attivo INTEGER NOT NULL DEFAULT 0, limite_min INTEGER NOT NULL DEFAULT 0,
    limite_max INTEGER NOT NULL DEFAULT 0, banca_id INTEGER REFERENCES risorse(id),
    modalita_predef_id INTEGER, in_uso INTEGER NOT NULL DEFAULT 1);
CREATE TABLE modalita(
    id INTEGER PRIMARY KEY, risorsa_id INTEGER NOT NULL REFERENCES risorse(id),
    nome TEXT NOT NULL, in_uso INTEGER NOT NULL DEFAULT 1);
CREATE TABLE destinazioni(id INTEGER PRIMARY KEY, nome TEXT NOT NULL, in_uso INTEGER NOT NULL DEFAULT 1);
CREATE TABLE soggetti(id INTEGER PRIMARY KEY, nome TEXT NOT NULL, in_uso INTEGER NOT NULL DEFAULT 1);
CREATE TABLE descrizioni(id INTEGER PRIMARY KEY, nome TEXT NOT NULL, in_uso INTEGER NOT NULL DEFAULT 1);
CREATE TABLE raggruppamenti(id INTEGER PRIMARY KEY, nome TEXT NOT NULL, in_uso INTEGER NOT NULL DEFAULT 1);
CREATE TABLE raggruppamenti_voci(
    id INTEGER PRIMARY KEY,
    raggruppamento_id INTEGER NOT NULL REFERENCES raggruppamenti(id) ON DELETE CASCADE,
    gruppo_id INTEGER NOT NULL REFERENCES gruppi(id),
    sottogruppo_id INTEGER REFERENCES sottogruppi(id));
CREATE TABLE scadenze(
    id INTEGER PRIMARY KEY, descrizione TEXT NOT NULL DEFAULT '',
    tipo TEXT NOT NULL DEFAULT 'M' CHECK (tipo IN ('M','G')),
    risorsa_id INTEGER NOT NULL REFERENCES risorse(id),
    gruppo_id INTEGER REFERENCES gruppi(id), sottogruppo_id INTEGER REFERENCES sottogruppi(id),
    importo INTEGER NOT NULL DEFAULT 0, modalita_id INTEGER REFERENCES modalita(id),
    destinazione_id INTEGER REFERENCES destinazioni(id), soggetto_id INTEGER REFERENCES soggetti(id),
    rif TEXT NOT NULL DEFAULT '',
    risorsa_dest_id INTEGER REFERENCES risorse(id), importo_dest INTEGER NOT NULL DEFAULT 0,
    data_inizio TEXT NOT NULL, data_fine TEXT, ripetizioni INTEGER,
    unita TEXT NOT NULL CHECK (unita IN ('G','S','M')), passo INTEGER NOT NULL DEFAULT 1,
    giorno_settimana INTEGER, giorno_mese INTEGER, ordinale INTEGER);
CREATE TABLE giroconti(
    id INTEGER PRIMARY KEY, data TEXT NOT NULL, saldato INTEGER NOT NULL DEFAULT 0,
    descrizione TEXT NOT NULL DEFAULT '',
    scadenza_id INTEGER REFERENCES scadenze(id) ON DELETE SET NULL);
CREATE TABLE movimenti(
    id INTEGER PRIMARY KEY, data TEXT NOT NULL,
    gruppo_id INTEGER REFERENCES gruppi(id), sottogruppo_id INTEGER REFERENCES sottogruppi(id),
    risorsa_id INTEGER NOT NULL REFERENCES risorse(id),
    importo INTEGER NOT NULL DEFAULT 0, saldato INTEGER NOT NULL DEFAULT 0,
    modalita_id INTEGER REFERENCES modalita(id),
    destinazione_id INTEGER REFERENCES destinazioni(id), soggetto_id INTEGER REFERENCES soggetti(id),
    descrizione TEXT NOT NULL DEFAULT '', rif TEXT NOT NULL DEFAULT '', controllo TEXT NOT NULL DEFAULT '',
    giroconto_id INTEGER REFERENCES giroconti(id) ON DELETE CASCADE,
    scadenza_id INTEGER REFERENCES scadenze(id) ON DELETE SET NULL,
    CHECK (gruppo_id IS NOT NULL OR giroconto_id IS NOT NULL));
CREATE INDEX ix_mov_data ON movimenti(data);
CREATE INDEX ix_mov_risorsa ON movimenti(risorsa_id, data);
CREATE INDEX ix_mov_giroconto ON movimenti(giroconto_id);
CREATE INDEX ix_mov_scadenza ON movimenti(scadenza_id);
CREATE TABLE budget(
    gruppo_id INTEGER NOT NULL REFERENCES gruppi(id) ON DELETE CASCADE,
    mese INTEGER NOT NULL CHECK (mese BETWEEN 1 AND 12), importo INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (gruppo_id, mese));
"""

# Aggiornamenti dello schema: versione -> istruzioni per arrivarci dalla precedente.
MIGRATIONS = {
    2: ["CREATE TABLE IF NOT EXISTS ricerche(id INTEGER PRIMARY KEY, nome TEXT NOT NULL, filtro TEXT NOT NULL, "
        "in_uso INTEGER NOT NULL DEFAULT 1)"],
    3: [
        "CREATE TABLE IF NOT EXISTS rubrica(id INTEGER PRIMARY KEY, nome TEXT NOT NULL, indirizzo TEXT NOT NULL DEFAULT '', "
        "cap TEXT NOT NULL DEFAULT '', citta TEXT NOT NULL DEFAULT '', provincia TEXT NOT NULL DEFAULT '', "
        "tel1 TEXT NOT NULL DEFAULT '', desc1 TEXT NOT NULL DEFAULT '', tel2 TEXT NOT NULL DEFAULT '', "
        "desc2 TEXT NOT NULL DEFAULT '', tel3 TEXT NOT NULL DEFAULT '', desc3 TEXT NOT NULL DEFAULT '', "
        "piva TEXT NOT NULL DEFAULT '', riferimento TEXT NOT NULL DEFAULT '', libero TEXT NOT NULL DEFAULT '', "
        "email TEXT NOT NULL DEFAULT '', web TEXT NOT NULL DEFAULT '', "
        "soggetto_id INTEGER REFERENCES soggetti(id), note TEXT NOT NULL DEFAULT '', "
        "in_uso INTEGER NOT NULL DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS agenda(data TEXT PRIMARY KEY, testo TEXT NOT NULL DEFAULT '', "
        "ricorda INTEGER NOT NULL DEFAULT 0)",
        "CREATE TABLE IF NOT EXISTS note_mese(anno INTEGER NOT NULL, mese INTEGER NOT NULL, testo TEXT NOT NULL DEFAULT '', "
        "PRIMARY KEY (anno, mese))",
        "CREATE TABLE IF NOT EXISTS schede(id INTEGER PRIMARY KEY, nome TEXT NOT NULL, data TEXT, "
        "decimali INTEGER NOT NULL DEFAULT 2, usa_moltiplicatore INTEGER NOT NULL DEFAULT 0, "
        "moltiplicatore TEXT NOT NULL DEFAULT '1', in_uso INTEGER NOT NULL DEFAULT 1)",
        "CREATE TABLE IF NOT EXISTS schede_righe(id INTEGER PRIMARY KEY, "
        "scheda_id INTEGER NOT NULL REFERENCES schede(id) ON DELETE CASCADE, pos INTEGER NOT NULL, "
        "data TEXT, descrizione TEXT NOT NULL DEFAULT '', valore INTEGER)",
        "CREATE TABLE IF NOT EXISTS investimenti(id INTEGER PRIMARY KEY, nome TEXT NOT NULL, "
        "capitale_iniziale INTEGER NOT NULL DEFAULT 0, data_inizio TEXT NOT NULL, "
        "capitale_finale INTEGER NOT NULL DEFAULT 0, data_fine TEXT NOT NULL, "
        "rendite INTEGER NOT NULL DEFAULT 0, tasse INTEGER NOT NULL DEFAULT 0, bolli INTEGER NOT NULL DEFAULT 0, "
        "spese INTEGER NOT NULL DEFAULT 0, capitalizzazioni INTEGER NOT NULL DEFAULT 1, "
        "in_uso INTEGER NOT NULL DEFAULT 1)",
    ],
}

TABLES = {
    "valute", "gruppi", "sottogruppi", "risorse", "modalita", "destinazioni",
    "soggetti", "descrizioni", "raggruppamenti", "raggruppamenti_voci", "scadenze",
    "giroconti", "movimenti", "budget", "ricerche", "rubrica", "agenda", "note_mese", "schede",
    "schede_righe", "investimenti",
}

# Riferimenti che impediscono la cancellazione di una voce di tabella.
REFERENCES = {
    "valute": [("risorse", "valuta_id")],
    "gruppi": [("movimenti", "gruppo_id"), ("scadenze", "gruppo_id")],
    "sottogruppi": [("movimenti", "sottogruppo_id"), ("scadenze", "sottogruppo_id")],
    "risorse": [("movimenti", "risorsa_id"), ("scadenze", "risorsa_id"),
                ("scadenze", "risorsa_dest_id"), ("risorse", "banca_id")],
    "modalita": [("movimenti", "modalita_id"), ("scadenze", "modalita_id")],
    "destinazioni": [("movimenti", "destinazione_id"), ("scadenze", "destinazione_id")],
    "soggetti": [("movimenti", "soggetto_id"), ("scadenze", "soggetto_id"), ("rubrica", "soggetto_id")],
}

DEFAULT_SETTINGS = {
    "decimali": "2",
    "salda_subito": "0",
    "mese_apertura": "corrente",
    "copia_alla_chiusura": "0",
}

GRUPPI_INIZIALI = [
    ("Stipendi e compensi", "E", ["Stipendio", "Tredicesima", "Rimborsi"]),
    ("Interessi e rendite", "E", ["Interessi bancari", "Cedole", "Affitti attivi"]),
    ("Altre entrate", "E", []),
    ("Casa", "U", ["Affitto o mutuo", "Condominio", "Manutenzione", "Arredamento"]),
    ("Utenze", "U", ["Luce", "Gas", "Acqua", "Telefono e internet"]),
    ("Alimentari", "U", ["Supermercato", "Macelleria", "Frutta e verdura"]),
    ("Trasporti", "U", ["Carburante", "Autostrada", "Mezzi pubblici", "Manutenzione auto"]),
    ("Salute", "U", ["Farmaci", "Visite mediche"]),
    ("Abbigliamento", "U", []),
    ("Tempo libero", "U", ["Ristoranti", "Viaggi", "Sport", "Cultura"]),
    ("Tasse e imposte", "U", ["Imposte sul reddito", "Bollo auto", "Rifiuti"]),
    ("Assicurazioni", "U", ["Auto", "Casa", "Vita"]),
    ("Spese bancarie", "U", ["Commissioni", "Canone conto"]),
    ("Spese varie", "U", []),
    ("Rettifiche", "M", []),
]

TIPI_RISORSA = {
    "cassa": "Cassa",
    "banca": "Banca c/c",
    "carta": "Carta di credito",
    "posta": "Conto postale",
    "deposito": "Deposito / libretto",
    "altro": "Altro",
}

MODALITA_INIZIALI = {
    "banca": ["Bonifico", "Bancomat", "Assegno", "Addebito diretto (RID/SDD)", "RIBA"],
    "posta": ["Bollettino", "Bonifico", "Postamat"],
    "carta": ["Acquisto in negozio", "Acquisto online"],
}


class ArchiveError(Exception):
    """Errore generico dell'archivio."""


class InUseError(ArchiveError):
    """La voce è usata da altri dati e non può essere cancellata."""


class ValidationError(ArchiveError):
    """Dati non validi."""


class PasswordRequired(ArchiveError):
    """L'archivio è protetto da codice d'accesso."""


class Archive:
    def __init__(self, conn: sqlite3.Connection, path: Path | None, key: bytes | None = None,
                 salt: bytes | None = None):
        self.conn = conn
        self.path = path
        self._key, self._salt = key, salt
        self._dirty = False
        conn.isolation_level = None  # autocommit: le transazioni si aprono solo con tx()
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.set_trace_callback(self._trace)

    # --- cifratura ------------------------------------------------------
    @property
    def encrypted(self) -> bool:
        return self._key is not None

    def _trace(self, sql: str):
        if self._key is not None and sql.lstrip()[:6].upper() in ("INSERT", "UPDATE", "DELETE", "REPLAC",
                                                                  "CREATE", "DROP T", "ALTER "):
            self._dirty = True

    def flush(self):
        """Archivio cifrato: riscrive il file se ci sono modifiche (chiamato a fine transazione, dal timer
        dell'interfaccia e alla chiusura). Per un archivio normale non fa nulla: SQLite scrive da sé."""
        if self._key is None or not self._dirty or self.conn.in_transaction or self.path is None:
            return
        from .security import atomic_write, encrypt
        atomic_write(self.path, encrypt(self.conn.serialize(), self._key, self._salt))
        self._dirty = False

    def set_password(self, password: str):
        """Protegge (o cambia il codice di) un archivio: da questo momento il file su disco è cifrato."""
        from .security import derive_key, new_salt
        if self.path is None:
            raise ArchiveError("Un archivio in memoria non può essere protetto")
        salt = new_salt()
        key = derive_key(password, salt)
        if self._key is None:
            data = self.conn.serialize()
            mem = sqlite3.connect(":memory:")
            mem.deserialize(data)
            self.conn.close()
            self.conn = mem
            self.conn.isolation_level = None
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.set_trace_callback(self._trace)
        self._key, self._salt = key, salt
        self._dirty = True
        self.flush()

    def remove_password(self):
        """Toglie la protezione: il file torna un normale database SQLite."""
        from .security import atomic_write
        if self._key is None:
            return
        data = self.conn.serialize()
        atomic_write(self.path, data)
        self.conn.close()
        self._key = self._salt = None
        self.conn = sqlite3.connect(str(self.path))
        self.conn.isolation_level = None
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.set_trace_callback(self._trace)

    # --- apertura -------------------------------------------------------
    @classmethod
    def create(cls, path: str | Path | None, with_defaults: bool = True) -> "Archive":
        """Crea un archivio nuovo. path=None crea un archivio in memoria (per i test)."""
        if path is not None:
            path = Path(path)
            if path.exists():
                raise ArchiveError(f"Esiste già un file {path}")
        conn = sqlite3.connect(":memory:" if path is None else str(path))
        arc = cls(conn, path)
        with arc.tx():
            for stmt in SCHEMA.split(";"):
                if stmt.strip():
                    conn.execute(stmt)
            for v in sorted(MIGRATIONS):
                for stmt in MIGRATIONS[v]:
                    conn.execute(stmt)
            conn.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            for k, v in DEFAULT_SETTINGS.items():
                conn.execute("INSERT INTO meta VALUES (?, ?)", (k, v))
            if with_defaults:
                arc._seed()
        return arc

    @classmethod
    def open(cls, path: str | Path, password: str | None = None) -> "Archive":
        from . import security
        path = Path(path)
        if not path.exists():
            raise ArchiveError(f"File non trovato: {path}")
        key = salt = None
        if security.is_encrypted(path):
            if not password:
                raise PasswordRequired(f"{path.name} è protetto da codice d'accesso")
            blob = path.read_bytes()
            salt = security.read_salt(blob)
            key = security.derive_key(password, salt)
            try:
                data = security.decrypt(blob, key)
            except security.WrongPassword as e:
                raise ArchiveError(str(e)) from None
            conn = sqlite3.connect(":memory:")
            conn.deserialize(data)
        else:
            conn = sqlite3.connect(str(path))
        try:
            ver = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        except sqlite3.DatabaseError:
            conn.close()
            raise ArchiveError(f"{path.name} non è un archivio Rationalis") from None
        if ver is None or int(ver[0]) > SCHEMA_VERSION:
            conn.close()
            raise ArchiveError(f"{path.name}: versione dell'archivio non supportata")
        arc = cls(conn, path, key, salt)
        arc._migrate(int(ver[0]))
        arc.flush()
        return arc

    def _migrate(self, current: int):
        if current >= SCHEMA_VERSION:
            return
        with self.tx():
            for v in range(current + 1, SCHEMA_VERSION + 1):
                for stmt in MIGRATIONS.get(v, []):
                    self.conn.execute(stmt)
            self.conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))

    def close(self):
        self.flush()
        self.conn.close()

    def _seed(self):
        eur = self.insert("valute", sigla="EUR", nome="Euro", cambio="1", principale=1)
        for nome, tipo, subs in GRUPPI_INIZIALI:
            gid = self.insert("gruppi", nome=nome, tipo=tipo)
            for s in subs:
                self.insert("sottogruppi", gruppo_id=gid, nome=s)
        self.add_risorsa("Cassa", "cassa", eur)
        self.add_risorsa("Banca c/c", "banca", eur)

    # --- transazioni ----------------------------------------------------
    @contextmanager
    def tx(self):
        if self.conn.in_transaction:
            yield
            return
        self.conn.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")
            self.flush()

    # --- accesso generico ----------------------------------------------
    @staticmethod
    def _check_table(table: str):
        if table not in TABLES:
            raise ValueError(f"Tabella sconosciuta: {table}")

    def rows(self, table: str, where: str = "", params=(), order: str = "nome COLLATE NOCASE"):
        self._check_table(table)
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if order:
            sql += f" ORDER BY {order}"
        return self.conn.execute(sql, params).fetchall()

    def row(self, table: str, id_: int | None):
        self._check_table(table)
        if id_ is None:
            return None
        return self.conn.execute(f"SELECT * FROM {table} WHERE id=?", (id_,)).fetchone()

    def insert(self, table: str, **fields) -> int:
        self._check_table(table)
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        cur = self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(fields.values()))
        return cur.lastrowid

    def update(self, table: str, id_: int, **fields):
        self._check_table(table)
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*fields.values(), id_))

    def usage_count(self, table: str, id_: int) -> int:
        n = 0
        for child, col in REFERENCES.get(table, []):
            n += self.conn.execute(f"SELECT COUNT(*) FROM {child} WHERE {col}=?", (id_,)).fetchone()[0]
        if table == "gruppi":
            for child, col in REFERENCES["sottogruppi"]:
                n += self.conn.execute(
                    f"SELECT COUNT(*) FROM {child} WHERE {col} IN (SELECT id FROM sottogruppi WHERE gruppo_id=?)",
                    (id_,)).fetchone()[0]
        return n

    def delete(self, table: str, id_: int):
        """Cancella una voce di tabella; rifiuta se è usata (vedi REFERENCES)."""
        self._check_table(table)
        if self.usage_count(table, id_):
            raise InUseError("La voce è usata da movimenti o scadenze: non può essere cancellata. "
                             "Si può disattivare togliendo «in uso» oppure usare le variazioni automatiche.")
        with self.tx():
            if table == "valute" and self.row("valute", id_)["principale"]:
                raise InUseError("La valuta principale non può essere cancellata")
            if table == "gruppi":
                self.conn.execute("DELETE FROM raggruppamenti_voci WHERE gruppo_id=?", (id_,))
                self.conn.execute("DELETE FROM sottogruppi WHERE gruppo_id=?", (id_,))
            elif table == "sottogruppi":
                self.conn.execute("DELETE FROM raggruppamenti_voci WHERE sottogruppo_id=?", (id_,))
            elif table == "risorse":
                self.conn.execute("DELETE FROM modalita WHERE risorsa_id=?", (id_,))
            elif table == "modalita":
                self.conn.execute("UPDATE risorse SET modalita_predef_id=NULL WHERE modalita_predef_id=?", (id_,))
            self.conn.execute(f"DELETE FROM {table} WHERE id=?", (id_,))

    # --- impostazioni ---------------------------------------------------
    def setting(self, key: str, default: str | None = None) -> str | None:
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else default

    def set_setting(self, key: str, value: str):
        with self.tx():
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    @property
    def decimals(self) -> int:
        return int(self.setting("decimali", "2"))

    # --- valute ---------------------------------------------------------
    def principal(self):
        return self.conn.execute("SELECT * FROM valute WHERE principale=1").fetchone()

    def rate(self, valuta_id: int) -> Decimal:
        return Decimal(self.row("valute", valuta_id)["cambio"])

    def set_principal(self, valuta_id: int):
        """Imposta una nuova valuta principale ricalcolando tutti i cambi e i budget."""
        new_rate = self.rate(valuta_id)
        with self.tx():
            for v in self.rows("valute", order=""):
                self.update("valute", v["id"], cambio=str(Decimal(v["cambio"]) / new_rate),
                            principale=int(v["id"] == valuta_id))
            for b in self.conn.execute("SELECT gruppo_id, mese, importo FROM budget").fetchall():
                self.conn.execute("UPDATE budget SET importo=? WHERE gruppo_id=? AND mese=?",
                                  (to_db(from_db(b["importo"]) * new_rate), b["gruppo_id"], b["mese"]))

    def resource_currency(self, risorsa_id: int):
        return self.conn.execute(
            "SELECT v.* FROM valute v JOIN risorse r ON r.valuta_id=v.id WHERE r.id=?", (risorsa_id,)).fetchone()

    # --- utilità tabelle ------------------------------------------------
    def add_risorsa(self, nome: str, tipo: str, valuta_id: int, saldo_iniziale: Decimal = Decimal(0),
                    banca_id: int | None = None) -> int:
        if tipo == "carta" and banca_id is None:
            banca = self.conn.execute("SELECT id FROM risorse WHERE tipo='banca' ORDER BY id").fetchone()
            if banca is None:
                raise ValidationError("Una carta di credito richiede una risorsa di tipo banca c/c associata")
            banca_id = banca["id"]
        with self.tx():
            rid = self.insert("risorse", nome=nome, tipo=tipo, valuta_id=valuta_id,
                              saldo_iniziale=to_db(saldo_iniziale), banca_id=banca_id)
            for m in MODALITA_INIZIALI.get(tipo, []):
                self.insert("modalita", risorsa_id=rid, nome=m)
        return rid

    def name_of(self, table: str, id_: int | None) -> str:
        r = self.row(table, id_)
        return r["nome"] if r else ""

    def find_by_name(self, table: str, nome: str, **extra):
        where = "nome = ? COLLATE NOCASE"
        params = [nome.strip()]
        for k, v in extra.items():
            where += f" AND {k} = ?"
            params.append(v)
        r = self.rows(table, where, params, order="id")
        return r[0] if r else None
