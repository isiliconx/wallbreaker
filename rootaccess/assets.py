"""Locate bundled files in a source checkout or an installed wheel."""
from pathlib import Path
import sysconfig


def asset_dir(kind: str) -> Path:
    if kind not in {"batteries", "ladders", "examples"}:
        raise ValueError(f"Unknown asset kind: {kind}")
    checkout = Path(__file__).resolve().parent.parent / kind
    if checkout.is_dir():
        return checkout
    target_install = Path(__file__).resolve().parent.parent / "share" / "rootaccess" / kind
    if target_install.is_dir():
        return target_install
    return Path(sysconfig.get_path("data")) / "share" / "rootaccess" / kind


def resolve_asset(value: str, relative_to: Path | None = None) -> Path:
    path = Path(value).expanduser()
    candidates = [path]
    if relative_to is not None and not path.is_absolute():
        candidates.insert(0, relative_to / path)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    if not path.is_absolute() and path.parts and path.parts[0] in {"batteries", "ladders", "examples"}:
        candidate = asset_dir(path.parts[0]).joinpath(*path.parts[1:])
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"File not found: {value}")
