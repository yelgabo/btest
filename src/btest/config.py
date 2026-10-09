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
    holdout_start: date


def load(root: Path = ROOT, need_alpaca: bool = True, dotenv: bool = True) -> Settings:
    if dotenv:
        load_dotenv(root / ".env")
    with open(root / "btest.toml", "rb") as f:
        cfg = tomllib.load(f)
    missing = [k for k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY") if not os.environ.get(k)]
    if missing and need_alpaca:
        raise SystemExit(f"missing in .env: {', '.join(missing)}")
    return Settings(
        alpaca_key=os.environ.get("ALPACA_API_KEY", ""),
        alpaca_secret=os.environ.get("ALPACA_SECRET_KEY", ""),
        database_url=os.environ.get("DATABASE_URL", "postgresql://localhost:5432/btest"),
        data_dir=Path(os.environ.get("BTEST_DATA_DIR") or root / cfg.get("data_dir", "data")),
        symbols=list(cfg["symbols"]),
        history_start=cfg["history_start"],
        holdout_start=cfg["holdout_start"],
    )
