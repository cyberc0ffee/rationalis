"""Importazione da archivio DPM: prova sul database Jet 3 sintetico (struttura dedotta, non verificata
su un archivio reale). Il file si rigenera con tests/fixtures/make_dpm_fixture.ps1."""
import zipfile
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from rationalis import balances as bal
from rationalis import movements as mv
from rationalis.interop.dpm import DpmFormatError, import_dpm

FIXTURE = Path(__file__).parent / "fixtures" / "sintetico.dpm"
pytestmark = pytest.mark.skipif(not FIXTURE.exists(), reason="manca il database sintetico")


def test_import_synthetic():
    arc, rep = import_dpm(FIXTURE, None)
    assert rep.counts["Movimenti"] == 3 and rep.counts["Giroconti"] == 1
    cassa = arc.find_by_name("risorse", "Cassa")
    banca = arc.find_by_name("risorse", "Banca c/c 15001")
    visa = arc.find_by_name("risorse", "Visa")
    assert visa["tipo"] == "carta" and visa["banca_id"] == banca["id"]
    assert bal.balance(arc, cassa["id"]) == D(307)          # 100 - 43 + 250
    assert bal.balance(arc, banca["id"]) == D("3600.5")     # 2500,50 + 1350 - 250
    assert arc.find_by_name("gruppi", "Stipendi")["tipo"] == "E"
    assert arc.find_by_name("gruppi", "Caffè e bar")["in_uso"] == 0
    m = [x for x in mv.list_month(arc, 2002, 5, cassa["id"]) if not x.is_transfer][0]
    assert m.descrizione == "Macelleria € e città" and m.controllo == "A"
    assert arc.name_of("soggetti", m.soggetto_id) == "Sonia"
    assert any("scadenze" in w for w in rep.warnings)
    assert arc.rate(arc.find_by_name("valute", "Dollaro USA")["id"]) == D("0.9104")


def test_import_dpz_zip(tmp_path):
    z = tmp_path / "copia.dpz"
    with zipfile.ZipFile(z, "w") as f:
        f.write(FIXTURE, "archivio.dpm")
    arc, rep = import_dpm(z, tmp_path / "nuovo.rtl")
    assert rep.counts["Movimenti"] == 3
    arc.close()
    assert (tmp_path / "nuovo.rtl").exists()


def test_rejects_non_jet(tmp_path):
    p = tmp_path / "falso.dpm"
    p.write_bytes(b"non un database")
    with pytest.raises(DpmFormatError):
        import_dpm(p, None)
    assert not list(tmp_path.glob("*.rtl"))


def test_list_dates_ok():
    arc, _ = import_dpm(FIXTURE, None)
    assert mv.list_month(arc, 2002, 3)[0].data == date(2002, 3, 10)
