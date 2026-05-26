"""Analisi statica del codice Python per supportare la generazione Rust.

Passate di analisi implementate:
  1. MutabilityAnalyzer  — determina quali variabili richiedono `let mut`
  2. StringOwnershipAnalyzer — determina quali `str` richiedono `String` vs `&str`
  3. OwnershipAnalyzer   — determina quali collezioni nei loop richiedono `&`

Tutte le analisi lavorano a livello di *scope di funzione*: le variabili di
funzioni diverse sono trattate indipendentemente.
"""

import ast
from dataclasses import dataclass, field


@dataclass
class AnalysisResult:
    """Risultato dell'analisi per una singola funzione (o scope globale)."""

    # Variabili che vengono riassegnate → `let mut`
    mutable_vars: set[str] = field(default_factory=set)

    # Variabili `str` costruite a runtime (f-string, concatenazione) → `String`
    owned_strings: set[str] = field(default_factory=set)

    # Collezioni usate *dopo* un loop che le itera → `for x in &coll`
    borrowed_in_loop: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Mutabilità
# ---------------------------------------------------------------------------

class MutabilityAnalyzer(ast.NodeVisitor):
    """Segna come `mutable` ogni variabile assegnata più di una volta.

    Regola (dal design doc):
      - Mai riassegnata → `let`
      - Riassegnata almeno una volta → `let mut`

    Algoritmo: conta le assegnazioni per ogni nome nello scope.
    Una variabile è mutable se il conteggio > 1.
    I loop aggiuntano un'assegnazione implicita alla var di iterazione
    (es. `for i in ...` → `i` è assegnata ad ogni iterazione).
    """

    def __init__(self) -> None:
        self._assign_count: dict[str, int] = {}

    def analyze(self, node: ast.AST) -> AnalysisResult:
        """Analizza un albero (modulo o funzione) e restituisce il risultato."""
        self._assign_count = {}
        self.visit(node)

        result = AnalysisResult()
        result.mutable_vars = {name for name, cnt in self._assign_count.items() if cnt > 1}
        return result

    # --- Nodi assegnazione ---

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Annotated assignment: `x: int = 5`"""
        if isinstance(node.target, ast.Name):
            self._record(node.target.id)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Simple assignment: `x = 5`"""
        for target in node.targets:
            if isinstance(target, ast.Name):
                self._record(target.id)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """`x += 1` — riassegna sempre → certamente mutable."""
        if isinstance(node.target, ast.Name):
            # AugAssign conta come riassegnazione, la registriamo due volte
            # per garantire che venga marcata mutable.
            self._record(node.target.id)
            self._record(node.target.id)
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        """La variabile di loop è assegnata ad ogni iterazione → mutable."""
        if isinstance(node.target, ast.Name):
            # Registriamo due volte: prima assegnazione + riassegnazioni nel loop
            self._record(node.target.id)
            self._record(node.target.id)
        self.generic_visit(node)

    # --- Helpers ---

    def _record(self, name: str) -> None:
        self._assign_count[name] = self._assign_count.get(name, 0) + 1


# ---------------------------------------------------------------------------
# String ownership
# ---------------------------------------------------------------------------

class StringOwnershipAnalyzer(ast.NodeVisitor):
    """Determina quali variabili `str` sono costruite a runtime.

    Regola:
      - Stringa letterale `"hello"` → `&str` (immutabile, nota a compile-time)
      - F-string `f"..."` o concatenazione → `String` (costruita a runtime)

    La distinzione è inferibile analizzando il valore dell'assegnazione.
    """

    def __init__(self) -> None:
        self._owned: set[str] = set()

    def analyze(self, node: ast.AST) -> set[str]:
        """Restituisce l'insieme dei nomi variabile che richiedono `String`."""
        self._owned = set()
        self.visit(node)
        return self._owned

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            if self._is_owned_string(node.value):
                self._owned.add(node.target.id)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._is_owned_string(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self._owned.add(target.id)
        self.generic_visit(node)

    @staticmethod
    def _is_owned_string(node: ast.expr) -> bool:
        """True se il valore è una stringa costruita a runtime."""
        # F-string: `f"Ciao {nome}"`
        if isinstance(node, ast.JoinedStr):
            return True
        # Concatenazione: `"a" + var`
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return True
        # Chiamata a str() o metodi su stringa
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "str":
                return True
            if isinstance(func, ast.Attribute):
                return True  # .join(), .format(), ...
        return False


# ---------------------------------------------------------------------------
# Loop ownership (borrow checker hint)
# ---------------------------------------------------------------------------

class LoopOwnershipAnalyzer(ast.NodeVisitor):
    """Determina quali collezioni iterarte in un loop sono usate dopo il loop.

    Se una collezione è usata *dopo* il loop che la itera, va passata
    per reference: `for x in &lista` invece di `for x in lista`.

    Algoritmo semplificato: per ogni for loop, controlla se l'iterabile
    appare come nome in istruzioni successive nello stesso blocco.
    """

    def __init__(self) -> None:
        self._borrowed: set[str] = set()

    def analyze(self, node: ast.AST) -> set[str]:
        self._borrowed = set()
        self.visit(node)
        return self._borrowed

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._analyze_block(node.body)
        # non visitiamo ricorsivamente — scope separati

    def visit_Module(self, node: ast.Module) -> None:
        self._analyze_block(node.body)

    def _analyze_block(self, stmts: list[ast.stmt]) -> None:
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, ast.For):
                iterable = stmt.iter
                if isinstance(iterable, ast.Name):
                    coll_name = iterable.id
                    # Verifica se coll_name appare nei nodi successivi
                    rest = stmts[i + 1 :]
                    if self._name_used_in(coll_name, rest):
                        self._borrowed.add(coll_name)
                # Ricorsione nel corpo del for (loop annidati)
                self._analyze_block(stmt.body)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Ricorsione nel corpo della funzione (scope separato)
                self._analyze_block(stmt.body)
            elif isinstance(stmt, ast.If):
                self._analyze_block(stmt.body)
                if stmt.orelse:
                    self._analyze_block(stmt.orelse)
            elif isinstance(stmt, ast.While):
                self._analyze_block(stmt.body)

    @staticmethod
    def _name_used_in(name: str, stmts: list[ast.stmt]) -> bool:
        """True se `name` appare come ast.Name in uno qualsiasi degli stmt."""
        for stmt in stmts:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Name) and node.id == name:
                    return True
        return False


# ---------------------------------------------------------------------------
# Analisi composta (entry point pubblico)
# ---------------------------------------------------------------------------

def analyze(tree: ast.AST) -> AnalysisResult:
    """Esegui tutte le passate di analisi e restituisci un AnalysisResult unificato."""
    mut_result = MutabilityAnalyzer().analyze(tree)
    owned_strings = StringOwnershipAnalyzer().analyze(tree)
    borrowed = LoopOwnershipAnalyzer().analyze(tree)

    return AnalysisResult(
        mutable_vars=mut_result.mutable_vars,
        owned_strings=owned_strings,
        borrowed_in_loop=borrowed,
    )
