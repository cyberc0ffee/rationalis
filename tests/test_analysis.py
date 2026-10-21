from datetime import date
from decimal import Decimal as D

import pytest

from rationalis import analysis as an
from rationalis import movements as mv
from rationalis import transfers as tr
from rationalis.db import SCHEMA_VERSION, Archive, ValidationError


@pytest.fixture
def arc():
    a = Archive.create(None)
    g = lambda n: a.find_by_name("gruppi", n)["id"]  # noqa: E731
    r = lambda n: a.find_by_name("risorse", n)["id"]  # noqa: E731
    sonia = a.insert("soggetti", nome="Sonia")
    vac = a.insert("destinazioni", nome="Vacanze")
    trasp = g("Trasporti")
    carb = a.find_by_name("sottogruppi", "Carburante", gruppo_id=trasp)["id"]
    data = [
        (date(2024, 1, 10), "Stipendi e compensi", None, "Banca c/c", 2000, True, None, None),
        (date(2024, 1, 15), "Trasporti", carb, "Cassa", -50, True, sonia, None),
        (date(2024, 2, 3), "Trasporti", carb, "Cassa", -60, True, None, vac),
        (date(2024, 2, 20), "Alimentari", None, "Cassa", -120, True, sonia, None),
        (date(2024, 3, 1), "Alimentari", None, "Banca c/c", -700, True, None, None),
        (date(2024, 3, 2), "Alimentari", None, "Banca c/c", -999, False, None, None),   # non saldato
        (date(2023, 2, 3), "Trasporti", None, "Cassa", -40, True, None, vac),
    ]
    for d, grp, sub, res, imp, s, sogg, dest in data:
        mv.save(a, mv.Movement(data=d, risorsa_id=r(res), gruppo_id=g(grp), sottogruppo_id=sub, importo=D(imp),
                               saldato=s, soggetto_id=sogg, destinazione_id=dest))
    tr.save(a, tr.Transfer(date(2024, 1, 20), tr.Leg(r("Banca c/c"), D(300)), [tr.Leg(r("Cassa"), D(300))],
                           saldato=True))
    yield a
    a.close()


def test_filter_basics(arc):
    movs = an.filtered(arc, an.Filter(date(2024, 1, 1), date(2024, 12, 31)))
    assert len(movs) == 5                                     # niente giroconti, niente non saldati
    assert all(not m.is_transfer for m in movs)
    t = an.totals(arc, movs)
    assert t["entrate"] == 2000 and t["uscite"] == 930
    assert len(an.filtered(arc, an.Filter(saldato="tutti", tipo="uscite"))) == 6
    sonia = arc.find_by_name("soggetti", "Sonia")["id"]
    assert len(an.filtered(arc, an.Filter(soggetti=[sonia]))) == 2


def test_filter_raggruppamento_and_exclusivity(arc):
    """Raggruppamento «Trasporti complessivi» con il gruppo Trasporti intero (esempio della guida)."""
    rg = arc.insert("raggruppamenti", nome="Trasporti complessivi")
    arc.insert("raggruppamenti_voci", raggruppamento_id=rg, gruppo_id=arc.find_by_name("gruppi", "Trasporti")["id"])
    movs = an.filtered(arc, an.Filter(raggruppamento_id=rg))
    assert sorted(m.importo for m in movs) == [D(-60), D(-50), D(-40)]
    vac = arc.find_by_name("destinazioni", "Vacanze")["id"]
    q = an.Filter(date(2024, 1, 1), date(2024, 12, 31), tipo="uscite", raggruppamento_id=rg, destinazioni=[vac])
    assert [m.importo for m in an.filtered(arc, q)] == [D(-60)]   # «quanto ho speso di trasporti in vacanza?»
    with pytest.raises(ValidationError):
        an.Filter(gruppi=[1], raggruppamento_id=rg).to_sql()


def test_saved_search_roundtrip(arc):
    f = an.Filter(date(2024, 1, 1), None, tipo="uscite", descrizione="pane", risorse=[1])
    sid = an.save_search(arc, "Uscite 2024", f)
    assert an.load_search(arc, sid) == f


def test_summary_three_periods(arc):
    periods = [an.period("bimestre", 2024, 1), an.period("bimestre", 2024, 2), an.period("anno", 2023)]
    assert periods[1].start == date(2024, 3, 1) and periods[1].end == date(2024, 4, 30)
    rows, tot = an.summary(arc, "gruppo", periods)
    by = {r.label: r for r in rows}
    assert by["Trasporti"].values == [D(-110), D(0), D(-40)]
    assert by["Alimentari"].values == [D(-120), D(-700), D(0)]
    assert by["Trasporti"].total == D(-150) and by["Trasporti"].mean == D(-50)
    assert tot.values == [D(1770), D(-700), D(-40)]
    rows, _ = an.summary(arc, "sottogruppo", periods)
    assert any(r.label == "Trasporti / Carburante" for r in rows)


def test_summary_twelve_months_and_filter(arc):
    sonia = arc.find_by_name("soggetti", "Sonia")["id"]
    rows, tot = an.summary(arc, "gruppo", an.twelve_months(2023, 11), an.Filter(soggetti=[sonia]))
    assert len(tot.values) == 12 and tot.values[2] == D(-50) and tot.values[3] == D(-120)


def test_monitor(arc):
    rows, tot = an.monitor(arc, date(2024, 1, 1), date(2024, 12, 31), "mese")
    assert [r.label for r in rows] == ["Gennaio 2024", "Febbraio 2024", "Marzo 2024"]
    jan = rows[0]
    assert (jan.n_entrate, jan.entrate, jan.n_uscite, jan.uscite) == (1, D(2000), 1, D(50))
    assert tot.n == 5 and tot.saldo == D(1070)
    rows, _ = an.monitor(arc, date(2024, 1, 1), date(2024, 12, 31), "valore")
    assert [r.label for r in rows] == ["da 50 a 100", "da 100 a 500", "da 500 a 1.000", "da 1.000 a 5.000"]
    assert round(an.share(rows[0].n, tot.n)) == 40


def test_chart_data_other(arc):
    pairs = an.chart_data(arc, date(2024, 1, 1), date(2024, 12, 31), "gruppo")
    assert pairs[0] == ("Alimentari", D(820)) and pairs[1] == ("Trasporti", D(110))
    folded = an.chart_data(arc, date(2023, 1, 1), date(2024, 12, 31), "sottogruppo", max_items=2)
    assert folded[-1][0] == "Altro"


def test_budget_and_variance(arc):
    alim = arc.find_by_name("gruppi", "Alimentari")["id"]
    stip = arc.find_by_name("gruppi", "Stipendi e compensi")["id"]
    an.set_budget(arc, alim, an.assisted_budget(D(6000), "annuale"))
    an.set_budget(arc, stip, an.assisted_budget(D(1900), "mensile"))
    assert an.budget_of(arc, alim) == [D(500)] * 12
    lines = {ln.gruppo: ln for ln in an.budget_variance(arc, 2024, 1, 3)}
    assert set(lines) == {"Alimentari", "Stipendi e compensi"}
    a = lines["Alimentari"]
    assert a.consuntivo == [D(0), D(-120), D(-700)]
    assert a.budget == [D(-500)] * 3
    assert a.scostamento == [D(500), D(380), D(-200)]       # positivo = meno spesa del previsto
    assert lines["Stipendi e compensi"].scostamento[0] == D(100)  # più entrata del previsto
    assert len(an.budget_variance(arc, 2024, 1, 3, only_with_budget=False)) == 3
    sheet = an.budget_sheet(arc)
    assert [s[0] for s in sheet] == ["Alimentari", "Stipendi e compensi"]


def test_assisted_budget_rounding():
    vals = an.assisted_budget(D(1000), "annuale")
    assert sum(vals) == D(1000) and vals[0] == D("83.33") and vals[-1] == D("83.37")


def test_month_totals(arc):
    t = an.month_totals(arc, 2024, 2, None)
    assert t["mese"]["uscite"] == D(180) and t["anno"]["entrate"] == D(2000)


def test_migration_from_v1(tmp_path):
    import sqlite3
    p = tmp_path / "vecchio.rtl"
    Archive.create(p).close()
    c = sqlite3.connect(p)
    c.execute("DROP TABLE ricerche")
    c.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    c.commit()
    c.close()
    a = Archive.open(p)
    assert a.setting("schema_version") == str(SCHEMA_VERSION)
    an.save_search(a, "prova", an.Filter())
    a.close()
