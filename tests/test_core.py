from datetime import date
from decimal import Decimal as D

import pytest

from rationalis import balances as bal
from rationalis import movements as mv
from rationalis import scheduler as sch
from rationalis import transfers as tr
from rationalis.db import Archive, InUseError, ValidationError
from rationalis.finance import Investment, ren_from_rin
from rationalis.money import fmt_amount, parse_amount, round_to
from rationalis.recurrence import Plan, describe, occurrences


@pytest.fixture
def arc():
    a = Archive.create(None)
    yield a
    a.close()


def gid(arc, nome):
    return arc.find_by_name("gruppi", nome)["id"]


def rid(arc, nome):
    return arc.find_by_name("risorse", nome)["id"]


# --- importi ---------------------------------------------------------------
@pytest.mark.parametrize("text,value", [
    ("1350", D("1350")), ("1.350", D("1350")), ("1.350,50", D("1350.50")), ("12.5", D("12.5")),
    ("-7,6", D("-7.6")), ("€ 22,40", D("22.40")), ("", D(0)),
])
def test_parse_amount(text, value):
    assert parse_amount(text) == value


def test_fmt_amount():
    assert fmt_amount(D("5600"), 2) == "5.600,00"
    assert fmt_amount(D("-1234567.891"), 2) == "-1.234.567,89"
    assert fmt_amount(D(0), 2, blank_zero=True) == ""


# --- movimenti e disponibilità ---------------------------------------------
def test_stipendio_example(arc):
    """Esempio della guida: stipendio di 1.350 € il 10/3/2002 sul conto, saldato."""
    banca = rid(arc, "Banca c/c")
    mv.save(arc, mv.Movement(data=date(2002, 3, 10), risorsa_id=banca, gruppo_id=gid(arc, "Stipendi e compensi"),
                             importo=D(1350), saldato=True))
    assert bal.balance(arc, banca, date(2002, 3, 9)) == 0
    assert bal.balance(arc, banca, date(2002, 3, 31)) == 1350
    bar = bal.availability_bar(arc, 2002, 3, banca, today=date(2002, 3, 15))
    assert bar["fine_mese_precedente"] == 0 and bar["fine_mese"] == 1350 and bar["oggi"] == 1350


def test_group_type_enforced(arc):
    with pytest.raises(ValidationError):
        mv.save(arc, mv.Movement(data=date(2024, 1, 1), risorsa_id=rid(arc, "Cassa"),
                                 gruppo_id=gid(arc, "Alimentari"), importo=D(10)))
    mv.save(arc, mv.Movement(data=date(2024, 1, 1), risorsa_id=rid(arc, "Cassa"),
                             gruppo_id=gid(arc, "Rettifiche"), importo=D(10)))


def test_unsettled_only_in_projection(arc):
    cassa = rid(arc, "Cassa")
    mv.save(arc, mv.Movement(data=date(2024, 5, 2), risorsa_id=cassa, gruppo_id=gid(arc, "Alimentari"),
                             importo=D(-43), saldato=False))
    assert bal.balance(arc, cassa) == 0
    assert bal.balance(arc, cassa, include_unsettled=True) == -43


def test_paste_clamps_day(arc):
    cassa = rid(arc, "Cassa")
    i = mv.save(arc, mv.Movement(data=date(2002, 5, 31), risorsa_id=cassa, gruppo_id=gid(arc, "Spese varie"),
                                 importo=D(-5)))
    new = mv.paste_into_month(arc, [mv.get(arc, i)], 2002, 6)
    assert mv.get(arc, new[0]).data == date(2002, 6, 30)


def test_delete_in_use(arc):
    g = gid(arc, "Abbigliamento")
    mv.save(arc, mv.Movement(data=date(2024, 1, 1), risorsa_id=rid(arc, "Cassa"), gruppo_id=g, importo=D(-1)))
    with pytest.raises(InUseError):
        arc.delete("gruppi", g)
    arc.delete("gruppi", gid(arc, "Salute"))  # mai usato: si cancella con i suoi sottogruppi
    assert arc.find_by_name("gruppi", "Salute") is None


def test_find(arc):
    cassa = rid(arc, "Cassa")
    mv.save(arc, mv.Movement(data=date(2024, 1, 3), risorsa_id=cassa, gruppo_id=gid(arc, "Spese varie"),
                             importo=D(-9), descrizione="Libro DANEA"))
    assert mv.find(arc, "danea").descrizione == "Libro DANEA"
    assert mv.find(arc, "9", mode="importi") is not None
    assert mv.find(arc, "", mode="non_saldato") is not None


def test_bulk_change(arc):
    cassa = rid(arc, "Cassa")
    ab, sport = gid(arc, "Abbigliamento"), gid(arc, "Tempo libero")
    acc = arc.find_by_name("sottogruppi", "Sport", gruppo_id=sport)["id"]
    mv.save(arc, mv.Movement(data=date(2024, 1, 3), risorsa_id=cassa, gruppo_id=ab, importo=D(-60)))
    assert mv.bulk_change(arc, "gruppo", ab, sport, new_sub_id=acc) == 1
    assert mv.list_month(arc, 2024, 1)[0].sottogruppo_id == acc


# --- giroconti --------------------------------------------------------------
def test_transfer_exchange_example(arc):
    """Esempio della guida: 100 € → 90 US$ a cambio 0,9; con cambio 0,95 lo sbilancio è 5,26 €."""
    usd = arc.insert("valute", sigla="US$", nome="Dollaro USA", cambio="0.9")
    c_eur = arc.add_risorsa("Cassa Euro", "cassa", arc.principal()["id"], D(1000))
    c_usd = arc.add_risorsa("Cassa Usa", "cassa", usd, D(400))
    t = tr.Transfer(date(2024, 1, 10), tr.Leg(c_eur, D(100)), [tr.Leg(c_usd, D(90))], saldato=True)
    assert tr.imbalance(arc, t) == 0
    tid = tr.save(arc, t)
    assert bal.balance(arc, c_eur) == 900 and bal.balance(arc, c_usd) == 490
    arc.update("valute", usd, cambio="0.95")
    assert round_to(tr.imbalance(arc, tr.get(arc, tid)), 2) == D("5.26")
    assert bal.balance(arc, c_eur) == 900 and bal.balance(arc, c_usd) == 490


def test_transfer_split_and_rules(arc):
    """1.620 € dalla cassa: 1.000 in banca e 620 in posta."""
    eur = arc.principal()["id"]
    posta = arc.add_risorsa("Posta", "posta", eur)
    cassa, banca = rid(arc, "Cassa"), rid(arc, "Banca c/c")
    with pytest.raises(ValidationError):
        tr.save(arc, tr.Transfer(date(2024, 2, 1), tr.Leg(cassa, D(1620)), [tr.Leg(banca, D(1000))]))
    t = tr.Transfer(date(2024, 2, 1), tr.Leg(cassa, D(1620)), [tr.Leg(banca, D(1000)), tr.Leg(posta, D(0.01))])
    assert tr.balancing_amount(arc, t, 1) == D("620")
    t.versamenti[1].importo = D(620)
    tid = tr.save(arc, t)
    legs = mv.list_month(arc, 2024, 2, cassa)
    assert len(legs) == 1 and legs[0].is_transfer
    assert mv.list_month(arc, 2024, 2, None) == []           # con «tutte» i giroconti non appaiono
    assert mv.delete(arc, [legs[0].id]) == (0, 1)            # non cancellabile dall'elenco
    mv.toggle_settled(arc, [legs[0].id])
    assert tr.get(arc, tid).saldato is True
    assert bal.balance(arc, posta) == 620


def test_credit_card_charge(arc):
    """Spese carta 407 €, addebito in banca con 1 € di commissioni."""
    eur = arc.principal()["id"]
    carta = arc.add_risorsa("Visa", "carta", eur)
    banca = rid(arc, "Banca c/c")
    mv.save(arc, mv.Movement(data=date(2024, 3, 5), risorsa_id=carta, gruppo_id=gid(arc, "Tempo libero"),
                             importo=D(-407), saldato=True))
    assert tr.card_balance(arc, carta) == -407
    comm = gid(arc, "Spese bancarie")
    tr.charge_credit_card(arc, carta, D(407), date(2024, 3, 31), commissione=D(1), gruppo_id=comm)
    assert bal.balance(arc, carta) == 0
    assert bal.balance(arc, banca) == -408
    assert tr.default_card_charge_date(date(2024, 4, 15)) == date(2024, 3, 31)


# --- scadenzario -------------------------------------------------------------
@pytest.mark.parametrize("plan,n,first,last", [
    (Plan(date(2002, 2, 10), "M", count=40, monthday=15), 40, date(2002, 2, 15), date(2005, 5, 15)),
    (Plan(date(2002, 1, 1), "S", end=date(2002, 12, 31), weekday=0), 52, date(2002, 1, 7), date(2002, 12, 30)),
    (Plan(date(2002, 1, 1), "M", end=date(2002, 6, 30), monthday=-1), 6, date(2002, 1, 31), date(2002, 6, 30)),
    (Plan(date(2002, 2, 1), "G", end=date(2002, 2, 28)), 28, date(2002, 2, 1), date(2002, 2, 28)),
    (Plan(date(2003, 1, 1), "M", step=2, end=date(2003, 12, 31), weekday=0, ordinal=1), 6,
     date(2003, 1, 6), date(2003, 11, 3)),
    (Plan(date(2002, 6, 1), "M", step=12, end=date(2009, 6, 30), monthday=2), 8, date(2002, 6, 2), date(2009, 6, 2)),
])
def test_recurrence_examples(plan, n, first, last):
    """Gli esempi di piano di sviluppo riportati nella guida dello scadenzario."""
    occ = occurrences(plan)
    assert len(occ) == n and occ[0] == first and occ[-1] == last


def test_recurrence_last_weekday_and_describe():
    occ = occurrences(Plan(date(2024, 1, 1), "M", count=3, weekday=4, ordinal=-1))
    assert occ == [date(2024, 1, 26), date(2024, 2, 23), date(2024, 3, 29)]
    assert "primo lunedì" in describe(Plan(date(2003, 1, 1), "M", step=2, count=3, weekday=0, ordinal=1))


def test_schedule_keeps_settled(arc):
    """Rate auto: 36 rate di 460 € il 5 del mese da aprile 2002."""
    banca = rid(arc, "Banca c/c")
    s = sch.Schedule("Rata auto", banca, Plan(date(2002, 4, 1), "M", count=36, monthday=5),
                     gruppo_id=gid(arc, "Trasporti"), importo=D(460))
    sid = sch.save(arc, s)
    movs = arc.rows("movimenti", "scadenza_id=?", (sid,), order="data")
    assert len(movs) == 36 and all(m["importo"] < 0 and not m["saldato"] for m in movs)
    mv.toggle_settled(arc, [movs[0]["id"]])
    mv.save(arc, mv.Movement.from_row(arc.row("movimenti", movs[0]["id"])))
    s.importo = D(470)
    sch.save(arc, s)
    movs = arc.rows("movimenti", "scadenza_id=?", (sid,), order="data")
    assert len(movs) == 36
    assert movs[0]["saldato"] and movs[0]["importo"] == -4_600_000
    assert all(m["importo"] == -4_700_000 for m in movs[1:])
    sch.delete(arc, sid)
    remaining = arc.rows("movimenti", order="id")
    assert len(remaining) == 1 and remaining[0]["scadenza_id"] is None


def test_schedule_transfer(arc):
    cassa, banca = rid(arc, "Cassa"), rid(arc, "Banca c/c")
    sid = sch.save(arc, sch.Schedule("Prelievo settimanale", banca, Plan(date(2024, 1, 1), "S", count=4),
                                     tipo="G", risorsa_dest_id=cassa, importo=D(50)))
    assert len(arc.rows("giroconti", "scadenza_id=?", (sid,), order="id")) == 4
    assert bal.balance(arc, cassa, include_unsettled=True) == 200


def test_mixed_group_sign(arc):
    cassa = rid(arc, "Cassa")
    sch.save(arc, sch.Schedule("Rettifica", cassa, Plan(date(2024, 1, 1), "M", count=1),
                               gruppo_id=gid(arc, "Rettifiche"), importo=D(-1500)))
    assert mv.list_month(arc, 2024, 1)[0].importo == -1500


# --- valute -----------------------------------------------------------------
def test_change_principal_currency(arc):
    eur = arc.principal()["id"]
    usd = arc.insert("valute", sigla="US$", nome="Dollaro", cambio="0.9104")
    arc.conn.execute("INSERT INTO budget VALUES (?, 1, ?)", (gid(arc, "Casa"), 1_000_000))
    arc.set_principal(usd)
    assert arc.principal()["id"] == usd and arc.rate(usd) == 1
    assert round_to(arc.rate(eur), 4) == round_to(D(1) / D("0.9104"), 4)
    assert arc.conn.execute("SELECT importo FROM budget").fetchone()[0] == 910_400


# --- rendimenti --------------------------------------------------------------
@pytest.mark.parametrize("ci,di,cf,df,rin", [
    (1000, date(2023, 5, 4), 1150, date(2023, 11, 15), D("28.08")),
    (10000, date(2023, 6, 2), 11000, date(2023, 10, 30), D("24.33")),
    (13000, date(2023, 3, 1), 15500, date(2023, 12, 31), D("23.01")),
    (5000, date(2023, 4, 15), 5400, date(2023, 8, 15), D("23.93")),
])
def test_rin_examples(ci, di, cf, df, rin):
    """Gli esempi di RIN della guida."""
    assert round_to(Investment(D(ci), di, D(cf), df).rin, 2) == rin


def test_ren_example():
    assert round_to(ren_from_rin(D(6), 2), 2) == D("6.09")
