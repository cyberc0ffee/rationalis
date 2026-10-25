"""Crea la versione portabile di Rationalis per il sistema su cui viene eseguito, e la verifica.

Uso (dalla cartella del progetto):  python tools_build/build_portable.py
Requisiti: le dipendenze di requirements.txt più pyinstaller (e pillow su macOS, per l'icona .icns).

Windows: dist/Rationalis/ (Rationalis.exe + _internal) e dist/Rationalis-<ver>-portabile-win64.zip
macOS:   dist/Rationalis.app, dist/Rationalis-<ver>-macos-<arch>.dmg e .zip
Passi: PyInstaller (finestra senza console) -> LEGGIMI -> prova `--prova-avvio` dell'eseguibile -> pacchetti.
Si ferma con errore se la prova non riesce. PyInstaller non fa compilazione incrociata: la versione per
macOS si costruisce su un Mac (o sul server macOS di GitHub Actions, vedi .github/workflows/build.yml).
"""
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rationalis import __version__  # noqa: E402

MAC = sys.platform == "darwin"
WIN = sys.platform == "win32"


def pyinstaller():
    res = ROOT / "rationalis" / "resources"
    # su macOS PyInstaller converte il PNG in .icns (con pillow); su Windows usa l'.ico
    icon = res / ("rationalis.png" if MAC else "rationalis.ico")
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "Rationalis",
            "--icon", str(icon), "--add-data", f"{res}{os.pathsep}rationalis/resources",
            "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
            "--exclude-module", "tkinter", "--exclude-module", "pytest"]
    if MAC:
        args += ["--osx-bundle-identifier", "it.rationalis.app"]
    subprocess.run(args + [str(ROOT / "avvio.py")], check=True)


def executable() -> Path:
    if MAC:
        return ROOT / "dist" / "Rationalis.app" / "Contents" / "MacOS" / "Rationalis"
    return ROOT / "dist" / "Rationalis" / ("Rationalis.exe" if WIN else "Rationalis")


def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ)
        bundle = executable().parent.parent if MAC else executable().parent
        if not WIN and any(bundle.rglob("libqoffscreen*")):
            env.setdefault("QT_QPA_PLATFORM", "offscreen")   # prova anche su server senza schermo
        else:
            env.pop("QT_QPA_PLATFORM", None)                  # plugin non incluso: grafica normale
        subprocess.run([str(executable()), "--prova-avvio", tmp], check=True, timeout=300, env=env)
        result = (Path(tmp) / "esito.txt").read_text(encoding="utf-8")
    print("prova:", result)
    if not result.startswith("ok"):
        raise SystemExit("La prova dell'eseguibile non è riuscita")


def package_windows():
    app_dir = ROOT / "dist" / "Rationalis"
    shutil.copy(ROOT / "tools_build" / "LEGGIMI.txt", app_dir / "LEGGIMI.txt")
    for f in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy(ROOT / f, app_dir / f)
    out = ROOT / "dist" / f"Rationalis-{__version__}-portabile-win64.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in app_dir.rglob("*"):
            if f.is_file():
                z.write(f, Path("Rationalis") / f.relative_to(app_dir))
    print(f"{out}  ({out.stat().st_size / 1e6:.0f} MB)")


def package_macos():
    arch = platform.machine()            # arm64 (Apple Silicon) oppure x86_64 (Intel)
    stage = ROOT / "build" / "dmg"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    # ditto conserva collegamenti simbolici e permessi del pacchetto .app (zipfile no)
    subprocess.run(["ditto", str(ROOT / "dist" / "Rationalis.app"), str(stage / "Rationalis.app")], check=True)
    shutil.copy(ROOT / "tools_build" / "LEGGIMI_macOS.txt", stage / "LEGGIMI.txt")
    for f in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy(ROOT / f, stage / f)
    os.symlink("/Applications", stage / "Applicazioni")
    dmg = ROOT / "dist" / f"Rationalis-{__version__}-macos-{arch}.dmg"
    dmg.unlink(missing_ok=True)
    subprocess.run(["hdiutil", "create", "-volname", f"Rationalis {__version__}", "-srcfolder", str(stage),
                    "-ov", "-format", "UDZO", str(dmg)], check=True)
    zip_out = ROOT / "dist" / f"Rationalis-{__version__}-macos-{arch}.zip"
    subprocess.run(["ditto", "-c", "-k", "--keepParent", str(ROOT / "dist" / "Rationalis.app"), str(zip_out)],
                   check=True)
    for f in (dmg, zip_out):
        print(f"{f}  ({f.stat().st_size / 1e6:.0f} MB)")


def main():
    pyinstaller()
    self_test()
    if MAC:
        package_macos()
    elif WIN:
        package_windows()
    else:
        print("Creata dist/Rationalis (Linux): nessun pacchetto aggiuntivo")


if __name__ == "__main__":
    main()
