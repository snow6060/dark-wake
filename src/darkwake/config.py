"""Central config, loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _chokepoint_registry() -> dict[str, list[str]]:
    """Maps our internal chokepoint key -> substrings to match against the
    PortWatch `portname` field (case-insensitive).

    Matching by name substring (instead of hardcoding a `portid`) is
    deliberate: IMF hasn't published a stable, documented portid list for
    this table, and portname strings are visibly stable in the data. Adding
    a new chokepoint later is just adding an entry here.
    """
    return {
        "hormuz": ["hormuz"],
        "bab_el_mandeb": ["mandab", "mandeb"],  # PortWatch spells it "Mandab"
    }


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///data/darkwake.db")
    )
    portwatch_url: str = field(
        default_factory=lambda: os.getenv(
            "PORTWATCH_FEATURE_SERVER_URL",
            "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/ArcGIS/rest/"
            "services/Daily_Chokepoints_Data/FeatureServer/0/query",
        )
    )
    lookback_days: int = field(
        default_factory=lambda: int(os.getenv("PORTWATCH_LOOKBACK_DAYS", "120"))
    )
    ingest_interval_hours: int = field(
        default_factory=lambda: int(os.getenv("INGEST_INTERVAL_HOURS", "1"))
    )
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: int(os.getenv("API_PORT", "8000")))
    chokepoints: dict[str, list[str]] = field(default_factory=_chokepoint_registry)


settings = Settings()
