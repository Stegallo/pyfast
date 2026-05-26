"""Milestone 1 — Variabili tipizzate con inferenza mut.

Dimostra:
  - Variabili scalari con type hints
  - Inferenza let vs let mut
  - F-string → format!/println!
  - Stringa letterale (&str) vs costruita (String)
"""


def greet(nome: str) -> None:
    saluto: str = f"Ciao, {nome}!"
    print(saluto)


def counter_demo() -> None:
    start: int = 0
    contatore: int = start    # immutabile: mai riassegnato
    limite: int = 5

    # contatore viene riassegnato → let mut
    contatore = 0
    while contatore < limite:
        print(contatore)
        contatore = contatore + 1


def main() -> None:
    nome_fisso: str = "Alice"      # letterale → &str
    greet(nome_fisso)
    counter_demo()

    pi: float = 3.14159
    attivo: bool = True
    print(pi)
    print(attivo)


main()
