from decimal import Decimal as D

import pytest

from rationalis.calculator import Calculator


@pytest.mark.parametrize("keys,result", [
    ("20+10+++", D(50)),          # ripetizione dell'ultima operazione
    ("20+10\n", D(30)),
    ("200*5%", D(10)),            # 5% di 200
    ("400+10%", D(440)),          # aggiungere il 10%
    ("1200-35%", D(780)),         # togliere il 35%
    ("7/2\n", D("3.5")),
    ("2*3\n\n", D(18)),           # "=" ripetuto
])
def test_examples(keys, result):
    c = Calculator()
    c.keys(keys)
    assert c.result == result


def test_vat_and_rate_and_errors():
    c = Calculator(vat_rate=D(22))
    c.keys("100")
    c.press("iva+")
    assert c.result == D(122)
    c.press("iva-")
    assert c.result == D(100)
    c.rate = D("0.9")
    c.press("cambio")
    assert c.result == D(90)
    c.keys("/0\n")
    assert c.display == "Errore"
    c.press("canc")
    assert not c.error and c.display == "0,00"
    assert c.tape


def test_entry_editing():
    c = Calculator()
    c.keys("12,5")
    assert c.display == "12,5"
    c.press("back")
    assert c.display == "12,"
    c.press("segno")
    assert c.display == "-12,"
    c.press("canc")
    assert c.display == "0,00"
