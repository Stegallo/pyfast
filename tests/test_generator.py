"""Test per il modulo generator.

Ogni test verifica che il codice Rust generato contenga le costruzioni attese.
Usiamo contains-substring invece di uguaglianza esatta per rendere i test
robusti a variazioni di spaziatura/indentazione.
"""

import ast
import textwrap
import pytest

from pyfast.transpiler.analyzer import analyze
from pyfast.transpiler.generator import RustGenerator


def transpile(source: str) -> str:
    """Helper: analizza + genera Rust da sorgente Python."""
    source = textwrap.dedent(source).strip()
    tree = ast.parse(source)
    analysis = analyze(tree)
    gen = RustGenerator(analysis)
    return gen.generate(tree)


# ---------------------------------------------------------------------------
# Hello World
# ---------------------------------------------------------------------------

class TestHelloWorld:
    def test_basic_print(self):
        rust = transpile("""
            def main() -> None:
                print("Hello, World!")
        """)
        assert 'fn main()' in rust
        assert 'println!("Hello, World!")' in rust

    def test_function_no_return(self):
        rust = transpile("def foo() -> None:\n    pass")
        assert "fn foo()" in rust
        assert "// pass" in rust


# ---------------------------------------------------------------------------
# Variabili scalari
# ---------------------------------------------------------------------------

class TestVariables:
    def test_immutable_int(self):
        rust = transpile("x: int = 42")
        assert "let x: i64 = 42;" in rust

    def test_mutable_int_reassigned(self):
        rust = transpile("x: int = 0\nx = 1")
        assert "let mut x: i64 = 0;" in rust

    def test_float(self):
        rust = transpile("pi: float = 3.14")
        assert "let pi: f64 = 3.14;" in rust

    def test_bool_true(self):
        rust = transpile("flag: bool = True")
        assert "let flag: bool = true;" in rust

    def test_bool_false(self):
        rust = transpile("flag: bool = False")
        assert "let flag: bool = false;" in rust

    def test_literal_string(self):
        rust = transpile('nome: str = "Alice"')
        assert 'let nome: &str = "Alice";' in rust

    def test_fstring_string_owned(self):
        rust = transpile('s: str = f"Ciao {nome}"')
        assert "let s: String" in rust
        assert "format!" in rust


# ---------------------------------------------------------------------------
# F-string e print
# ---------------------------------------------------------------------------

class TestFString:
    def test_fstring_in_print(self):
        rust = transpile('print(f"Ciao {nome}")')
        assert 'println!("Ciao {}", nome)' in rust

    def test_fstring_multiple_vars(self):
        rust = transpile('print(f"Nome: {nome}, Eta: {eta}")')
        assert 'println!("Nome: {}, Eta: {}", nome, eta)' in rust

    def test_fstring_assign(self):
        rust = transpile('s: str = f"Valore: {x}"')
        assert 'format!("Valore: {}", x)' in rust

    def test_print_variable(self):
        rust = transpile("print(x)")
        assert 'println!("{}", x)' in rust

    def test_print_literal(self):
        rust = transpile('print("ciao")')
        assert 'println!("ciao")' in rust


# ---------------------------------------------------------------------------
# Funzioni con parametri
# ---------------------------------------------------------------------------

class TestFunctions:
    def test_function_with_params(self):
        rust = transpile("""
            def somma(a: int, b: int) -> int:
                return a + b
        """)
        assert "fn somma(a: i64, b: i64) -> i64" in rust
        assert "(a + b)" in rust

    def test_function_returns_str(self):
        rust = transpile("""
            def greet(nome: str) -> str:
                return nome
        """)
        assert "fn greet(nome: &str)" in rust

    def test_missing_type_hint_raises(self):
        from pyfast.transpiler.generator import TranspileError
        with pytest.raises(TranspileError):
            transpile("""
                def foo(x) -> None:
                    pass
            """)


# ---------------------------------------------------------------------------
# Espressioni
# ---------------------------------------------------------------------------

class TestExpressions:
    def test_binary_add(self):
        rust = transpile("z: int = x + y")
        assert "(x + y)" in rust

    def test_aug_assign(self):
        rust = transpile("x: int = 0\nx += 1")
        assert "x += 1;" in rust

    def test_comparison(self):
        rust = transpile("""
            def check(x: int) -> bool:
                return x > 0
        """)
        assert "(x > 0)" in rust


# ---------------------------------------------------------------------------
# Controllo di flusso (Milestone 2)
# ---------------------------------------------------------------------------

class TestControlFlow:
    def test_if_else(self):
        rust = transpile("""
            def foo(x: int) -> None:
                if x > 0:
                    print("positivo")
                else:
                    print("non positivo")
        """)
        assert "if (x > 0)" in rust
        assert "} else {" in rust

    def test_while_loop(self):
        rust = transpile("""
            def foo() -> None:
                i: int = 0
                while i < 10:
                    i = i + 1
        """)
        assert "while (i < 10)" in rust

    def test_for_range(self):
        rust = transpile("""
            def foo() -> None:
                for i in range(5):
                    print(i)
        """)
        assert "for i in 0..5" in rust

    def test_for_collection_with_borrow(self):
        """Se la collezione è usata dopo il loop → &lista"""
        rust = transpile("""
def foo() -> None:
    numeri = [1, 2, 3]
    for n in numeri:
        print(n)
    print(numeri)
""")
        assert "for n in &numeri" in rust

    def test_if_elif_else(self):
        rust = transpile("""
            def foo(x: int) -> None:
                if x > 0:
                    print("pos")
                elif x < 0:
                    print("neg")
                else:
                    print("zero")
        """)
        assert "if (x > 0)" in rust
        assert "} else if (x < 0) {" in rust
        assert "} else {" in rust


# ---------------------------------------------------------------------------
# Type mapper
# ---------------------------------------------------------------------------

class TestTypeMapper:
    def test_optional_type(self):
        rust = transpile("""
            from typing import Optional
            def foo(x: Optional[int]) -> None:
                pass
        """)
        assert "Option<i64>" in rust

    def test_list_type(self):
        rust = transpile("""
            def foo() -> None:
                numeri: list[int] = [1, 2, 3]
        """)
        assert "Vec<i64>" in rust

    def test_dict_needs_import(self):
        rust = transpile("""
            def foo() -> None:
                d: dict[str, int] = {}
        """)
        assert "use std::collections::HashMap;" in rust
        assert "HashMap<&str, i64>" in rust
