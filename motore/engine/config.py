"""Caricamento config. Accetta .yml/.yaml (serve PyYAML) oppure .json (zero dipendenze)."""
from __future__ import annotations

import json
from pathlib import Path


def load_config(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config non trovato: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yml", ".yaml"):
        try:
            import yaml
        except ImportError as e:
            raise ImportError(
                "Per i config YAML serve PyYAML:  pip install pyyaml\n"
                "Oppure converti il config in JSON (stessa struttura)."
            ) from e
        return yaml.safe_load(text) or {}
    return json.loads(text)
