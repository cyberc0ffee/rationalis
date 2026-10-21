"""Calcolo dei rendimenti finanziari (RIN e REN)."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .money import ZERO


@dataclass
class Investment:
    capitale_iniziale: Decimal
    data_inizio: date
    capitale_finale: Decimal
    data_fine: date
    rendite: Decimal = ZERO
    tasse: Decimal = ZERO
    bolli: Decimal = ZERO
    spese: Decimal = ZERO

    @property
    def utile_netto(self) -> Decimal:
        return (self.capitale_finale - self.capitale_iniziale + self.rendite
                - self.tasse - self.bolli - self.spese)

    @property
    def utile_percentuale(self) -> Decimal:
        if self.capitale_iniziale == 0:
            raise ValueError("Il capitale iniziale deve essere diverso da zero")
        return self.utile_netto / self.capitale_iniziale * 100

    @property
    def giorni(self) -> int:
        return (self.data_fine - self.data_inizio).days

    @property
    def rin(self) -> Decimal:
        """Rendimento immediato netto: utile percentuale riportato a un anno (365 giorni)."""
        if self.giorni <= 0:
            raise ValueError("La data di fine deve seguire la data di inizio")
        return self.utile_percentuale * 365 / self.giorni


def ren_from_rin(rin_percent: Decimal, periods_per_year: int) -> Decimal:
    """Rendimento effettivo netto con capitalizzazione degli interessi `periods_per_year` volte l'anno."""
    if periods_per_year < 1:
        raise ValueError("Il numero di capitalizzazioni annue deve essere almeno 1")
    r = Decimal(rin_percent) / 100 / periods_per_year
    return ((1 + r) ** periods_per_year - 1) * 100
