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
pip install -e ".[dev]"
```

## Utilizzo

```bash
# Esegui uno script (Python subito + compila Rust in background)
pyfast run examples/hello_world.py

# Solo transpila (non esegue)
pyfast transpile examples/hello_world.py

# Mostra il codice Rust generato
pyfast transpile --show examples/hello_world.py

# Stato della cache
pyfast cache --list
pyfast cache --clear
```

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
