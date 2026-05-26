"""Gestione della cache dei binari Rust compilati.

Struttura cache (in ~/.pyfast/cache/):
  <md5_hash>/
    binary          — binario compilato
    source.hash     — hash MD5 del sorgente Python
    rust_source.rs  — codice Rust generato (per debug)

Logica:
  - Hash calcolato sul contenuto del file Python (MD5)
  - Se il binario esiste e l'hash corrisponde → cache HIT
  - Se il binario non esiste o l'hash non corrisponde → cache MISS
"""

import hashlib
import os
import shutil
import stat
from pathlib import Path


# Directory base della cache
CACHE_ROOT = Path.home() / ".pyfast" / "cache"


# ---------------------------------------------------------------------------
# Gestione hash
# ---------------------------------------------------------------------------

def compute_hash(source: str) -> str:
    """Calcola l'hash MD5 del sorgente Python."""
    return hashlib.md5(source.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Percorsi cache
# ---------------------------------------------------------------------------

def cache_dir(source_hash: str) -> Path:
    """Restituisce la directory di cache per un dato hash."""
    return CACHE_ROOT / source_hash


def binary_path(source_hash: str) -> Path:
    """Percorso del binario compilato per un dato hash."""
    return cache_dir(source_hash) / "binary"


def rust_source_path(source_hash: str) -> Path:
    """Percorso del sorgente Rust generato (per debug)."""
    return cache_dir(source_hash) / "rust_source.rs"


def hash_file_path(source_hash: str) -> Path:
    """File che contiene l'hash (usato per verificare validità)."""
    return cache_dir(source_hash) / "source.hash"


# ---------------------------------------------------------------------------
# Operazioni cache
# ---------------------------------------------------------------------------

def is_cached(source_hash: str) -> bool:
    """True se esiste un binario valido in cache per questo hash."""
    binary = binary_path(source_hash)
    return binary.exists() and os.access(binary, os.X_OK)


def store(source_hash: str, rust_source: str, binary_data: bytes) -> None:
    """Salva il sorgente Rust e il binario in cache.

    Args:
        source_hash: Hash MD5 del sorgente Python originale.
        rust_source: Codice Rust generato (stringa).
        binary_data: Contenuto del binario compilato (bytes).
    """
    d = cache_dir(source_hash)
    d.mkdir(parents=True, exist_ok=True)

    # Sorgente Rust
    rust_source_path(source_hash).write_text(rust_source, encoding="utf-8")

    # Binario
    bin_path = binary_path(source_hash)
    bin_path.write_bytes(binary_data)
    # Rendi eseguibile
    bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # Hash file (ridondante — il nome dir è già l'hash, ma utile per ispezione)
    hash_file_path(source_hash).write_text(source_hash, encoding="utf-8")


def store_rust_source(source_hash: str, rust_source: str) -> Path:
    """Salva solo il sorgente Rust (prima della compilazione).

    Returns:
        Path del file .rs salvato.
    """
    d = cache_dir(source_hash)
    d.mkdir(parents=True, exist_ok=True)
    path = rust_source_path(source_hash)
    path.write_text(rust_source, encoding="utf-8")
    return path


def store_binary(source_hash: str, binary_path_src: Path) -> None:
    """Copia un binario già compilato nella cache."""
    d = cache_dir(source_hash)
    d.mkdir(parents=True, exist_ok=True)
    dst = binary_path(source_hash)
    shutil.copy2(binary_path_src, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def get_rust_source(source_hash: str) -> str | None:
    """Leggi il sorgente Rust dalla cache (se presente)."""
    path = rust_source_path(source_hash)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def clear_all() -> int:
    """Svuota tutta la cache. Restituisce il numero di entry rimosse."""
    if not CACHE_ROOT.exists():
        return 0
    count = 0
    for entry in CACHE_ROOT.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
            count += 1
    return count


def list_entries() -> list[dict]:
    """Elenca tutte le entry in cache con i loro metadati."""
    if not CACHE_ROOT.exists():
        return []
    entries = []
    for entry in sorted(CACHE_ROOT.iterdir()):
        if not entry.is_dir():
            continue
        bin_p = entry / "binary"
        rs_p = entry / "rust_source.rs"
        entries.append({
            "hash": entry.name,
            "has_binary": bin_p.exists(),
            "binary_size": bin_p.stat().st_size if bin_p.exists() else 0,
            "has_rust_source": rs_p.exists(),
            "path": str(entry),
        })
    return entries
