"""Geography of the fictional company: provinces, distribution centres and service regions."""

from __future__ import annotations

from dataclasses import dataclass

from stockpilot.synth.names import vocabulary


@dataclass(frozen=True)
class Province:
    name: str  # English name
    name_th: str
    region: str  # central, north, northeast, south
    lat: float
    lon: float
    weight: float  # relative share of customers


@dataclass(frozen=True)
class Warehouse:
    plant: str
    name: str
    province: str
    lat: float
    lon: float


WAREHOUSES: tuple[Warehouse, ...] = (
    Warehouse("1100", "Central DC (Bang Phli)", "Samut Prakan", 13.62, 100.71),
    Warehouse("1200", "Northeast DC (Khon Kaen)", "Khon Kaen", 16.43, 102.84),
    Warehouse("1300", "South DC (Hat Yai)", "Songkhla", 7.01, 100.47),
)

# Each region is served by one distribution centre; the North is served from Bangkok.
REGION_PLANT = {"central": "1100", "north": "1100", "northeast": "1200", "south": "1300"}

# Extra days a shipment from a supplier needs to reach each plant (all arrive via Bangkok).
TRANSIT_DAYS = {"1100": 0, "1200": 2, "1300": 3}


def provinces() -> tuple[Province, ...]:
    return tuple(
        Province(p["en"], p["th"], p["region"], p["lat"], p["lon"], p["weight"])
        for p in vocabulary()["provinces"]
    )
