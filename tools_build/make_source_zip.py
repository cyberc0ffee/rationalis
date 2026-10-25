"""Crea dist/Rationalis-<versione>-sorgente.zip da portare su un Mac (o un altro PC) per avviare o costruire l'app.

Uso (dalla cartella del progetto):  python tools_build/make_source_zip.py
Include codice, test, script di build, workflow e documentazione; esclude dist/, build/, .venv e file compilati.
Gli script .command e .sh vengono marcati come eseguibili (permessi Unix nello zip).
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rationalis import __version__  # noqa: E402

INCLUDE = ["rationalis", "tests", "tools_build", ".github", "avvio.py", "pyproject.toml", "requirements.txt",
           "README.md", "README.it.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "Avvia Rationalis.command",
           "Avvia Rationalis.bat"]
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
EXECUTABLE = (".command", ".sh")


def main():
    out = ROOT / "dist" / f"Rationalis-{__version__}-sorgente.zip"
    out.parent.mkdir(exist_ok=True)
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for item in INCLUDE:
            p = ROOT / item
            files = [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.is_file())
            for f in files:
                rel = f.relative_to(ROOT)
                if SKIP_PARTS & set(rel.parts) or f.suffix == ".pyc":
                    continue
                info = zipfile.ZipInfo(str(Path("Rationalis") / rel).replace("\\", "/"))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3                      # Unix, così i permessi vengono letti
                mode = 0o755 if f.suffix in EXECUTABLE else 0o644
                info.external_attr = (0o100000 | mode) << 16
                z.writestr(info, f.read_bytes())
                n += 1
    print(f"{out}  ({n} file, {out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
