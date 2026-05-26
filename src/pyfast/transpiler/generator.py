"""Generatore di codice Rust a partire dall'AST Python.

Il generatore visita l'AST e produce una stringa di codice Rust valido.
Usa i risultati dell'analisi (mutabilità, string ownership, borrowing)
per produrre dichiarazioni corrette.

Milestone 1 implementato:
  ✅ Funzioni `def` → `fn`
  ✅ `print(...)` → `println!(...)`
  ✅ Variabili con type hints (`AnnAssign`)
  ✅ Inferenza `let` / `let mut`
  ✅ F-string → `format!` / `println!` con placeholders
  ✅ Costanti scalari (int, float, bool, str)
  ✅ Espressioni binarie e comparazioni
  ✅ Return

Milestone 2 parzialmente implementato (stub):
  ✅ `if/elif/else`
  ✅ `while`
  ✅ `for i in range(n)`
  ✅ `for x in lista` con inferenza borrow
"""

import ast
from typing import IO

from pyfast.transpiler.analyzer import AnalysisResult
from pyfast.transpiler.type_mapper import annotation_to_rust


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INDENT = "    "  # 4 spazi — stile Rust standard


def _needs_hashmap(tree: ast.AST) -> bool:
    """Verifica se il codice usa dict → richiede `use std::collections::HashMap;`"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and node.value.id == "dict":
                return True
    return False


# ---------------------------------------------------------------------------
# Generatore principale
# ---------------------------------------------------------------------------

class RustGenerator(ast.NodeVisitor):
    """Visita l'AST Python e genera codice Rust.

    Uso:
        gen = RustGenerator(analysis_result)
        rust_code = gen.generate(ast_tree)
    """

    def __init__(self, analysis: AnalysisResult) -> None:
        self._analysis = analysis
        self._indent_level = 0
        self._lines: list[str] = []
        # Variabili dichiarate nello scope corrente (via AnnAssign, parametri, for).
        # Usato da visit_Assign per distinguere prima dichiarazione (errore: manca
        # type hint) da riassegnazione legittima.
        self._declared_vars: set[str] = set()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def generate(self, tree: ast.Module) -> str:
        """Genera il codice Rust completo da un modulo Python."""
        self._lines = []

        # Import Rust necessari
        if _needs_hashmap(tree):
            self._emit("use std::collections::HashMap;")
            self._emit("")

        self.visit(tree)
        return "\n".join(self._lines)

    # ------------------------------------------------------------------
    # Emissione linee
    # ------------------------------------------------------------------

    def _emit(self, line: str = "") -> None:
        prefix = INDENT * self._indent_level
        self._lines.append(f"{prefix}{line}" if line else "")

    def _indent(self) -> None:
        self._indent_level += 1

    def _dedent(self) -> None:
        self._indent_level -= 1

    # ------------------------------------------------------------------
    # Visita modulo e funzioni
    # ------------------------------------------------------------------

    def visit_Module(self, node: ast.Module) -> None:
        for stmt in node.body:
            # Salta docstring a livello di modulo (Constant str come Expr)
            if _is_docstring(stmt):
                continue
            # Salta `main()` a livello modulo — in Rust `fn main` è l'entry point
            if _is_main_call(stmt):
                continue
            self.visit(stmt)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Traduce `def foo(a: int, b: str) -> bool:` in `fn foo(a: i64, b: &str) -> bool {`"""
        # Argomenti
        params: list[str] = []
        for arg in node.args.args:
            if arg.annotation is None:
                raise TranspileError(
                    f"parametro '{arg.arg}' nella funzione '{node.name}' "
                    f"manca di type hint",
                    lineno=arg.lineno,
                    col=arg.col_offset,
                )
            rust_type = self._get_type(arg.annotation, var_name=arg.arg)
            params.append(f"{arg.arg}: {rust_type}")

        # Tipo di ritorno
        if node.returns and not _is_none_annotation(node.returns):
            ret_type = self._get_type(node.returns)
            ret = f" -> {ret_type}"
        else:
            ret = ""

        self._emit(f"fn {node.name}({', '.join(params)}){ret} {{")
        self._indent()

        # Nuovo scope: i parametri sono già dichiarati, le variabili locali no
        outer_declared = self._declared_vars
        self._declared_vars = {arg.arg for arg in node.args.args}

        for stmt in node.body:
            # Salta docstring di funzione (primo stmt se è Constant str)
            if _is_docstring(stmt):
                continue
            self.visit(stmt)

        self._declared_vars = outer_declared  # ripristina scope esterno
        self._dedent()
        self._emit("}")
        self._emit()

    # ------------------------------------------------------------------
    # Istruzioni
    # ------------------------------------------------------------------

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """`x: int = 5` → `let [mut] x: i64 = 5;`"""
        if not isinstance(node.target, ast.Name):
            return
        name = node.target.id
        self._declared_vars.add(name)  # registra nel scope corrente
        mut = "mut " if name in self._analysis.mutable_vars else ""
        is_owned = name in self._analysis.owned_strings
        rust_type = self._get_type(node.annotation, var_name=name, owned_str=is_owned)

        if node.value is not None:
            value = self._expr(node.value)
            self._emit(f"let {mut}{name}: {rust_type} = {value};")
        else:
            self._emit(f"let {mut}{name}: {rust_type};")

    def visit_Assign(self, node: ast.Assign) -> None:
        """Riassegnazione senza annotation: `x = expr`

        Se la variabile non è ancora dichiarata nello scope corrente,
        significa che manca il type hint sulla prima assegnazione → errore.
        """
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if name not in self._declared_vars:
                raise TranspileError(
                    f"variabile '{name}' usata senza type hint — "
                    f"aggiungi `{name}: <tipo> = ...`",
                    lineno=node.lineno,
                    col=node.col_offset,
                )
            value = self._expr(node.value)
            self._emit(f"{name} = {value};")

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """`x += 1` → `x += 1;`"""
        if isinstance(node.target, ast.Name):
            op = _binop_symbol(node.op)
            value = self._expr(node.value)
            self._emit(f"{node.target.id} {op}= {value};")

    def visit_Expr(self, node: ast.Expr) -> None:
        """Istruzione-espressione: chiamate a funzione come `print(...)`"""
        result = self._call_or_expr(node.value)
        if result:
            self._emit(f"{result};")

    def visit_Return(self, node: ast.Return) -> None:
        if node.value is None:
            self._emit("return;")
        else:
            # Usiamo sempre `return X;` — valido in qualsiasi posizione in Rust.
            # La tail expression senza return (idiomatica) richiederebbe
            # sapere se siamo all'ultimo statement — ottimizzazione futura.
            self._emit(f"return {self._expr(node.value)};")

    def visit_If(self, node: ast.If) -> None:
        """if / elif / else"""
        cond = self._expr(node.test)
        self._emit(f"if {cond} {{")
        self._indent()
        for stmt in node.body:
            self.visit(stmt)
        self._dedent()

        # elif / else
        orelse = node.orelse
        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                # elif
                elif_node = orelse[0]
                cond = self._expr(elif_node.test)
                self._emit(f"}} else if {cond} {{")
                self._indent()
                for stmt in elif_node.body:
                    self.visit(stmt)
                self._dedent()
                orelse = elif_node.orelse
            else:
                # else
                self._emit("} else {")
                self._indent()
                for stmt in orelse:
                    self.visit(stmt)
                self._dedent()
                orelse = []

        self._emit("}")

    def visit_While(self, node: ast.While) -> None:
        cond = self._expr(node.test)
        self._emit(f"while {cond} {{")
        self._indent()
        for stmt in node.body:
            self.visit(stmt)
        self._dedent()
        self._emit("}")

    def visit_For(self, node: ast.For) -> None:
        """for i in range(n) / for x in lista"""
        if not isinstance(node.target, ast.Name):
            self._emit("/* unsupported: complex for target */")
            return

        var = node.target.id
        self._declared_vars.add(var)  # la var di loop è dichiarata dal for stesso

        # Caso speciale: `for i in range(n)` → `for i in 0..n`
        if _is_range_call(node.iter):
            range_expr = self._range_to_rust(node.iter)
            self._emit(f"for {var} in {range_expr} {{")
        else:
            # Iterazione su collezione
            iter_name = self._expr(node.iter)
            borrow = "&" if isinstance(node.iter, ast.Name) and node.iter.id in self._analysis.borrowed_in_loop else ""
            self._emit(f"for {var} in {borrow}{iter_name} {{")

        self._indent()
        for stmt in node.body:
            self.visit(stmt)
        self._dedent()
        self._emit("}")

    def visit_Pass(self, node: ast.Pass) -> None:
        self._emit("// pass")

    def visit_Break(self, node: ast.Break) -> None:
        self._emit("break;")

    def visit_Continue(self, node: ast.Continue) -> None:
        self._emit("continue;")

    # Ignora le chiamate standalone fuori da funzioni (es. `main()` in Python)
    # — in Rust `main()` è l'entry point automatico
    def visit_Call_toplevel(self, node: ast.Call) -> None:
        pass

    # ------------------------------------------------------------------
    # Espressioni
    # ------------------------------------------------------------------

    def _call_or_expr(self, node: ast.expr) -> str | None:
        """Genera il codice per una istruzione-espressione."""
        if isinstance(node, ast.Call):
            func_name = _get_func_name(node.func)
            if func_name == "print":
                return self._translate_print(node)
            # Chiamata normale
            args = ", ".join(self._expr(a) for a in node.args)
            return f"{func_name}({args})"
        return self._expr(node)

    def _expr(self, node: ast.expr) -> str:
        """Genera il codice Rust per un'espressione Python."""
        # Costante
        if isinstance(node, ast.Constant):
            return _constant_to_rust(node)

        # Nome variabile
        if isinstance(node, ast.Name):
            if node.id == "None":
                return "None"
            if node.id == "True":
                return "true"
            if node.id == "False":
                return "false"
            return node.id

        # Operazione binaria
        if isinstance(node, ast.BinOp):
            left = self._expr(node.left)
            right = self._expr(node.right)
            op = _binop_symbol(node.op)
            return f"({left} {op} {right})"

        # Operazione unaria
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return f"-{self._expr(node.operand)}"
            if isinstance(node.op, ast.Not):
                return f"!{self._expr(node.operand)}"
            if isinstance(node.op, ast.UAdd):
                return self._expr(node.operand)

        # Comparazione
        if isinstance(node, ast.Compare):
            left = self._expr(node.left)
            parts = []
            for op, cmp in zip(node.ops, node.comparators):
                parts.append(f"{_cmpop_symbol(op)} {self._expr(cmp)}")
            return f"({left} {' '.join(parts)})"

        # Operazione booleana
        if isinstance(node, ast.BoolOp):
            op = " && " if isinstance(node.op, ast.And) else " || "
            return f"({op.join(self._expr(v) for v in node.values)})"

        # F-string
        if isinstance(node, ast.JoinedStr):
            fmt, values = _fstring_parts(node)
            if values:
                return f'format!("{fmt}", {", ".join(values)})'
            else:
                return f'"{fmt}".to_string()'

        # Chiamata a funzione
        if isinstance(node, ast.Call):
            func_name = _get_func_name(node.func)
            if func_name == "print":
                return self._translate_print(node)
            args = ", ".join(self._expr(a) for a in node.args)
            return f"{func_name}({args})"

        # Lista letterale
        if isinstance(node, ast.List):
            elems = ", ".join(self._expr(e) for e in node.elts)
            return f"vec![{elems}]"

        # Tupla letterale
        if isinstance(node, ast.Tuple):
            elems = ", ".join(self._expr(e) for e in node.elts)
            return f"({elems},)"

        # Subscript (accesso indice)
        if isinstance(node, ast.Subscript):
            obj = self._expr(node.value)
            idx = self._expr(node.slice)
            return f"{obj}[{idx} as usize]"

        # Attributo
        if isinstance(node, ast.Attribute):
            obj = self._expr(node.value)
            return f"{obj}.{node.attr}"

        return f"/* unsupported expr: {type(node).__name__} */"

    # ------------------------------------------------------------------
    # Print → println!
    # ------------------------------------------------------------------

    def _translate_print(self, node: ast.Call) -> str:
        """Traduce `print(...)` in `println!(...)`."""
        if not node.args:
            return 'println!("")'

        arg = node.args[0]

        # print("stringa letterale")
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            escaped = arg.value.replace('"', '\\"')
            return f'println!("{escaped}")'

        # print(f"f-string")
        if isinstance(arg, ast.JoinedStr):
            fmt, values = _fstring_parts(arg)
            if values:
                return f'println!("{fmt}", {", ".join(values)})'
            else:
                return f'println!("{fmt}")'

        # print(variabile) o print(espressione)
        expr = self._expr(arg)
        return f'println!("{{}}", {expr})'

    # ------------------------------------------------------------------
    # Helpers tipo
    # ------------------------------------------------------------------

    def _get_type(
        self,
        annotation: ast.expr,
        var_name: str | None = None,
        owned_str: bool | None = None,
    ) -> str:
        """Mappa un nodo annotation al tipo Rust, tenendo conto del contesto."""
        if owned_str is None and var_name is not None:
            owned_str = var_name in self._analysis.owned_strings
        return annotation_to_rust(annotation, owned_str=bool(owned_str))

    # ------------------------------------------------------------------
    # Range
    # ------------------------------------------------------------------

    def _range_to_rust(self, node: ast.Call) -> str:
        """Traduce `range(n)`, `range(a, b)`, `range(a, b, step)` in range Rust."""
        args = node.args
        if len(args) == 1:
            return f"0..{self._expr(args[0])}"
        if len(args) == 2:
            return f"{self._expr(args[0])}..{self._expr(args[1])}"
        if len(args) == 3:
            # range con step — usiamo step_by
            start = self._expr(args[0])
            stop = self._expr(args[1])
            step = self._expr(args[2])
            return f"({start}..{stop}).step_by({step} as usize)"
        return "0..0 /* invalid range */"


# ---------------------------------------------------------------------------
# Eccezione custom
# ---------------------------------------------------------------------------

class TranspileError(Exception):
    """Errore durante la transpilazione.

    Attributes:
        lineno: Numero di riga nel sorgente Python (None se non disponibile).
        col:    Colonna nel sorgente Python (None se non disponibile).
    """

    def __init__(self, message: str, lineno: int | None = None, col: int | None = None):
        super().__init__(message)
        self.lineno = lineno
        self.col = col


# ---------------------------------------------------------------------------
# Funzioni helper pure (non metodi)
# ---------------------------------------------------------------------------

def _is_none_annotation(node: ast.expr) -> bool:
    """True se l'annotation è `None` o `-> None`."""
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Name) and node.id == "None":
        return True
    return False


def _is_range_call(node: ast.expr) -> bool:
    """True se il nodo è una chiamata a `range(...)`."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
    )


def _constant_to_rust(node: ast.Constant) -> str:
    """Converte una costante Python nel letterale Rust equivalente."""
    val = node.value
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return str(val)
    if isinstance(val, float):
        s = str(val)
        # Rust vuole sempre un punto decimale per i float
        return s if "." in s else s + ".0"
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if val is None:
        return "None"
    return f"/* constant: {val!r} */"


def _fstring_parts(node: ast.JoinedStr) -> tuple[str, list[str]]:
    """Estrai formato e argomenti da una f-string.

    Returns:
        fmt: stringa di formato con `{}` come placeholder
        values: lista di espressioni come stringhe Rust
    """
    fmt_parts: list[str] = []
    values: list[str] = []

    # Istanziamo un generatore temporaneo per risolvere le sotto-espressioni.
    # Usiamo un'analisi vuota perché le sotto-espressioni non hanno contesto proprio.
    from pyfast.transpiler.analyzer import AnalysisResult as _AR
    _sub = RustGenerator(_AR())

    for part in node.values:
        if isinstance(part, ast.Constant):
            text = str(part.value)
            # Escape parentesi graffe in Rust format strings
            text = text.replace("{", "{{").replace("}", "}}")
            fmt_parts.append(text)
        elif isinstance(part, ast.FormattedValue):
            fmt_parts.append("{}")
            values.append(_sub._expr(part.value))

    return "".join(fmt_parts), values


def _get_func_name(node: ast.expr) -> str:
    """Estrai il nome di una funzione da un nodo Call.func."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{node.attr}"  # metodo — usiamo solo il nome locale
    return "?"


def _binop_symbol(op: ast.operator) -> str:
    symbols = {
        ast.Add: "+",
        ast.Sub: "-",
        ast.Mult: "*",
        ast.Div: "/",
        ast.FloorDiv: "/",
        ast.Mod: "%",
    }
    return symbols.get(type(op), "/* op? */")


def _cmpop_symbol(op: ast.cmpop) -> str:
    symbols = {
        ast.Eq: "==",
        ast.NotEq: "!=",
        ast.Lt: "<",
        ast.LtE: "<=",
        ast.Gt: ">",
        ast.GtE: ">=",
    }
    return symbols.get(type(op), "/* cmp? */")


def _is_docstring(stmt: ast.stmt) -> bool:
    """True se lo statement è una docstring (Constant str come Expr standalone)."""
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _is_main_call(stmt: ast.stmt) -> bool:
    """True se lo statement è una chiamata `main()` a livello modulo.

    In Rust `fn main()` è l'entry point automatico — non serve la chiamata esplicita.
    """
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
        and stmt.value.func.id == "main"
        and not stmt.value.args
        and not stmt.value.keywords
    )
