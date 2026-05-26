"""Benchmark: misura lo speedup Python → Rust.

Algoritmo:
  1. Esegui lo script Python N volte, misura i tempi
  2. Transpila in Rust (se non già in cache)
  3. Compila con rustc (sincrono — per avere il binario prima di misurare)
  4. Esegui il binario Rust N volte, misura i tempi
  5. Calcola e mostra speedup

Nota: la compilazione Rust NON è inclusa nel tempo di benchmark.
      Il modello PyFast prevede compilazione una-tantum, esecuzione N volte.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pyfast import cache as cache_mod
from pyfast.runner import transpile, compile_rust


# ---------------------------------------------------------------------------
# Strutture dati
# ---------------------------------------------------------------------------

@dataclass
class TimingResult:
    runs: list[float]           # secondi per ogni run
    label: str

    @property
    def mean(self) -> float:
        return sum(self.runs) / len(self.runs)

    @property
    def best(self) -> float:
        return min(self.runs)

    @property
    def worst(self) -> float:
        return max(self.runs)

    def mean_ms(self) -> float:
        return self.mean * 1000

    def best_ms(self) -> float:
        return self.best * 1000


@dataclass
class BenchmarkResult:
    python: TimingResult
    rust: TimingResult | None
    compile_time_s: float | None  # tempo compilazione (non conteggiato)
    script_path: str

    @property
    def speedup(self) -> float | None:
        if self.rust is None:
            return None
        return self.python.mean / self.rust.mean


# ---------------------------------------------------------------------------
# Esecuzione con timing
# ---------------------------------------------------------------------------

def _time_subprocess(cmd: list[str], runs: int) -> list[float]:
    """Esegui un comando `runs` volte e restituisci i tempi in secondi."""
    times = []
    for _ in range(runs):
        t0 = time.perf_counter()
        result = subprocess.run(cmd, capture_output=True)
        t1 = time.perf_counter()
        if result.returncode != 0:
            raise RuntimeError(
                f"Comando fallito (exit {result.returncode}):\n"
                + result.stderr.decode(errors="replace")
            )
        times.append(t1 - t0)
    return times


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_benchmark(
    script_path: str,
    runs: int = 5,
    warmup: int = 1,
    verbose: bool = True,
) -> BenchmarkResult:
    """Esegui il benchmark completo per uno script Python.

    Args:
        script_path: Percorso al file Python.
        runs: Numero di esecuzioni per misurare i tempi.
        warmup: Numero di esecuzioni di riscaldamento (non conteggiate).
        verbose: Se True, stampa progress in tempo reale.

    Returns:
        BenchmarkResult con i tempi Python e Rust.
    """
    path = Path(script_path)
    if not path.exists():
        raise FileNotFoundError(f"File non trovato: {script_path}")

    source = path.read_text(encoding="utf-8")
    source_hash = cache_mod.compute_hash(source)

    # ── Python ──────────────────────────────────────────────────────────────
    python_cmd = [sys.executable, str(path)]

    if verbose:
        _print_header(f"Python ({runs} runs, {warmup} warmup)")

    # Warmup
    if warmup > 0:
        if verbose:
            print(f"  Riscaldamento ({warmup} run)...", flush=True)
        _time_subprocess(python_cmd, warmup)

    # Misura
    python_times = []
    for i in range(runs):
        t = _time_subprocess(python_cmd, 1)[0]
        python_times.append(t)
        if verbose:
            print(f"  Run {i+1}/{runs}: {t*1000:.1f} ms")

    python_result = TimingResult(runs=python_times, label="Python")

    if verbose:
        print(f"  → Media: {python_result.mean_ms():.1f} ms  "
              f"(best: {python_result.best_ms():.1f} ms)")

    # ── Compilazione Rust ────────────────────────────────────────────────────
    compile_time = None
    rust_result = None

    # Controlla se rustc è disponibile
    if not _rustc_available():
        if verbose:
            _print_warning("rustc non trovato — installa Rust: https://rustup.rs")
        return BenchmarkResult(
            python=python_result,
            rust=None,
            compile_time_s=None,
            script_path=script_path,
        )

    # Transpila
    try:
        rust_source = transpile(source)
    except Exception as e:
        if verbose:
            _print_warning(f"Transpilazione fallita: {e}")
        return BenchmarkResult(
            python=python_result,
            rust=None,
            compile_time_s=None,
            script_path=script_path,
        )

    # Compila (o usa cache)
    if cache_mod.is_cached(source_hash):
        if verbose:
            _print_header("Rust (cache HIT — binario già compilato)")
    else:
        if verbose:
            _print_header("Compilazione Rust")
            print("  Compilo in corso...", end=" ", flush=True)

        t0 = time.perf_counter()
        ok = compile_rust(rust_source, source_hash)
        compile_time = time.perf_counter() - t0

        if not ok:
            if verbose:
                print("FALLITA")
                rs_path = cache_mod.rust_source_path(source_hash)
                _print_warning(f"Errore di compilazione. Sorgente Rust: {rs_path}")
            return BenchmarkResult(
                python=python_result,
                rust=None,
                compile_time_s=compile_time,
                script_path=script_path,
            )

        if verbose:
            print(f"OK ({compile_time:.1f}s)")
            print(f"  Sorgente Rust: {cache_mod.rust_source_path(source_hash)}")

    # ── Rust ────────────────────────────────────────────────────────────────
    bin_path = str(cache_mod.binary_path(source_hash))
    rust_cmd = [bin_path]

    if verbose:
        _print_header(f"Rust ({runs} runs, {warmup} warmup)")

    # Warmup
    if warmup > 0:
        if verbose:
            print(f"  Riscaldamento ({warmup} run)...", flush=True)
        _time_subprocess(rust_cmd, warmup)

    # Misura
    rust_times = []
    for i in range(runs):
        t = _time_subprocess(rust_cmd, 1)[0]
        rust_times.append(t)
        if verbose:
            print(f"  Run {i+1}/{runs}: {t*1000:.1f} ms")

    rust_result = TimingResult(runs=rust_times, label="Rust")

    if verbose:
        print(f"  → Media: {rust_result.mean_ms():.1f} ms  "
              f"(best: {rust_result.best_ms():.1f} ms)")

    result = BenchmarkResult(
        python=python_result,
        rust=rust_result,
        compile_time_s=compile_time,
        script_path=script_path,
    )

    # ── Riepilogo ───────────────────────────────────────────────────────────
    if verbose:
        _print_summary(result)

    return result


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _print_header(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


def _print_warning(msg: str) -> None:
    print(f"\n  ⚠️  {msg}")


def _print_summary(result: BenchmarkResult) -> None:
    print(f"\n{'═' * 50}")
    print("  RIEPILOGO BENCHMARK")
    print(f"{'═' * 50}")
    print(f"  Script:  {result.script_path}")
    print(f"  Python:  {result.python.mean_ms():.1f} ms (media)")
    if result.compile_time_s is not None:
        print(f"  Compil:  {result.compile_time_s:.1f} s (una-tantum, non conteggiata)")
    if result.rust is not None:
        print(f"  Rust:    {result.rust.mean_ms():.1f} ms (media)")
        speedup = result.speedup
        emoji = "🚀" if speedup >= 5 else "⚡" if speedup >= 2 else "≈"
        print(f"  Speedup: {speedup:.1f}x  {emoji}")
        # Break-even: dopo quante esecuzioni Rust ripaga la compilazione?
        if result.compile_time_s and speedup > 1:
            saved_per_run = result.python.mean - result.rust.mean
            if saved_per_run > 0:
                breakeven = result.compile_time_s / saved_per_run
                print(f"  Break-even: ~{breakeven:.0f} esecuzioni")
    else:
        print("  Rust:    N/D (rustc non disponibile o transpilazione fallita)")
    print(f"{'═' * 50}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rustc_available() -> bool:
    from pyfast.runner import rustc_available
    return rustc_available()
