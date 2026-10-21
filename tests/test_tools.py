from datetime import date
from decimal import Decimal as D

import pytest

from rationalis import movements as mv
from rationalis import tools
from rationalis.backup import make_backup, restore_backup
from rationalis.db import Archive, ArchiveError, InUseError, PasswordRequired, ValidationError
from rationalis.finance import Investment
from rationalis.security import MAGIC, is_encrypted


@pytest.fixture
def arc():
    a = Archive.create(None)
    yield a
    a.close()


# --- rubrica --------------------------------------------------------------------
def test_addressbook(arc, tmp_path):
    sonia = arc.insert("soggetti", nome="Sonia")
    tools.save_contact(arc, {"nome": "APIX Srl", "riferimento": "Ing. Rossi", "tel1": "049 123", "desc1": "ufficio",
                             "email": "info@example.com", "citta": "Padova", "cap": "35100"})
    tools.save_contact(arc, {"nome": "Bianchi Anna", "tel1": "333 444", "desc1": "cellulare", "soggetto_id": sonia})
    tools.save_contact(arc, {"nome": "3M Italia"})
    assert [r["nome"] for r in tools.contacts(arc)] == ["3M Italia", "APIX Srl", "Bianchi Anna"]
    assert [r["nome"] for r in tools.contacts(arc, letter="#")] == ["3M Italia"]
    assert [r["nome"] for r in tools.contacts(arc, soggetto_id=sonia)] == ["Bianchi Anna"]
    first = tools.search_contacts(arc, "padova")
    assert first["nome"] == "APIX Srl"
    assert tools.search_contacts(arc, "padova", after_id=first["id"]) is None
    assert tools.search_contacts(arc, "bian", ["nome"], "inizio")["nome"] == "Bianchi Anna"
    with pytest.raises(ValidationError):
        tools.save_contact(arc, {"nome": " "})
    p = tmp_path / "rubrica.csv"
    tools.export_contacts(arc, p)
    text = p.read_text(encoding="utf-8-sig")
    assert '"APIX Srl";' in text and '"Sonia"' in text
    h, rows = tools.contacts_for_print(arc, "mini", from_name="A", to_name="AZZZ")
    assert rows == [["APIX Srl – Ing. Rossi", "049 123 (ufficio)"]]
    with pytest.raises(InUseError):
        arc.delete("soggetti", sonia)       # usato dalla rubrica


# --- agenda e annotazioni --------------------------------------------------------------
def test_agenda_and_notes(arc):
    tools.agenda_set(arc, date(2026, 5, 10), "rinnovo patente entro il 25/5", remind=True)
    tools.agenda_set(arc, date(2026, 5, 20), "dentista")
    assert tools.agenda_get(arc, date(2026, 5, 10)) == ("rinnovo patente entro il 25/5", True)
    assert tools.agenda_days(arc, 2026, 5) == {10, 20}
    assert tools.agenda_neighbour(arc, date(2026, 5, 10)) == date(2026, 5, 20)
    assert tools.agenda_neighbour(arc, date(2026, 5, 20), backwards=True) == date(2026, 5, 10)
    assert tools.agenda_neighbour(arc, date(2026, 1, 1), text="PATENTE") == date(2026, 5, 10)
    assert tools.reminders(arc, date(2026, 5, 10)) == [(date(2026, 5, 10), "rinnovo patente entro il 25/5")]
    tools.agenda_set(arc, date(2026, 5, 20), "")
    assert tools.agenda_days(arc, 2026, 5) == {10}
    tools.month_note_set(arc, 2026, 5, "mese delle vacanze")
    assert tools.month_note_get(arc, 2026, 5) == "mese delle vacanze"
    with pytest.raises(ValidationError):
        tools.month_note_set(arc, 2026, 5, "x" * 32_001)


# --- schede libere -----------------------------------------------------------------------
def test_free_cards_examples(arc):
    """Esempi della guida: Viacard a scalare, videoteca con moltiplicatore, lavoro a ore."""
    via = [tools.CardRow(None, "apertura scheda", D(100)), tools.CardRow(date(2026, 3, 2), "Padova-Bologna", D("-7.6"))]
    sid = tools.save_card(arc, "Viacard", via)
    assert tools.card_totals(tools.card_rows(arc, sid), None) == (D("92.4"), None)
    video = [tools.CardRow(None, "apertura scheda", D(10)), tools.CardRow(date(2026, 3, 5), "Film", D(-1))]
    assert tools.card_totals(video, D("2.5")) == (D(9), D("22.5"))
    ore = [tools.CardRow(date(2002, 1, 10), "Manutenzione", D("1.5")), tools.CardRow(date(2002, 1, 3), "", D(8)),
           tools.CardRow(None, "nota", None)]
    assert tools.card_totals(ore, D(65))[1] == D("617.5")
    assert [r.descrizione for r in tools.sort_card_by_date(ore)] == ["", "Manutenzione", "nota"]
    with pytest.raises(ValidationError):
        tools.save_card(arc, "Troppe", [tools.CardRow(None, "x", D(1))] * 1001)


def test_investments(arc):
    inv = Investment(D(1000), date(2023, 5, 4), D(1150), date(2023, 11, 15))
    iid = tools.save_investment(arc, "BTP", inv, 2)
    nome, inv2, cap = tools.load_investment(arc, iid)
    assert (nome, inv2, cap) == ("BTP", inv, 2)


def test_start_page(arc):
    banca = arc.find_by_name("risorse", "Banca c/c")["id"]
    casa = arc.find_by_name("gruppi", "Casa")["id"]
    mv.save(arc, mv.Movement(data=date(2026, 10, 1), risorsa_id=banca, gruppo_id=casa, importo=D(-800)))
    mv.save(arc, mv.Movement(data=date(2026, 10, 22), risorsa_id=banca, gruppo_id=casa, importo=D(-50)))
    mv.save(arc, mv.Movement(data=date(2026, 12, 1), risorsa_id=banca, gruppo_id=casa, importo=D(-50)))
    tools.agenda_set(arc, date(2026, 10, 20), "chiamare il commercialista", remind=True)
    d = tools.start_page_data(arc, date(2026, 10, 20))
    assert len(d["scadute"]) == 1 and len(d["in_scadenza"]) == 1
    assert d["promemoria"][0][1] == "chiamare il commercialista"
    assert d["statistiche"]["movimenti"] == 3


# --- codice d'accesso --------------------------------------------------------------------
def test_password_protection(tmp_path):
    p = tmp_path / "segreto.rtl"
    a = Archive.create(p)
    cassa = a.find_by_name("risorse", "Cassa")["id"]
    a.set_password("Gatto-42")
    assert a.encrypted and is_encrypted(p)
    assert b"Cassa" not in p.read_bytes()                 # nessun testo in chiaro nel file
    mv.save(a, mv.Movement(data=date(2026, 1, 2), risorsa_id=cassa, gruppo_id=a.find_by_name("gruppi", "Spese varie")
                           ["id"], importo=D(-12), descrizione="Giornale"))
    a.insert("soggetti", nome="Scritto senza transazione")  # scrittura fuori da tx(): salvata alla chiusura
    a.close()
    with pytest.raises(PasswordRequired):
        Archive.open(p)
    with pytest.raises(ArchiveError):
        Archive.open(p, "sbagliato")
    b = Archive.open(p, "Gatto-42")
    assert mv.list_month(b, 2026, 1, cassa)[0].descrizione == "Giornale"
    assert b.find_by_name("soggetti", "Scritto senza transazione") is not None
    # copia di sicurezza cifrata e ripristino col codice
    z = make_backup(b, tmp_path)
    out = tmp_path / "rip"
    out.mkdir()
    restored = restore_backup(z, out)
    assert restored.read_bytes().startswith(MAGIC)
    Archive.open(restored, "Gatto-42").close()
    # cambio codice e rimozione
    b.set_password("Nuovo")
    b.close()
    c = Archive.open(p, "Nuovo")
    c.remove_password()
    assert not is_encrypted(p)
    c.close()
    Archive.open(p).close()


def test_migration_v2_to_v3(tmp_path):
    import sqlite3
    p = tmp_path / "v2.rtl"
    Archive.create(p).close()
    con = sqlite3.connect(p)
    for t in ("rubrica", "agenda", "note_mese", "schede_righe", "schede", "investimenti"):
        con.execute(f"DROP TABLE {t}")
    con.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
    con.commit()
    con.close()
    a = Archive.open(p)
    tools.agenda_set(a, date(2026, 1, 1), "ok")
    a.close()
