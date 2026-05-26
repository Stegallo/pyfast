"""Milestone 1+2 — Fibonacci iterativo.

Dimostra:
  - Funzioni con parametri e valore di ritorno
  - While loop con contatore
  - Variabili mutabili e immutabili
  - Aritmetica intera
"""


def fibonacci(n: int) -> int:
    """Calcola l'n-esimo numero di Fibonacci (iterativo)."""
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
    limite: int = 10
    i: int = 0
    while i <= limite:
        result: int = fibonacci(i)
        print(result)
        i = i + 1


main()
