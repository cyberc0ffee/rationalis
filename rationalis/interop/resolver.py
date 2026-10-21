"""Ricerca o creazione delle voci di tabella per nome, usata dalle importazioni."""
from ..db import Archive, TIPI_RISORSA
from . import ImportReport

TRANSFER_MARK = "<giroconto>"


def guess_resource_type(nome: str) -> str:
    n = nome.lower()
    if "carta" in n or "visa" in n or "mastercard" in n or "amex" in n or "american express" in n:
        return "carta"
    if "cassa" in n or "contanti" in n:
        return "cassa"
    if "posta" in n or "bancoposta" in n:
        return "posta"
    if "banca" in n or "c/c" in n or "conto" in n:
        return "banca"
    if "libretto" in n or "deposito" in n:
        return "deposito"
    return "altro"


class Resolver:
    def __init__(self, arc: Archive, report: ImportReport):
        self.arc = arc
        self.report = report

    def gruppo(self, nome: str, sign: int) -> int:
        """Gruppo per nome; se manca lo crea (entrata/uscita secondo il segno). Se esiste con tipo
        incompatibile lo rende misto, come consentito per i gruppi già usati."""
        want = "E" if sign > 0 else "U" if sign < 0 else "M"
        g = self.arc.find_by_name("gruppi", nome)
        if g is None:
            self.report.add("Gruppi creati")
            return self.arc.insert("gruppi", nome=nome.strip(), tipo=want)
        if want != "M" and g["tipo"] not in (want, "M"):
            self.arc.update("gruppi", g["id"], tipo="M")
            self.report.warn(f"Il gruppo «{g['nome']}» contiene entrate e uscite: impostato come misto")
        return g["id"]

    def sottogruppo(self, gruppo_id: int, nome: str) -> int:
        s = self.arc.find_by_name("sottogruppi", nome, gruppo_id=gruppo_id)
        if s is None:
            self.report.add("Sottogruppi creati")
            return self.arc.insert("sottogruppi", gruppo_id=gruppo_id, nome=nome.strip())
        return s["id"]

    def risorsa(self, nome: str) -> int:
        r = self.arc.find_by_name("risorse", nome)
        if r is not None:
            return r["id"]
        tipo = guess_resource_type(nome)
        banca_id = None
        if tipo == "carta":
            b = self.arc.rows("risorse", "tipo = 'banca'", order="id")
            if b:
                banca_id = b[0]["id"]
            else:
                tipo = "altro"
                self.report.warn(f"«{nome}» sembra una carta di credito ma non c'è una banca da associare: "
                                 "creata come risorsa generica")
        self.report.add("Risorse create")
        rid = self.arc.insert("risorse", nome=nome.strip(), tipo=tipo, valuta_id=self.arc.principal()["id"],
                              banca_id=banca_id)
        if tipo != "altro":
            self.report.warn(f"Risorsa «{nome}» creata come {TIPI_RISORSA[tipo].lower()} in valuta principale: "
                             "controllare tipo e valuta nella tabella risorse")
        return rid

    def simple(self, table: str, nome: str, label: str) -> int:
        r = self.arc.find_by_name(table, nome)
        if r is None:
            self.report.add(label)
            return self.arc.insert(table, nome=nome.strip())
        return r["id"]

    def modalita(self, risorsa_id: int, nome: str) -> int:
        m = self.arc.find_by_name("modalita", nome, risorsa_id=risorsa_id)
        if m is None:
            self.report.add("Modalità di pagamento create")
            return self.arc.insert("modalita", risorsa_id=risorsa_id, nome=nome.strip())
        return m["id"]
