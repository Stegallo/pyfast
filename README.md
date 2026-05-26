# PyFast

> Esegui i tuoi script Python **fino a 50 volte più veloce** — senza cambiare una riga di codice.\*
>
> \* Il codice deve usare un piccolo sottoinsieme di Python. Questa guida spiega esattamente come.

## Come funziona

PyFast agisce come un lanciatore intelligente al posto di `python`:

```
Prima esecuzione:
  pyfast run script.py  →  esegue con Python subito     →  output immediato
                            compila Rust in background   →  salva binario in cache

Dalla seconda esecuzione in poi:
  pyfast run script.py  →  carica il binario compilato  →  10–50x più veloce
  pyfast run script.py  →  (script modificato)          →  ricomincia dal punto 1
```

Non devi installare nulla di diverso, non devi imparare Rust, non devi toccare il tuo codice Python.
PyFast lo transpila automaticamente e gestisce la cache da solo.

---

## Installazione

```bash
# 1. Installa Rust (necessario per compilare i binari nativi)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# 2. Installa PyFast
pip install -e ".[dev]"
```

---

## Utilizzo rapido

```bash
# Esegui uno script (Python subito + Rust compilato in background)
pyfast run mio_script.py

# Solo transpila (utile per vedere il Rust generato o fare debug)
pyfast transpile mio_script.py
pyfast transpile mio_script.py -o output.rs

# Confronto prestazioni Python vs Rust
pyfast bench mio_script.py
pyfast bench mio_script.py --runs 10 --warmup 2

# Gestione cache
pyfast cache --list    # mostra i binari in cache
pyfast cache --clear   # svuota la cache
```

---

## Come scrivere codice compatibile con PyFast

PyFast non supporta tutto Python — supporta un **sottoinsieme ben definito**.
La regola d'oro è una sola: **ogni variabile e ogni parametro di funzione deve avere un type hint**.

### Regola 1 — Type hint obbligatori

```python
# ✅ Corretto: tutti i parametri e il valore di ritorno hanno type hint
def somma(a: int, b: int) -> int:
    return a + b

# ❌ Errore: manca il type hint su `a`
def somma(a, b: int) -> int:
    return a + b
```

```python
# ✅ Corretto: variabili locali con type hint
def main() -> None:
    contatore: int = 0
    nome: str = "Alice"

# ❌ Errore: variabile locale senza type hint
def main() -> None:
    contatore = 0   # PyFast segnala l'errore con la riga esatta
```

Se dimentichi un type hint, PyFast ti mostra subito dove:

```
⚠️  [pyfast] La compilazione Rust è fallita per questo script.
   riga 3: variabile 'contatore' usata senza type hint — aggiungi `contatore: <tipo> = ...`
   Esecuzione con Python (nessuno speedup).
```

### Regola 2 — Tipi supportati

| Tipo Python          | Esempio                                    | Note                                          |
|----------------------|--------------------------------------------|-----------------------------------------------|
| `int`                | `x: int = 42`                              | Intero a 64 bit (max ~9.2×10¹⁸)              |
| `float`              | `pi: float = 3.14`                         | Virgola mobile a 64 bit                       |
| `bool`               | `attivo: bool = True`                      | `True`/`False`                                |
| `str`                | `nome: str = "Alice"`                      | Stringa                                       |
| `list[T]`            | `numeri: list[int] = [1, 2, 3]`           | Lista omogenea (tutti gli elementi stesso tipo)|
| `dict[K, V]`         | `d: dict[str, int] = {}`                  | Dizionario chiave→valore                      |
| `int \| None`        | `x: int \| None = None`                   | Valore che può essere `None` (Python 3.10+)   |
| `Optional[T]`        | `x: Optional[int] = None`                 | Equivalente al precedente (stile pre-3.10)    |

```python
from typing import Optional

def cerca(lista: list[int], valore: int) -> Optional[int]:
    i: int = 0
    while i < len(lista):
        if lista[i] == valore:
            return i
        i = i + 1
    return None
```

### Regola 3 — Costrutti supportati

**Funzioni**

```python
# Con parametri e valore di ritorno
def moltiplica(a: int, b: int) -> int:
    return a * b

# Senza valore di ritorno
def stampa_saluto(nome: str) -> None:
    print(f"Ciao {nome}!")
```

**Variabili e assegnazioni**

```python
def esempio() -> None:
    x: int = 10          # dichiarazione con type hint
    x = 20               # riassegnazione ok (PyFast inferisce `mut` da solo)
    x += 5               # operatori augmented assignment: +=, -=, *=, /=
```

**Condizionali**

```python
def classifica(punteggio: int) -> None:
    if punteggio >= 90:
        print("ottimo")
    elif punteggio >= 60:
        print("sufficiente")
    else:
        print("insufficiente")
```

**Cicli**

```python
def conta() -> None:
    i: int = 0
    while i < 10:
        i = i + 1

def somma_lista() -> None:
    numeri: list[int] = [1, 2, 3, 4, 5]
    totale: int = 0
    for n in numeri:
        totale = totale + n
    print(totale)

def range_loop() -> None:
    for i in range(5):   # range(n) → for i in 0..n in Rust
        print(i)
```

**Print e f-string**

```python
nome: str = "Alice"
eta: int = 30

print("Testo semplice")               # → println!("Testo semplice")
print(nome)                            # → println!("{}", nome)
print(f"Ciao {nome}, hai {eta} anni") # → println!("Ciao {}, hai {} anni", nome, eta)
```

### Cosa non è supportato (ancora)

| Costrutto                | Alternativa                                                |
|--------------------------|------------------------------------------------------------|
| `class` con ereditarietà | usa funzioni e dizionari                                   |
| `try` / `except`         | usa `Optional[T]` e controlla `None`                      |
| `raise`                  | restituisce `None` o un codice di errore                   |
| Liste eterogenee         | usa `list[int]`, `list[str]` — non `list[Any]`             |
| `*args` / `**kwargs`     | usa parametri espliciti con type hint                      |
| `lambda`                 | usa una funzione normale                                    |
| `import` (escluso `Optional`) | tieni le funzioni semplici e autonome                 |
| Ricorsione mutua         | supportata solo se le funzioni sono nel file               |

---

## Esempio completo

**`examples/fibonacci.py`** — calcola Fibonacci 1 milione di volte:

```python
def fibonacci(n: int) -> int:
    if n <= 1:
        return n

    a: int = 0
    b: int = 1
    i: int = 2

    while i <= n:
        c: int = a + b
        a = b
        b = c
        i = i + 1

    return b


def main() -> None:
    runs: int = 1000000
    n: int = 90
    i: int = 0
    result: int = 0

    while i < runs:
        result = fibonacci(n)
        i = i + 1

    print(result)


main()
```

Transpilato da PyFast:

```rust
fn fibonacci(n: i64) -> i64 {
    if (n <= 1) {
        return n;
    }
    let mut a: i64 = 0;
    let mut b: i64 = 1;
    let mut i: i64 = 2;
    while (i <= n) {
        let c: i64 = (a + b);
        a = b;
        b = c;
        i = (i + 1);
    }
    return b;
}

fn main() {
    let runs: i64 = 1000000;
    let n: i64 = 90;
    let mut i: i64 = 0;
    let mut result: i64 = 0;
    while (i < runs) {
        result = fibonacci(n);
        i = (i + 1);
    }
    println!("{}", result);
}
```

Nota: PyFast inferisce automaticamente `let mut` dove la variabile viene riassegnata.
Non devi dichiarare nulla di speciale nel codice Python.

### Risultato benchmark

```
══════════════════════════════════════════════════
  RIEPILOGO BENCHMARK
══════════════════════════════════════════════════
  Script:  examples/fibonacci.py
  Python:  1612.3 ms (media)
  Compil:  1.4 s (una-tantum, non conteggiata)
  Rust:    31.8 ms (media)
  Speedup: 50.7x  🚀
  Break-even: ~1 esecuzione
══════════════════════════════════════════════════
```

---

## Messaggi di errore comuni

| Messaggio                                                        | Causa                                | Soluzione                               |
|------------------------------------------------------------------|--------------------------------------|-----------------------------------------|
| `variabile 'x' usata senza type hint`                            | Variabile locale senza annotazione   | `x: int = 0` invece di `x = 0`         |
| `parametro 'x' senza type hint`                                  | Parametro funzione senza annotazione | `def f(x: int)` invece di `def f(x)`   |
| `tipo 'list' non supportato senza parametro`                     | `list` senza tipo elemento           | `list[int]` invece di `list`            |
| `rustc non trovato`                                              | Rust non installato                  | `curl ... rustup.rs \| sh`              |
| `Il codice Rust generato non compila`                            | Bug del transpiler                   | Usa `PYFAST_DEBUG=1 pyfast run script.py` per dettagli |

Per debug avanzato:

```bash
# Vedi il codice Rust generato
pyfast transpile mio_script.py

# Vedi errori di compilazione rustc
PYFAST_DEBUG=1 pyfast run mio_script.py

# Forza ricompilazione (svuota cache)
pyfast cache --clear && pyfast run mio_script.py
```

---

## Architettura interna (per i curiosi)

```
script.py
    │
    ▼
[ast.parse]          analizza il sorgente Python
    │
    ▼
[Analyzer]           inferisce: mutabilità, ownership stringhe, borrow nei loop
    │
    ▼
[RustGenerator]      produce codice Rust equivalente
    │
    ▼
[rustc]              compila in background (prima run) o dalla cache (run successive)
    │
    ▼
[binario nativo]     cachato in ~/.pyfast/cache/<hash>/
```

La cache usa l'MD5 del sorgente Python: se il file cambia, viene ricompilato automaticamente.
