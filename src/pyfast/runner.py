"""Runner: logica di esecuzione ibrida Python + Rust.

Flusso (dal design doc):

  Prima esecuzione:
    script.py → esegui con Python subito (zero attesa utente)
               → compila Rust in background
               → salva binario in cache

  Esecuzioni successive:
    script.py → hash invariato → esegui binario nativo (10x più veloce)
    script.py → hash cambiato  → ricomincia dal punto 1

Questa strategia è equivalente al JIT lazy di Java HotSpot / V8:
interpreta subito, ottimizza in background, sostituisce silenziosamente.
"""

import ast
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from pyfast import cache as cache_mod
from pyfast.transpiler.analyzer import analyze
from pyfast.transpiler.generator import RustGenerator, TranspileError

# Secondi di attesa per la compilazione Rust dopo che Python ha finito.
# Sovrascrivibile via variabile d'ambiente PYFAST_COMPILE_TIMEOUT.
COMPILE_TIMEOUT: int = int(os.environ.get("PYFAST_COMPILE_TIMEOUT", "10"))


# ---------------------------------------------------------------------------
# Transpilazione (Python AST → Rust source)
# ---------------------------------------------------------------------------

def transpile(source: str) -> str:
    """Transpila il sorgente Python in codice Rust.

    Args:
        source: Contenuto del file Python.

    Returns:
        Codice Rust come stringa.

    Raises:
        TranspileError: Se il codice Python non è nel subset supportato.
    """
    tree = ast.parse(source)
    analysis = analyze(tree)
    generator = RustGenerator(analysis)
    return generator.generate(tree)


# ---------------------------------------------------------------------------
# Compilazione Rust
# ---------------------------------------------------------------------------

def compile_rust(rust_source: str, source_hash: str) -> bool:
    """Compila il codice Rust e salva il binario in cache.

    Args:
        rust_source: Codice Rust da compilare.
        source_hash: Hash del sorgente Python originale (usato per la cache).

    Returns:
        True se la compilazione ha avuto successo.
    """
    # Salva sorgente Rust in cache (utile per debug anche in caso di errore)
    rs_path = cache_mod.store_rust_source(source_hash, rust_source)

    # Output binario in una directory temporanea, poi copiamo in cache
    with tempfile.TemporaryDirectory() as tmpdir:
        bin_out = Path(tmpdir) / "binary"
        try:
            result = subprocess.run(
                ["rustc", str(rs_path), "-o", str(bin_out)],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            cache_mod.store_compile_error(
                source_hash,
                cache_mod.ERROR_RUSTC_NOT_FOUND,
                "rustc non trovato — installa Rust: https://rustup.rs",
            )
            return False

        if result.returncode != 0:
            cache_mod.store_compile_error(
                source_hash,
                cache_mod.ERROR_RUSTC,
                result.stderr,
            )
            if os.environ.get("PYFAST_DEBUG"):
                print(f"[pyfast] Errore compilazione Rust ({rs_path}):", file=sys.stderr)
                print(result.stderr, file=sys.stderr)
            return False

        # Successo: rimuovi eventuale errore precedente e salva il binario
        cache_mod.clear_compile_error(source_hash)
        cache_mod.store_binary(source_hash, bin_out)
        return True


# ---------------------------------------------------------------------------
# Esecuzione
# ---------------------------------------------------------------------------

def run_python(script_path: str, argv: list[str] | None = None) -> int:
    """Esegui lo script con l'interprete Python corrente.

    Returns:
        Exit code del processo Python.
    """
    args = [sys.executable, script_path] + (argv or [])
    result = subprocess.run(args)
    return result.returncode


def run_binary(source_hash: str, argv: list[str] | None = None) -> None:
    """Esegui il binario Rust dalla cache (sostituisce il processo corrente).

    Usa os.execv per evitare overhead: il processo Python diventa il binario Rust.
    Questo significa che questa funzione non ritorna mai.
    """
    bin_path = cache_mod.binary_path(source_hash)
    # os.execv rimpiazza il processo corrente — overhead zero
    os.execv(str(bin_path), [str(bin_path)] + (argv or []))


# ---------------------------------------------------------------------------
# Controllo disponibilità rustc
# ---------------------------------------------------------------------------

def rustc_available() -> bool:
    """True se rustc è disponibile nel PATH."""
    try:
        result = subprocess.run(
            ["rustc", "--version"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Entry point principale
# ---------------------------------------------------------------------------

def execute(script_path: str, argv: list[str] | None = None) -> int:
    """Esegui uno script Python con la strategia PyFast.

    Flusso:
      1. Cache HIT  → esegui binario Rust (os.execv, no return)
      2. Cache MISS →
           a. Avvisa se c'è un errore dalla run precedente
           b. Transpila subito (sync, < 100ms) → intercetta errori di subset
           c. Verifica rustc disponibile → intercetta tool mancante
           d. Avvia rustc in background
           e. Esegui Python immediatamente
           f. join(timeout) → avvisa se errore rustc o timeout
    """
    source_path = Path(script_path)
    if not source_path.exists():
        print(f"pyfast: file non trovato: {script_path}", file=sys.stderr)
        return 1

    source = source_path.read_text(encoding="utf-8")
    source_hash = cache_mod.compute_hash(source)

    # ── Cache HIT ──────────────────────────────────────────────────────────
    if cache_mod.is_cached(source_hash):
        run_binary(source_hash, argv)
        return 1  # execv ha fallito

    # ── Errore dalla run precedente ────────────────────────────────────────
    _warn_if_compile_error(source_hash, script_path)
    if cache_mod.get_compile_error(source_hash):
        # Errore già noto: esegui Python e basta, non ritentare
        return run_python(script_path, argv)

    # ── Transpilazione (sincrona, < 100ms) ────────────────────────────────
    # Eseguita prima di run_python() per intercettare errori di subset subito,
    # prima che l'output dello script li "nasconda" visivamente.
    rust_source = _transpile_or_warn(source, source_hash, script_path)
    if rust_source is None:
        # Transpilazione fallita: errore già salvato e mostrato
        return run_python(script_path, argv)

    # ── Verifica rustc ─────────────────────────────────────────────────────
    if not rustc_available():
        msg = "rustc non trovato — installa Rust: https://rustup.rs"
        cache_mod.store_compile_error(source_hash, cache_mod.ERROR_RUSTC_NOT_FOUND, msg)
        _warn_if_compile_error(source_hash, script_path)
        return run_python(script_path, argv)

    # ── Avvia rustc in background ──────────────────────────────────────────
    compile_thread = _start_background_rustc(rust_source, source_hash)

    # ── Esegui Python immediatamente ───────────────────────────────────────
    exit_code = run_python(script_path, argv)

    # ── Attendi rustc fino al timeout ──────────────────────────────────────
    compile_thread.join(timeout=COMPILE_TIMEOUT)
    if compile_thread.is_alive():
        _warn_compile_timeout(COMPILE_TIMEOUT)
    else:
        _warn_if_compile_error(source_hash, script_path)

    return exit_code


def _warn_if_compile_error(source_hash: str, script_path: str) -> None:
    """Stampa un warning su stderr se la compilazione precedente è fallita."""
    error = cache_mod.get_compile_error(source_hash)
    if error is None:
        return

    kind, message = error
    rs_path = cache_mod.rust_source_path(source_hash)

    print(file=sys.stderr)
    print("⚠️  [pyfast] La compilazione Rust è fallita per questo script.", file=sys.stderr)

    if kind == cache_mod.ERROR_RUSTC_NOT_FOUND:
        print(f"   {message}", file=sys.stderr)

    elif kind == cache_mod.ERROR_TRANSPILE:
        print("   Il codice Python contiene costrutti fuori dal subset supportato.", file=sys.stderr)
        print(f"   Dettaglio: {message}", file=sys.stderr)

    elif kind == cache_mod.ERROR_RUSTC:
        print("   Il codice Rust generato non compila.", file=sys.stderr)
        print(f"   Sorgente Rust: {rs_path}", file=sys.stderr)
        print(f"   Per il dettaglio completo: PYFAST_DEBUG=1 pyfast run {script_path}", file=sys.stderr)

    print("   Esecuzione con Python (nessuno speedup).", file=sys.stderr)
    print(file=sys.stderr)


def _warn_compile_timeout(timeout: int) -> None:
    """Warning quando il timeout di compilazione scade e il thread è ancora vivo."""
    print(file=sys.stderr)
    print(f"⚠️  [pyfast] La compilazione Rust non ha finito entro {timeout}s.", file=sys.stderr)
    print("   Il thread è stato interrotto: l'esito non verrà salvato.", file=sys.stderr)
    print(f"   Se hai una macchina lenta, aumenta il timeout:", file=sys.stderr)
    print(f"   PYFAST_COMPILE_TIMEOUT=60 pyfast run <script>", file=sys.stderr)
    print(file=sys.stderr)


def _transpile_or_warn(
    source: str, source_hash: str, script_path: str
) -> str | None:
    """Transpila il sorgente Python in Rust (sincrono).

    Se la transpilazione fallisce, salva l'errore in cache e mostra il warning.

    Returns:
        Il sorgente Rust come stringa, oppure None se la transpilazione è fallita.
    """
    try:
        return transpile(source)
    except (TranspileError, SyntaxError) as e:
        cache_mod.store_compile_error(source_hash, cache_mod.ERROR_TRANSPILE, str(e))
    except Exception as e:
        cache_mod.store_compile_error(
            source_hash, cache_mod.ERROR_TRANSPILE, f"Errore inaspettato: {e}"
        )
    _warn_if_compile_error(source_hash, script_path)
    return None


def _start_background_rustc(rust_source: str, source_hash: str) -> threading.Thread:
    """Avvia la compilazione rustc in background (la transpilazione è già avvenuta)."""
    thread = threading.Thread(
        target=compile_rust,
        args=(rust_source, source_hash),
        daemon=True,
    )
    thread.start()
    return thread
