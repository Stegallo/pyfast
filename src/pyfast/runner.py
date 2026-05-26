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
# Entry point principale
# ---------------------------------------------------------------------------

def execute(script_path: str, argv: list[str] | None = None) -> int:
    """Esegui uno script Python con la strategia PyFast.

    Algoritmo:
      1. Leggi sorgente e calcola hash
      2. Cache HIT → esegui binario Rust (os.execv, no return)
      3. Cache MISS → esegui Python subito + transpila+compila in background

    Args:
        script_path: Percorso al file Python da eseguire.
        argv: Argomenti da passare allo script (esclude script_path stesso).

    Returns:
        Exit code (solo nel caso Python — il caso Rust usa execv).
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
        # se arriviamo qui, execv ha fallito
        return 1

    # ── Errore compilazione precedente ─────────────────────────────────────
    # Se per questo hash esiste un errore registrato dalla run precedente,
    # avvisiamo l'utente PRIMA di eseguire (su stderr, non misto all'output).
    _warn_if_compile_error(source_hash, script_path)

    # ── Cache MISS ─────────────────────────────────────────────────────────
    # 1. Avvia compilazione in background (solo se non avevamo già un errore)
    compile_thread = None
    if not cache_mod.get_compile_error(source_hash):
        compile_thread = _start_background_compile(source, source_hash)

    # 2. Esegui con Python immediatamente (zero attesa per l'utente)
    exit_code = run_python(script_path, argv)

    # 3. Attendi che il thread di compilazione finisca.
    #
    #    Perché non daemon=True?
    #    Con daemon=True il thread viene ucciso quando il processo esce
    #    (subito dopo run_python). Se Python < rustc, compile.error non
    #    viene mai scritto e il warning non compare mai.
    #
    #    Con daemon=False il processo aspetta il thread dopo che l'output
    #    Python è già apparso — l'utente vede il risultato subito,
    #    il prompt torna quando la compilazione finisce (o scade il timeout).
    if compile_thread is not None:
        compile_thread.join(timeout=120)  # max 2 min; rustc piccoli: ~2-5s

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


def _start_background_compile(source: str, source_hash: str) -> threading.Thread:
    """Avvia la transpilazione e compilazione Rust in background."""
    def _compile():
        try:
            rust_source = transpile(source)
        except (TranspileError, SyntaxError) as e:
            cache_mod.store_compile_error(
                source_hash,
                cache_mod.ERROR_TRANSPILE,
                str(e),
            )
            if os.environ.get("PYFAST_DEBUG"):
                print(f"[pyfast] Transpilazione fallita: {e}", file=sys.stderr)
            return
        except Exception as e:
            cache_mod.store_compile_error(
                source_hash,
                cache_mod.ERROR_TRANSPILE,
                f"Errore inaspettato: {e}",
            )
            if os.environ.get("PYFAST_DEBUG"):
                print(f"[pyfast] Errore inaspettato nella transpilazione: {e}", file=sys.stderr)
            return

        compile_rust(rust_source, source_hash)

    thread = threading.Thread(target=_compile, daemon=False)
    thread.start()
    return thread
