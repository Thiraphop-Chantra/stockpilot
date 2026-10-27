"""Generator configuration and scale presets.

Every value here is a configured input (a target or a rate), not a result; results are measured
on the generated data and written to ``data/manifest.json``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from typing import Any

PATTERNS = ("smooth", "erratic", "intermittent", "lumpy")


@dataclass(frozen=True)
class IssueRates:
    """How often each deliberate data-quality problem is injected."""

    month_overlap_prob: float = 0.15  # monthly export also contains 1-3 days of the next month
    rerun_months: int = 1  # whole monthly exports delivered twice
    truncated_file_share: float = 0.05  # monthly exports whose material codes lost leading zeros
    extra_zero: float = 0.001  # share of ERP records with a quantity typed with extra zeros
    unit_mismatch: float = 0.002  # share of box-capable records with the wrong unit label
    missing_net_value: float = 0.003  # share of ERP records without a net value
    future_date: float = 0.0005  # share of ERP records with a posting date in the future
    missing_list_price: float = 0.02  # share of materials without a list price
    duplicate_customer: float = 0.04  # share of customers entered a second time


@dataclass(frozen=True)
class SynthConfig:
    preset: str = "default"
    seed: int = 42
    n_skus: int = 2000
    n_customers: int = 600
    n_suppliers: int = 60
    start: date = date(2021, 1, 1)
    history_years: int = 5
    warmup_days: int = 120
    horizon_days: int = 181
    pattern_mix: tuple[tuple[str, float], ...] = (
        ("smooth", 0.35),
        ("erratic", 0.15),
        ("intermittent", 0.30),
        ("lumpy", 0.20),
    )
    issues: IssueRates = field(default_factory=IssueRates)

    def __post_init__(self) -> None:
        names = [name for name, _ in self.pattern_mix]
        total = sum(share for _, share in self.pattern_mix)
        if sorted(names) != sorted(PATTERNS) or abs(total - 1.0) > 1e-9:
            raise ValueError(f"pattern_mix must give a share for each of {PATTERNS} summing to 1")

    @classmethod
    def from_preset(cls, name: str, **overrides: Any) -> SynthConfig:
        if name not in PRESETS:
            raise ValueError(f"unknown preset {name!r}; choose one of {sorted(PRESETS)}")
        return replace(PRESETS[name], **overrides)

    @property
    def history_end(self) -> date:
        return date(self.start.year + self.history_years, self.start.month, self.start.day) - (
            timedelta(days=1)
        )

    @property
    def extraction_date(self) -> date:
        """The day the ERP exports were pulled: the first day after the history."""
        return self.history_end + timedelta(days=1)

    @property
    def horizon_end(self) -> date:
        return self.history_end + timedelta(days=self.horizon_days)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start"] = self.start.isoformat()
        payload["pattern_mix"] = dict(self.pattern_mix)
        return payload


PRESETS: dict[str, SynthConfig] = {
    "default": SynthConfig(),
    "small": SynthConfig(
        preset="small", n_skus=240, n_customers=120, n_suppliers=20, history_years=2
    ),
    "tiny": SynthConfig(preset="tiny", n_skus=60, n_customers=40, n_suppliers=8, history_years=1),
}
