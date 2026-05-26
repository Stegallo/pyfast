"""CLI di PyFast.

Comandi:
  pyfast run <script.py>              — esegui (Python + compila Rust in background)
  pyfast transpile <script.py>        — solo transpila, stampa il Rust
  pyfast transpile --show <script.py> — mostra Rust senza salvare in cache
  pyfast cache --list                 — elenca entry in cache
  pyfast cache --clear                — svuota la cache
"""

import argparse
import sys
from pathlib import Path

from pyfast import __version__


def _cmd_run(args: argparse.Namespace) -> int:
    """Esegui uno script con la strategia PyFast."""
    from pyfast.runner import execute
    return execute(args.script, args.script_args)


def _cmd_transpile(args: argparse.Namespace) -> int:
    """Transpila uno script Python in Rust e mostra / salva il risultato."""
    from pyfast.runner import transpile
    from pyfast import cache as cache_mod

    script_path = Path(args.script)
    if not script_path.exists():
        print(f"pyfast: file non trovato: {args.script}", file=sys.stderr)
        return 1

    source = script_path.read_text(encoding="utf-8")
    try:
        rust_code = transpile(source)
    except Exception as e:
        print(f"pyfast: errore di transpilazione: {e}", file=sys.stderr)
        return 1

    if args.output:
        out_path = Path(args.output)
        out_path.write_text(rust_code, encoding="utf-8")
        print(f"Rust salvato in: {out_path}")
    else:
        # Mostra a schermo
        print(rust_code)

    # Salva anche in cache (il sorgente Rust, non il binario)
    if not args.no_cache:
        source_hash = cache_mod.compute_hash(source)
        cache_mod.store_rust_source(source_hash, rust_code)

    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    """Benchmark: misura speedup Python vs Rust."""
    from pyfast.bench import run_benchmark

    try:
        run_benchmark(args.script, runs=args.runs, warmup=args.warmup)
    except FileNotFoundError as e:
        print(f"pyfast: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"pyfast: errore benchmark: {e}", file=sys.stderr)
        return 1
    return 0


def _cmd_cache(args: argparse.Namespace) -> int:
    """Gestione della cache."""
    from pyfast import cache as cache_mod

    if args.list:
        entries = cache_mod.list_entries()
        if not entries:
            print("Cache vuota.")
            return 0
        print(f"{'Hash':<34} {'Binario':<8} {'Dimensione':>12}")
        print("-" * 60)
        for e in entries:
            binary_info = "✓" if e["has_binary"] else "✗"
            size = f"{e['binary_size']:,} B" if e["has_binary"] else "-"
            print(f"{e['hash']}  {binary_info:<8} {size:>12}")
        print(f"\n{len(entries)} entry/entries in cache.")
        return 0

    if args.clear:
        n = cache_mod.clear_all()
        print(f"Cache svuotata ({n} entry rimosse).")
        return 0

    # Nessuna opzione — mostra help
    print("Usa `pyfast cache --list` o `pyfast cache --clear`.")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyfast",
        description="Python → Rust transpiler per speedup trasparente",
    )
    parser.add_argument("--version", action="version", version=f"pyfast {__version__}")

    subparsers = parser.add_subparsers(dest="command", metavar="<comando>")
    subparsers.required = True

    # ── run ─────────────────────────────────────────────────────────────────
    run_p = subparsers.add_parser("run", help="Esegui uno script Python con PyFast")
    run_p.add_argument("script", metavar="script.py", help="File Python da eseguire")
    run_p.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        metavar="...",
        help="Argomenti passati allo script",
    )
    run_p.set_defaults(func=_cmd_run)

    # ── transpile ────────────────────────────────────────────────────────────
    trans_p = subparsers.add_parser("transpile", help="Transpila Python → Rust (senza eseguire)")
    trans_p.add_argument("script", metavar="script.py", help="File Python da transpilare")
    trans_p.add_argument("-o", "--output", metavar="file.rs", help="Salva il Rust in un file")
    trans_p.add_argument(
        "--no-cache", action="store_true", help="Non salvare il risultato in cache"
    )
    trans_p.set_defaults(func=_cmd_transpile)

    # ── cache ────────────────────────────────────────────────────────────────
    cache_p = subparsers.add_parser("cache", help="Gestione della cache dei binari")
    cache_group = cache_p.add_mutually_exclusive_group(required=True)
    cache_group.add_argument("--list", action="store_true", help="Elenca entry in cache")
    cache_group.add_argument("--clear", action="store_true", help="Svuota la cache")
    cache_p.set_defaults(func=_cmd_cache)

    # ── bench ────────────────────────────────────────────────────────────────
    bench_p = subparsers.add_parser(
        "bench",
        help="Misura speedup Python vs Rust (richiede rustc)",
    )
    bench_p.add_argument("script", metavar="script.py", help="File Python da benchmarkare")
    bench_p.add_argument(
        "--runs", type=int, default=5, metavar="N",
        help="Numero di esecuzioni per misurare i tempi (default: 5)",
    )
    bench_p.add_argument(
        "--warmup", type=int, default=1, metavar="N",
        help="Esecuzioni di riscaldamento, non conteggiate (default: 1)",
    )
    bench_p.set_defaults(func=_cmd_bench)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))
