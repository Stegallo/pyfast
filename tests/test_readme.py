"""Test di coerenza README ↔ codice.

Ogni test corrisponde a un esempio o a un'affermazione specifica nel README.
Se un test fallisce, il README va aggiornato (o il codice corretto).

Sezioni coperte:
  - Tabella dei tipi (README § "Regola 2 — Tipi supportati")
  - Messaggi di errore (README § "Messaggi di errore comuni")
  - Esempi di codice (README § "Regola 3", "Esempio completo")
  - Mutability inference (README § "Nota: PyFast inferisce automaticamente…")
"""

import ast
import textwrap

import pytest

from pyfast.transpiler.analyzer import analyze
from pyfast.transpiler.generator import RustGenerator, TranspileError


def transpile(source: str) -> str:
    source = textwrap.dedent(source).strip()
    tree = ast.parse(source)
    analysis = analyze(tree)
    gen = RustGenerator(analysis)
    return gen.generate(tree)


# ---------------------------------------------------------------------------
# Tabella dei tipi (README § "Regola 2 — Tipi supportati")
# ---------------------------------------------------------------------------

class TestReadmeTypeTable:
    """Ogni riga della tabella ha un test corrispondente."""

    def test_int_maps_to_i64(self):
        rust = transpile("x: int = 42")
        assert "i64" in rust, "README: int → i64"

    def test_float_maps_to_f64(self):
        rust = transpile("pi: float = 3.14")
        assert "f64" in rust, "README: float → f64"

    def test_bool_maps_to_bool(self):
        rust = transpile("attivo: bool = True")
        assert "bool" in rust, "README: bool → bool"

    def test_str_literal_maps_to_ref_str(self):
        rust = transpile('nome: str = "Alice"')
        assert "&str" in rust, "README: str (letterale) → &str"

    def test_str_fstring_maps_to_string_owned(self):
        rust = transpile('s: str = f"Ciao {nome}"')
        assert "String" in rust, "README: str (f-string/runtime) → String"

    def test_list_int_maps_to_vec_i64(self):
        rust = transpile("""
            def foo() -> None:
                numeri: list[int] = [1, 2, 3]
        """)
        assert "Vec<i64>" in rust, "README: list[int] → Vec<i64>"

    def test_dict_str_int_maps_to_hashmap(self):
        rust = transpile("""
            def foo() -> None:
                d: dict[str, int] = {}
        """)
        assert "HashMap<&str, i64>" in rust, "README: dict[str, int] → HashMap<&str, i64>"

    def test_optional_int_maps_to_option_i64(self):
        rust = transpile("""
            from typing import Optional
            def foo(x: Optional[int]) -> None:
                pass
        """)
        assert "Option<i64>" in rust, "README: Optional[int] → Option<i64>"


# ---------------------------------------------------------------------------
# Messaggi di errore (README § "Messaggi di errore comuni")
# ---------------------------------------------------------------------------

class TestReadmeErrorMessages:
    """Verifica che i messaggi di errore documentati corrispondano a quelli reali."""

    def test_missing_local_type_hint_error(self):
        """README: 'variabile 'x' usata senza type hint — aggiungi `x: <tipo> = ...`'"""
        with pytest.raises(TranspileError) as exc:
            transpile("""
                def main() -> None:
                    x = 0
            """)
        msg = str(exc.value)
        assert "x" in msg
        assert "type hint" in msg
        assert exc.value.lineno is not None, "Il TranspileError deve includere il numero di riga"

    def test_missing_param_type_hint_error(self):
        """README: errore su parametro senza type hint."""
        with pytest.raises(TranspileError) as exc:
            transpile("""
                def f(x) -> None:
                    pass
            """)
        assert "x" in str(exc.value)

    def test_error_includes_line_number(self):
        """README mostra il numero di riga nell'errore — deve essere presente."""
        with pytest.raises(TranspileError) as exc:
            transpile("""
                def main() -> None:
                    contatore = 0
            """)
        assert exc.value.lineno is not None


# ---------------------------------------------------------------------------
# Esempi di codice (README § "Regola 3 — Costrutti supportati")
# ---------------------------------------------------------------------------

class TestReadmeConstructs:

    def test_function_with_params_and_return(self):
        """README: funzione con parametri e valore di ritorno."""
        rust = transpile("""
            def somma(a: int, b: int) -> int:
                return a + b
        """)
        assert "fn somma(a: i64, b: i64) -> i64" in rust

    def test_function_void(self):
        """README: funzione senza valore di ritorno (-> None)."""
        rust = transpile("""
            def stampa_saluto(nome: str) -> None:
                print(f"Ciao {nome}!")
        """)
        assert "fn stampa_saluto" in rust
        assert 'println!("Ciao {}!", nome)' in rust

    def test_augmented_assignment(self):
        """README: operatori augmented assignment (+=, -=, *=, /=)."""
        rust = transpile("x: int = 10\nx += 5")
        assert "x += 5;" in rust

    def test_reassignment_infers_mut(self):
        """README: 'PyFast inferisce `let mut` dove la variabile è riassegnata.'"""
        rust = transpile("""
            def esempio() -> None:
                x: int = 10
                x = 20
        """)
        assert "let mut x: i64 = 10;" in rust

    def test_no_reassignment_is_immutable(self):
        """README (implicito): variabile non riassegnata → let (non let mut)."""
        rust = transpile("""
            def esempio() -> None:
                x: int = 10
        """)
        assert "let x: i64 = 10;" in rust
        assert "let mut" not in rust

    def test_if_elif_else(self):
        """README: condizionale completo con elif/else."""
        rust = transpile("""
            def classifica(punteggio: int) -> None:
                if punteggio >= 90:
                    print("ottimo")
                elif punteggio >= 60:
                    print("sufficiente")
                else:
                    print("insufficiente")
        """)
        assert "if (punteggio >= 90)" in rust
        assert "} else if (punteggio >= 60) {" in rust
        assert "} else {" in rust

    def test_while_loop(self):
        """README: ciclo while con variabile di controllo."""
        rust = transpile("""
            def conta() -> None:
                i: int = 0
                while i < 10:
                    i = i + 1
        """)
        assert "while (i < 10)" in rust

    def test_for_range(self):
        """README: for i in range(n) → for i in 0..n"""
        rust = transpile("""
            def range_loop() -> None:
                for i in range(5):
                    print(i)
        """)
        assert "for i in 0..5" in rust

    def test_for_list(self):
        """README: for su lista."""
        rust = transpile("""
            def somma_lista() -> None:
                numeri: list[int] = [1, 2, 3, 4, 5]
                totale: int = 0
                for n in numeri:
                    totale = totale + n
                print(totale)
        """)
        assert "for n in" in rust

    def test_print_literal(self):
        """README: print("Testo semplice") → println!("Testo semplice")"""
        rust = transpile('print("Testo semplice")')
        assert 'println!("Testo semplice")' in rust

    def test_print_variable(self):
        """README: print(nome) → println!("{}", nome)"""
        rust = transpile("print(nome)")
        assert 'println!("{}", nome)' in rust

    def test_print_fstring(self):
        """README: print(f"Ciao {nome}, hai {eta} anni") → println!(...)"""
        rust = transpile('print(f"Ciao {nome}, hai {eta} anni")')
        assert 'println!("Ciao {}, hai {} anni", nome, eta)' in rust


# ---------------------------------------------------------------------------
# Esempio completo fibonacci (README § "Esempio completo")
# ---------------------------------------------------------------------------

class TestReadmeFibonacciExample:
    """Verifica l'esempio fibonacci mostrato nel README, incluso il Rust generato."""

    FIBONACCI_SOURCE = """
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
    """

    def test_transpiles_without_error(self):
        """L'esempio fibonacci del README deve transpilare senza eccezioni."""
        transpile(self.FIBONACCI_SOURCE)  # non deve sollevare

    def test_function_signatures(self):
        """README mostra: fn fibonacci(n: i64) -> i64 e fn main()"""
        rust = transpile(self.FIBONACCI_SOURCE)
        assert "fn fibonacci(n: i64) -> i64" in rust
        assert "fn main()" in rust

    def test_mutability_inference_on_reassigned_vars(self):
        """README nota: a, b, i sono riassegnate → mut. c non lo è → immutable."""
        rust = transpile(self.FIBONACCI_SOURCE)
        assert "let mut a: i64 = 0;" in rust  # a = b nel loop
        assert "let mut b: i64 = 1;" in rust  # b = c nel loop
        assert "let mut i: i64 = 2;" in rust  # i = i + 1 nel loop
        assert "let c: i64" in rust            # c non è riassegnata

    def test_result_snippet_from_readme(self):
        """Frammenti Rust esatti mostrati nel README."""
        rust = transpile(self.FIBONACCI_SOURCE)
        assert "let mut result: i64 = 0;" in rust
        assert "result = fibonacci(n);" in rust
        assert 'println!("{}", result)' in rust
