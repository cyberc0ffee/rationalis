from datetime import date
from decimal import Decimal as D

from rationalis import balances as bal
from rationalis import movements as mv
from rationalis import transfers as tr
from rationalis.backup import make_backup, restore_backup
from rationalis.db import Archive
from rationalis.interop.tabular import export_csv, export_html, export_xlsx, import_rows, import_xlsx


def test_excel_example_from_guide():
    """Il foglio di esempio della guida: commento in A1, intestazione in riga 4."""
    rows = [
        ("Commento interno: importare a fine Febbraio", None, None, None, None),
        (None,) * 5, (None,) * 5,
        ("Gruppo", "Risorsa", "Entrata", "Uscita", "Data"),
        ("Trasporti", "Banca c/c", None, 55.0, "4/2/2003"),
        ("Ristorante", "Cassa", None, 22.40, "5/2/2003"),
        ("Vendite prodotti", "Banca c/c", 165.0, None, "5/2/2003"),
        ("Stipendi", "Banca c/c", None, "5.600,00", "8/2/2003"),
        (None,) * 5,
        ("Dopo la riga vuota", "Cassa", 1, None, "9/2/2003"),
    ]
    arc = Archive.create(None)
    rep = import_rows(arc, rows)
    assert rep.counts["Movimenti importati"] == 4
    movs = mv.list_month(arc, 2003, 2)
    assert sorted(m.importo for m in movs) == [D(-5600), D(-55), D("-22.4"), D(165)]
    assert arc.find_by_name("gruppi", "Ristorante")["tipo"] == "U"
    assert arc.find_by_name("gruppi", "Vendite prodotti")["tipo"] == "E"


def test_roundtrip_with_transfer(tmp_path):
    arc = Archive.create(None)
    cassa = arc.find_by_name("risorse", "Cassa")["id"]
    banca = arc.find_by_name("risorse", "Banca c/c")["id"]
    g = arc.find_by_name("gruppi", "Alimentari")["id"]
    mv.save(arc, mv.Movement(data=date(2024, 6, 3), risorsa_id=cassa, gruppo_id=g, importo=D("-43.10"),
                             saldato=True, descrizione="Macelleria", controllo="A"))
    tr.save(arc, tr.Transfer(date(2024, 6, 4), tr.Leg(banca, D(250)), [tr.Leg(cassa, D(250))], saldato=True,
                             descrizione="Prelievo bancomat"))
    x = tmp_path / "mov.xlsx"
    export_xlsx(arc, x, date(2024, 1, 1), date(2024, 12, 31))
    export_csv(arc, tmp_path / "mov.tsv", date(2024, 1, 1), date(2024, 12, 31))
    export_html(arc, tmp_path / "mov.html", date(2024, 1, 1), date(2024, 12, 31))

    arc2 = Archive.create(None)
    rep = import_xlsx(arc2, x)
    assert rep.counts["Movimenti importati"] == 1 and rep.counts["Giroconti importati"] == 1
    c2 = arc2.find_by_name("risorse", "Cassa")["id"]
    assert bal.balance(arc2, c2) == bal.balance(arc, cassa) == D("206.90")
    assert "<giroconto>" in (tmp_path / "mov.tsv").read_text(encoding="utf-8-sig")


def test_backup_restore(tmp_path):
    p = tmp_path / "casa.rtl"
    arc = Archive.create(p)
    arc.set_setting("decimali", "3")
    z = make_backup(arc, tmp_path)
    arc.close()
    out = tmp_path / "ripristino"
    out.mkdir()
    restored = restore_backup(z, out)
    a2 = Archive.open(restored)
    assert a2.decimals == 3
    a2.close()
