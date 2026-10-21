"""Copie di sicurezza compresse (.rtz = zip con l'archivio) e ripristino.

Un archivio protetto da codice d'accesso viene copiato così com'è, cifrato: il ripristino riporta anche
il codice in uso al momento della copia.
"""
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from . import security
from .db import EXTENSION, Archive, ArchiveError

BACKUP_EXTENSION = ".rtz"


def make_backup(arc: Archive, dest: Path | str) -> Path:
    """Scrive una copia coerente dell'archivio aperto (API di backup di SQLite) compressa in zip."""
    dest = Path(dest)
    stem = arc.path.stem if arc.path else "archivio"
    if dest.is_dir():
        dest = dest / (stem + datetime.now().strftime("_%Y%m%d_%H%M%S") + BACKUP_EXTENSION)
    if arc.encrypted:
        arc.flush()
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as z:   # dati cifrati: comprimere non serve
            z.write(arc.path, stem + EXTENSION)
        return dest
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / (stem + EXTENSION)
        out = sqlite3.connect(str(snap))
        try:
            arc.conn.backup(out)
        finally:
            out.close()
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.write(snap, snap.name)
    return dest


def restore_backup(src: Path | str, dest_dir: Path | str, overwrite: bool = False) -> Path:
    """Estrae l'archivio da una copia .rtz nella cartella indicata e verifica che sia leggibile."""
    src, dest_dir = Path(src), Path(dest_dir)
    with zipfile.ZipFile(src) as z:
        names = [n for n in z.namelist() if n.endswith(EXTENSION) and "/" not in n and "\\" not in n]
        if len(names) != 1:
            raise ArchiveError(f"{src.name} non è una copia di sicurezza valida")
        target = dest_dir / names[0]
        if target.exists() and not overwrite:
            raise ArchiveError(f"Esiste già {target.name} nella cartella di destinazione")
        with z.open(names[0]) as fin, open(target, "wb") as fout:
            fout.write(fin.read())
    if not security.is_encrypted(target):   # una copia cifrata si verifica quando viene aperta col codice
        Archive.open(target).close()
    return target
