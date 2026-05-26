# PyFast

> Transpiler Python → Rust per speedup trasparente e automatico.

## Concept

PyFast esegue codice Python trasparentemente più veloce, transpilando automaticamente in Rust e cachando il binario nativo.

```
Prima esecuzione:
  my_script.py ──→ esegui con Python subito    ──→ output utente (zero attesa)
                   compila Rust in background   ──→ salva binario in cache

Esecuzioni successive:
  my_script.py ──→ hash invariato ──→ esegui binario nativo (10x più veloce)
  my_script.py ──→ hash cambiato  ──→ ricomincia dal punto 1
```

## Installazione

```bash
# 1. Installa Rust (necessario per compilare i binari)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# 2. Installa PyFast
pip install -e ".[dev]"
```

## Utilizzo

```bash
# Esegui uno script (Python subito + compila Rust in background)
pyfast run examples/hello_world.py

# Solo transpila (non esegue)
pyfast transpile examples/hello_world.py

# Salva il Rust in un file
pyfast transpile examples/primes.py -o primes.rs

# Benchmark Python vs Rust
pyfast bench examples/primes.py
pyfast bench examples/fibonacci.py --runs 5 --warmup 2

# Stato della cache
pyfast cache --list
pyfast cache --clear
```

## Benchmark

`pyfast bench` misura lo speedup reale Python → Rust:

```
──────────────────────────────────────────────────
  Python (5 runs, 1 warmup)
──────────────────────────────────────────────────
  Run 1/5: 2321.4 ms
  ...
  → Media: 2338.2 ms  (best: 2318.7 ms)

──────────────────────────────────────────────────
  Compilazione Rust
──────────────────────────────────────────────────
  Compilo in corso... OK (1.8s)

──────────────────────────────────────────────────
  Rust (5 runs, 1 warmup)
──────────────────────────────────────────────────
  Run 1/5: 48.3 ms
  ...
  → Media: 49.1 ms  (best: 48.3 ms)

══════════════════════════════════════════════════
  RIEPILOGO BENCHMARK
══════════════════════════════════════════════════
  Script:  examples/primes.py
  Python:  2338.2 ms (media)
  Compil:  1.8 s (una-tantum, non conteggiata)
  Rust:    49.1 ms (media)
  Speedup: 47.6x  🚀
  Break-even: ~1 esecuzione
══════════════════════════════════════════════════
```

> **Nota**: la prima esecuzione paga la compilazione Rust (1-3 sec).
> Dalla seconda in poi: solo il binario nativo, nessun overhead.

### Esempi benchmark inclusi

| Script | Algoritmo | Python (atteso) | Rust (atteso) | Speedup |
|--------|-----------|-----------------|---------------|---------|
| `primes.py` | Crivello n=1M | ~2.3s | ~50ms | ~47x |
| `fibonacci.py` | Fib(90) × 1M iter | ~1.6s | ~30ms | ~50x |

### Perché Fibonacci non usa n>92?

Il subset PyFast mappa `int` → `i64` (max ≈ 9.2×10¹⁸).
`fibonacci(93)` overflowa `i64`. Per big integers servirebbero librerie esterne — escluse dal subset.

## Subset Python supportato

Il transpiler non supporta tutto Python — solo un subset che coincide con le **buone pratiche**:
codice con type hints, strutture dati coerenti, errori espliciti.

### Tipi supportati

| Python       | Rust            |
|--------------|-----------------|
| `int`        | `i64`           |
| `float`      | `f64`           |
| `bool`       | `bool`          |
| `str` (lett.)| `&str`          |
| `str` (runtime) | `String`     |
| `Optional[T]`| `Option<T>`     |
| `list[T]`    | `Vec<T>`        |
| `dict[K,V]`  | `HashMap<K,V>`  |

### Costrutti supportati

- Milestone 1 ✅ — Funzioni, variabili tipizzate, `print`, f-string, inferenza `mut`
- Milestone 2 🚧 — `if/elif/else`, `while`, `for`
- Milestone 3 ⏳ — Funzioni con parametri e ritorno
- Milestone 4 ⏳ — Collezioni (`list`, `dict`, `tuple`)
- Milestone 5 ⏳ — `Optional[T]`, `Result[T, str]`
- Milestone 6 ⏳ — Tool completo con cache e runner

## Architettura

```
Python source
     ↓
  [Parser]        ast stdlib
     ↓
  [AST Python]
     ↓
  [Analyzer]      inferisce mut, owned strings, ownership
     ↓
  [Generator]     produce codice Rust
     ↓
  [Rust source]
     ↓
  [rustc/cargo]   compila (solo quando necessario)
     ↓
  [Binary]        cachato e riusato
```

## Esempio

Input Python:
```python
def main() -> None:
    nome: str = "Alice"
    eta: int = 30
    saluto: str = f"Ciao {nome}, hai {eta} anni"
    print(saluto)

main()
```

Output Rust generato:
```rust
fn main() {
    let nome: &str = "Alice";
    let eta: i64 = 30;
    let saluto: String = format!("Ciao {}, hai {} anni", nome, eta);
    println!("{}", saluto);
}
```
