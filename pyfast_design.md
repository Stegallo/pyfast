# PyFast — Transpiler Python → Rust: Design e Motivazioni

> Documento di progetto basato su analisi conversazionale.  
> Obiettivo: costruire un tool che esegue codice Python trasparentemente più veloce,
> transpilando automaticamente in Rust e cachando il binario nativo.

---

## 1. Motivazione

### Il problema
Python è lento per codice CPU-bound. Rust è veloce ma ha una curva di apprendimento ripida e tempi di sviluppo 2-3x superiori.

### L'intuizione chiave
Un programmatore che scrive Python "pulito" — con type hints, strutture dati omogenee, errori espliciti — sta già scrivendo codice strutturalmente traducibile in Rust. Il transpiler automatizza questa traduzione in modo trasparente.

### I vantaggi combinati
- **Sviluppo** veloce come Python (nessuna compilazione, sintassi familiare)
- **Produzione** veloce come Rust (binario nativo, nessun GC, nessun interprete)
- **Apprendimento** — il progetto stesso insegna compilatori, Rust e differenze tra linguaggi

---

## 2. Architettura del Tool

### Nome provvisorio: `pyfast`

### Flusso di esecuzione

```
Prima esecuzione:
  my_script.py ──→ esegui con Python subito    ──→ output utente (zero attesa)
                   compila Rust in background   ──→ salva binario in cache

Esecuzioni successive:
  my_script.py ──→ hash invariato ──→ esegui binario nativo (10x più veloce)
  my_script.py ──→ hash cambiato  ──→ ricomincia dal punto 1
```

### Componenti

```
Python source
     ↓
  [Parser]        usa modulo `ast` di Python — disponibile in stdlib, gratis
     ↓
  [AST Python]
     ↓
  [Analyzer]      inferisce mut, ownership, tipi
     ↓
  [Generator]     produce codice Rust
     ↓
  [Rust source]
     ↓
  [rustc/cargo]   compila (solo quando necessario)
     ↓
  [Binary]        cachato e riusato nelle esecuzioni successive
```

### Logica di cache

```python
import hashlib
import os
import subprocess
import threading

def esegui(script_path):
    source = open(script_path).read()
    hash_attuale = hashlib.md5(source.encode()).hexdigest()
    binario = cache_path(script_path)

    if binario_valido(binario, hash_attuale):
        # esecuzioni successive: binario nativo
        os.execv(binario, sys.argv)
    else:
        # prima esecuzione: Python subito + compila in background
        thread = threading.Thread(
            target=transpila_e_compila,
            args=(script_path, hash_attuale)
        )
        thread.daemon = True
        thread.start()

        # esegui immediatamente con Python
        subprocess.run(["python3", script_path])
```

### Parallelo con tecnologie esistenti
Questa strategia è equivalente al **JIT lazy** usato da Java HotSpot e V8 di JavaScript:
interpreta subito, ottimizza in background, sostituisce silenziosamente con codice ottimizzato.
PyFast fa la stessa cosa usando due linguaggi separati invece di un JIT interno.

---

## 3. Il Subset del Linguaggio Python

Il transpiler non supporta tutto Python — solo un subset ben definito.
La caratteristica principale del subset è che coincide con le **buone pratiche di programmazione**:
codice con type hints, strutture dati coerenti, errori espliciti.

### 3.1 Mappatura tipi base

| Python | Rust | Note |
|--------|------|------|
| `int` | `i64` | Scelta fissa — interi oltre i64 vietati nel subset |
| `float` | `f64` | Scelta fissa |
| `bool` | `bool` | 1:1 |
| `str` (letterale) | `&str` | Stringhe immutabili, note a compile-time |
| `str` (costruita) | `String` | Concatenazione, f-string, valori runtime |
| `Optional[T]` | `Option<T>` | Obbligatorio esplicito, `None` implicito vietato |
| `list[T]` | `Vec<T>` | Solo liste omogenee |
| `dict[K, V]` | `HashMap<K, V>` | Quasi 1:1 |
| `tuple[A, B]` | `(A, B)` | 1:1 |

### 3.2 Costrutti di controllo

| Python | Rust | Note |
|--------|------|------|
| `if/elif/else` | `if/else if/else` | 1:1 |
| `while` | `while` | 1:1 |
| `for i in range(n)` | `for i in 0..n` | 1:1 |
| `for x in lista` | `for x in &lista` | `&` aggiunto automaticamente se lista usata dopo |

### 3.3 Funzioni

```python
# Python con type hints
def somma(a: int, b: int) -> int:
    return a + b
```

```rust
// Rust generato
fn somma(a: i64, b: i64) -> i64 {
    a + b
}
```

Traducibile deterministicamente con type hints obbligatorie.

### 3.4 Stringhe

Le stringhe Python sono immutabili — questo semplifica la mappatura:

| Caso | Rust |
|------|------|
| Stringa letterale `"hello"` | `&str` |
| Stringa costruita a runtime (concatenazione, f-string) | `String` |

```python
nome: str = "Alice"              # → &str (letterale)
saluto: str = f"Ciao {nome}"    # → String (costruita a runtime)
```

La distinzione è **inferibile automaticamente** dal transpiler.

### 3.5 Gestione errori

Python usa eccezioni (`raise/try/except`) — **vietate nel subset**.
Rust usa tipi di ritorno espliciti.

```python
# Python subset — no raise, errori come valori di ritorno
def dividi(a: int, b: int) -> Optional[float]:
    if b == 0:
        return None
    return a / b
```

```rust
// Rust generato
fn dividi(a: i64, b: i64) -> Option<f64> {
    if b == 0 { return None; }
    Some(a as f64 / b as f64)
}
```

Per errori con messaggio, aggiungere `Result[T, str]` al subset:

```rust
fn dividi(a: i64, b: i64) -> Result<f64, &str> {
    if b == 0 { return Err("divisione per zero"); }
    Ok(a as f64 / b as f64)
}
```

Chi chiama la funzione deve gestire entrambi i casi — il compilatore lo impone.

---

## 4. Regole di Inferenza del Transpiler

### 4.1 Mutabilità

In Rust le variabili sono immutabili per default (`let`).
Le variabili mutabili richiedono `let mut`.

**Regola:** il transpiler analizza se una variabile viene riassegnata nel suo scope:
- Mai riassegnata → `let`
- Riassegnata almeno una volta → `let mut`

```python
nome: str = "Alice"    # mai cambiata
contatore: int = 0     # cambiata nel loop
contatore = contatore + 1
```

```rust
let nome: &str = "Alice";       // immutabile
let mut contatore: i64 = 0;     // mutabile
contatore = contatore + 1;
```

Inferibile con una singola passata di analisi statica — nessuna ambiguità.

### 4.2 Ownership nei loop

```python
numeri: list[int] = [1, 2, 3]
for n in numeri:
    print(n)
print(numeri)  # numeri usata dopo il loop
```

```rust
let mut numeri: Vec<i64> = vec![1, 2, 3];
for n in &numeri {     // & aggiunto: ownership non consumata
    println!("{}", n);
}
println!("{:?}", numeri);  // ok, numeri esiste ancora
```

**Regola:** se la collezione viene usata dopo il loop, aggiungere `&`. Inferibile con analisi del flusso.

### 4.3 F-string → println!/format!

```python
print(f"Ciao {nome}, hai {x} anni")
saluto: str = f"Ciao {nome}"
```

```rust
println!("Ciao {}, hai {} anni", nome, x);
let saluto: String = format!("Ciao {}", nome);
```

---

## 5. Cosa è Escluso dal Subset

| Feature Python | Motivo esclusione |
|----------------|-------------------|
| Classi con ereditarietà | Non esiste in Rust, va ripensata come struct+trait |
| `raise/try/except` | Modello diverso, sostituito da Option/Result |
| Librerie esterne | Dipendenze non mappabili deterministicamente |
| Liste eterogenee `[1, "a", 3.14]` | Vec<T> richiede tipo uniforme |
| `*args`, `**kwargs` | Troppo dinamico |
| Duck typing | Solo tipi concreti |
| Interi oltre i64 | Richiederebbero librerie esterne (BigInt) |
| `None` implicito | Sostituito da `Optional[T]` esplicito |
| Ereditarietà multipla | Non esiste in Rust |

---

## 6. Confronto Hello World

Il punto di partenza — già traducibile deterministicamente:

```python
# Python
def main():
    print("Hello, World!")

main()
```

```rust
// Rust generato
fn main() {
    println!("Hello, World!");
}
```

Differenze visibili già qui:
- `fn` invece di `def`
- `println!` è una macro (il `!` lo indica)
- `;` obbligatorio a fine istruzione
- Nessuna chiamata esplicita a `main()` — è il punto di ingresso per convenzione

---

## 7. Quando Vale la Pena

PyFast ha senso per:
- Codice **CPU-bound** — algoritmi, parsing, calcoli
- Script eseguiti **frequentemente** — il costo di compilazione si ammortizza subito
- Team che conosce Python ma non vuole imparare Rust
- **Progetti didattici** — impara compilatori e Rust contemporaneamente

Non ha senso per:
- Codice **I/O-bound** — web app, query database (il collo di bottiglia non è il linguaggio)
- Script eseguiti **raramente** — non si ammortizza la compilazione
- Codice che usa **librerie Python ricche** — pandas, numpy, PyTorch

---

## 8. Milestone di Sviluppo

### Milestone 1 — Hello World + variabili base
- `def main()` → `fn main()`
- `print(...)` → `println!(...)`
- Variabili con type hints
- Inferenza `mut`
- F-string semplici

### Milestone 2 — Controllo di flusso
- `if/elif/else`
- `while` con contatore
- `for` su range e collezioni

### Milestone 3 — Funzioni
- Definizione con type hints obbligatorie
- Valori di ritorno
- Chiamate tra funzioni

### Milestone 4 — Collezioni
- `list[T]` → `Vec<T>`
- `dict[K,V]` → `HashMap<K,V>`
- `tuple` → tuple Rust

### Milestone 5 — Gestione errori
- `Optional[T]` → `Option<T>`
- `Result[T, str]` → `Result<T, &str>`
- Eliminazione `raise/try/except`

### Milestone 6 — Tool completo
- Cache con hash MD5
- Esecuzione Python in foreground alla prima run
- Compilazione Rust in background
- Sostituzione automatica nelle run successive

---

## 9. Strumenti Esistenti

- **py2many** — transpiler Python verso vari linguaggi (Rust incluso). Funziona su subset semplice, non è production-ready.
- **PyO3** — alternativa diversa: scrivere estensioni Rust chiamabili da Python. Utile se vuoi ottimizzare solo parti critiche.
- **Nuitka** — compila Python in C, approccio diverso ma obiettivo simile.

PyFast si differenzia per la **trasparenza totale** verso l'utente e la strategia di esecuzione ibrida (Python subito + Rust in background).

---

## 10. Note Tecniche

### Modulo ast di Python
Il parser è già disponibile nella stdlib — nessuna dipendenza esterna:

```python
import ast

source = """
def main():
    x: int = 42
    print(x)
"""

tree = ast.parse(source)
print(ast.dump(tree, indent=2))
```

Produce l'AST navigabile con tutti i nodi tipizzati — la base del transpiler.

### Compilazione Rust
- Prima compilazione: 2-10 secondi per progetti piccoli
- Ricompilazione: solo se il sorgente Python cambia (rilevato via hash)
- Esecuzione binario: millisecondi, nessun overhead interprete
