"""Crivello di Eratostene — esempio CPU-bound ideale per il benchmark.

Calcola tutti i numeri primi fino a N.
Algoritmicamente semplice, ma richiede molte operazioni integer →
  il gap Python/Rust è massimo qui.

Adatto per: pyfast bench examples/primes.py
"""


def count_primes(n: int) -> int:
    """Conta i numeri primi fino a n usando un crivello semplice."""
    if n < 2:
        return 0

    count: int = 0
    i: int = 2
    while i <= n:
        is_prime: bool = True
        j: int = 2
        while j * j <= i:
            if i % j == 0:
                is_prime = False
                j = i  # break equivalente
            j = j + 1
        if is_prime:
            count = count + 1
        i = i + 1
    return count


def main() -> None:
    limite: int = 1000000
    result: int = count_primes(limite)
    print(result)


main()
