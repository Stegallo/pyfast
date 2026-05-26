"""Mappatura tipi Python → Rust.

Tabella di riferimento dal design doc:
  int           → i64
  float         → f64
  bool          → bool
  str (letterale)  → &str
  str (runtime)    → String
  Optional[T]   → Option<T>
  list[T]       → Vec<T>
  dict[K, V]    → HashMap<K, V>
  tuple[A, B]   → (A, B)
  None / ()     → ()
"""

import ast

# Tipi scalari: mapping diretto
SCALAR_TYPES: dict[str, str] = {
    "int": "i64",
    "float": "f64",
    "bool": "bool",
}


def annotation_to_rust(node: ast.expr, owned_str: bool = False) -> str:
    """Converti un nodo annotation AST nel tipo Rust corrispondente.

    Args:
        node: Nodo AST dell'annotation (ast.Name, ast.Subscript, ...).
        owned_str: Se True, le stringhe `str` vengono mappate a `String`
                   invece di `&str` (usato per variabili costruite a runtime).
    """
    # Sintassi union Python 3.10+: `T | None` e `None | T` → Option<T>
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left, right = node.left, node.right
        if _is_none_node(right):
            inner = annotation_to_rust(left, owned_str=owned_str)
            return f"Option<{inner}>"
        if _is_none_node(left):
            inner = annotation_to_rust(right, owned_str=owned_str)
            return f"Option<{inner}>"
        # Union di due tipi non-None — non supportato
        return f"/* unsupported union type: {ast.unparse(node)} */"

    if isinstance(node, ast.Name):
        name = node.id
        if name == "str":
            return "String" if owned_str else "&str"
        if name == "None":
            return "()"
        return SCALAR_TYPES.get(name, name)

    if isinstance(node, ast.Constant):
        # annotazioni letterali come None
        if node.value is None:
            return "()"
        return str(node.value)

    if isinstance(node, ast.Subscript):
        outer_name = _get_name(node.value)

        if outer_name == "Optional":
            inner = annotation_to_rust(_unwrap_slice(node), owned_str=owned_str)
            return f"Option<{inner}>"

        if outer_name == "list":
            inner = annotation_to_rust(_unwrap_slice(node), owned_str=owned_str)
            return f"Vec<{inner}>"

        if outer_name == "dict":
            slice_node = _unwrap_slice(node)
            if isinstance(slice_node, ast.Tuple) and len(slice_node.elts) == 2:
                k = annotation_to_rust(slice_node.elts[0], owned_str=False)
                v = annotation_to_rust(slice_node.elts[1], owned_str=owned_str)
                return f"HashMap<{k}, {v}>"
            return "HashMap<_, _>"

        if outer_name == "tuple":
            slice_node = _unwrap_slice(node)
            if isinstance(slice_node, ast.Tuple):
                elems = ", ".join(annotation_to_rust(e, owned_str=owned_str) for e in slice_node.elts)
                return f"({elems})"
            inner = annotation_to_rust(slice_node, owned_str=owned_str)
            return f"({inner},)"

        if outer_name == "Result":
            slice_node = _unwrap_slice(node)
            if isinstance(slice_node, ast.Tuple) and len(slice_node.elts) == 2:
                ok = annotation_to_rust(slice_node.elts[0], owned_str=owned_str)
                err = annotation_to_rust(slice_node.elts[1], owned_str=False)
                return f"Result<{ok}, {err}>"

    # fallback
    return f"/* unsupported type: {ast.unparse(node)} */"


def _is_none_node(node: ast.expr) -> bool:
    """True se il nodo rappresenta None come annotazione di tipo."""
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Name) and node.id == "None":
        return True
    return False


def _get_name(node: ast.expr) -> str:
    """Estrai il nome da un nodo ast.Name o ast.Attribute."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _unwrap_slice(node: ast.Subscript) -> ast.expr:
    """Estrai il nodo slice (compatibile Python 3.9+)."""
    return node.slice
