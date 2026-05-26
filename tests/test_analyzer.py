"""Test per il modulo analyzer."""

import ast
import pytest

from pyfast.transpiler.analyzer import (
    MutabilityAnalyzer,
    StringOwnershipAnalyzer,
    LoopOwnershipAnalyzer,
    analyze,
)


def _parse(source: str) -> ast.AST:
    return ast.parse(source)


# ---------------------------------------------------------------------------
# MutabilityAnalyzer
# ---------------------------------------------------------------------------

class TestMutabilityAnalyzer:
    def test_single_assignment_is_immutable(self):
        tree = _parse("x: int = 5")
        result = MutabilityAnalyzer().analyze(tree)
        assert "x" not in result.mutable_vars

    def test_reassigned_variable_is_mutable(self):
        tree = _parse("""
x: int = 0
x = 1
""")
        result = MutabilityAnalyzer().analyze(tree)
        assert "x" in result.mutable_vars

    def test_aug_assign_is_mutable(self):
        tree = _parse("""
contatore: int = 0
contatore += 1
""")
        result = MutabilityAnalyzer().analyze(tree)
        assert "contatore" in result.mutable_vars

    def test_for_loop_var_is_mutable(self):
        tree = _parse("""
for i in range(10):
    pass
""")
        result = MutabilityAnalyzer().analyze(tree)
        assert "i" in result.mutable_vars

    def test_two_distinct_vars(self):
        tree = _parse("""
a: int = 1
b: int = 2
b = 3
""")
        result = MutabilityAnalyzer().analyze(tree)
        assert "a" not in result.mutable_vars
        assert "b" in result.mutable_vars

    def test_function_scope(self):
        tree = _parse("""
def foo():
    x: int = 5
    x = 10
    y: int = 3
""")
        result = MutabilityAnalyzer().analyze(tree)
        assert "x" in result.mutable_vars
        assert "y" not in result.mutable_vars


# ---------------------------------------------------------------------------
# StringOwnershipAnalyzer
# ---------------------------------------------------------------------------

class TestStringOwnershipAnalyzer:
    def test_literal_string_not_owned(self):
        tree = _parse('nome: str = "Alice"')
        owned = StringOwnershipAnalyzer().analyze(tree)
        assert "nome" not in owned

    def test_fstring_is_owned(self):
        tree = _parse('saluto: str = f"Ciao {nome}"')
        owned = StringOwnershipAnalyzer().analyze(tree)
        assert "saluto" in owned

    def test_concatenation_is_owned(self):
        tree = _parse('s: str = "a" + b')
        owned = StringOwnershipAnalyzer().analyze(tree)
        assert "s" in owned

    def test_int_not_owned(self):
        tree = _parse("n: int = 42")
        owned = StringOwnershipAnalyzer().analyze(tree)
        assert "n" not in owned


# ---------------------------------------------------------------------------
# LoopOwnershipAnalyzer
# ---------------------------------------------------------------------------

class TestLoopOwnershipAnalyzer:
    def test_collection_used_after_loop_is_borrowed(self):
        tree = _parse("""
numeri = [1, 2, 3]
for n in numeri:
    pass
print(numeri)
""")
        borrowed = LoopOwnershipAnalyzer().analyze(tree)
        assert "numeri" in borrowed

    def test_collection_not_used_after_loop_not_borrowed(self):
        tree = _parse("""
numeri = [1, 2, 3]
for n in numeri:
    pass
""")
        borrowed = LoopOwnershipAnalyzer().analyze(tree)
        assert "numeri" not in borrowed

    def test_range_not_borrowed(self):
        tree = _parse("""
for i in range(10):
    pass
""")
        borrowed = LoopOwnershipAnalyzer().analyze(tree)
        assert len(borrowed) == 0


# ---------------------------------------------------------------------------
# analyze() — funzione composta
# ---------------------------------------------------------------------------

class TestAnalyze:
    def test_full_analysis(self):
        source = """
def main():
    nome: str = "Alice"
    saluto: str = f"Ciao {nome}"
    contatore: int = 0
    contatore = contatore + 1
    print(saluto)
"""
        tree = _parse(source)
        result = analyze(tree)

        assert "nome" not in result.mutable_vars
        assert "contatore" in result.mutable_vars
        assert "saluto" in result.owned_strings
        assert "nome" not in result.owned_strings
