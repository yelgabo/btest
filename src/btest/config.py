import os
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    alpaca_key: str
    alpaca_secret: str
    database_url: str
    data_dir: Path
    symbols: list[str]
    history_start: date


def load(root: Path = ROOT) -> Settings:
    load_dotenv(root / ".env")
    with open(root / "btest.toml", "rb") as f:
        cfg = tomllib.load(f)
    missing = [k for k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing in .env: {', '.join(missing)}")
    return Settings(
        alpaca_key=os.environ["ALPACA_API_KEY"],
        alpaca_secret=os.environ["ALPACA_SECRET_KEY"],
        database_url=os.environ.get("DATABASE_URL", "postgresql://localhost:5432/btest"),
        data_dir=root / cfg.get("data_dir", "data"),
        symbols=list(cfg["symbols"]),
        history_start=cfg["history_start"],
    )
