"""Cifratura degli archivi protetti da codice d'accesso.

Formato del file: MAGIC | sale (16 byte) | nonce (12 byte) | database SQLite cifrato con AES-256-GCM.
La chiave deriva dal codice con scrypt (n=2^15, r=8, p=1); MAGIC e sale sono autenticati insieme ai dati,
quindi un file alterato o un codice sbagliato vengono riconosciuti. Il database in chiaro esiste solo in memoria.
"""
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"RTLCRYPT1"
SALT_LEN = 16
NONCE_LEN = 12


class WrongPassword(Exception):
    """Codice d'accesso errato oppure file danneggiato."""


def is_encrypted(path: Path | str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def new_salt() -> bytes:
    return os.urandom(SALT_LEN)


def derive_key(password: str, salt: bytes) -> bytes:
    if not password:
        raise ValueError("Il codice d'accesso non può essere vuoto")
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(password.encode("utf-8"))


def encrypt(data: bytes, key: bytes, salt: bytes) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    return MAGIC + salt + nonce + AESGCM(key).encrypt(nonce, data, MAGIC + salt)


def read_salt(blob: bytes) -> bytes:
    if not blob.startswith(MAGIC):
        raise WrongPassword("Il file non è un archivio cifrato")
    return blob[len(MAGIC):len(MAGIC) + SALT_LEN]


def decrypt(blob: bytes, key: bytes) -> bytes:
    salt = read_salt(blob)
    start = len(MAGIC) + SALT_LEN
    nonce = blob[start:start + NONCE_LEN]
    try:
        return AESGCM(key).decrypt(nonce, blob[start + NONCE_LEN:], MAGIC + salt)
    except InvalidTag:
        raise WrongPassword("Codice d'accesso errato (o archivio danneggiato)") from None


def atomic_write(path: Path, data: bytes):
    """Scrive su un file temporaneo nella stessa cartella e poi lo sostituisce: mai un archivio a metà."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
