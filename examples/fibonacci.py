"""Fibonacci iterativo — esempio Milestone 1+2.

Nota: il subset PyFast usa i64 (max ~9.2e18).
      fibonacci(n) overflowa i64 per n > 92.
      Benchmark corretto: ripetere molte volte con n <= 90.

Per il benchmark Python vs Rust usa invece: pyfast bench examples/primes.py
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
    # Ripetiamo molte volte con n<=90 per restare in i64 e avere un benchmark significativo
    runs: int = 1000000
    n: int = 90
    i = 0
    result: int = 0

    while i < runs:
        result = fibonacci(n)
        i = i + 1

    print(result)


main()
