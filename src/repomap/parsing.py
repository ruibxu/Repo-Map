"""Tree-sitter extraction independent of storage, retrieval, and generation."""

import hashlib
from pathlib import PurePosixPath

from tree_sitter import Language, Parser
import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_typescript

VERSION = "tree-sitter-0.25.2-extraction-v1"
LANGUAGES = {".py": "python", ".js": "javascript", ".jsx": "javascript",
             ".ts": "typescript", ".tsx": "tsx"}
DEFINITIONS = {"function_definition": "function", "class_definition": "class",
               "function_declaration": "function", "class_declaration": "class",
               "method_definition": "method", "interface_declaration": "interface",
               "type_alias_declaration": "type"}


def identity(*parts) -> str:
    return hashlib.sha256("\0".join(map(str, parts)).encode()).hexdigest()[:32]


def walk(node):
    yield node
    for child in node.named_children:
        yield from walk(child)


def parse(path: str, source: str) -> dict:
    language = LANGUAGES.get(PurePosixPath(path).suffix, "text")
    result = {"language": language, "symbols": [], "references": [], "imports": [], "diagnostics": []}
    if language == "text":
        return result
    capsule = {"python": tree_sitter_python.language,
               "javascript": tree_sitter_javascript.language,
               "typescript": tree_sitter_typescript.language_typescript,
               "tsx": tree_sitter_typescript.language_tsx}[language]()
    raw = source.encode("utf-8")
    root = Parser(Language(capsule)).parse(raw).root_node
    text = lambda node: raw[node.start_byte:node.end_byte].decode("utf-8") if node else ""
    position = lambda node: dict(start_byte=node.start_byte, end_byte=node.end_byte,
                                start_line=node.start_point.row + 1, end_line=node.end_point.row + 1,
                                column=node.start_point.column)
    excluded = set()

    def exclude(node):
        if node:
            excluded.update(n.id for n in walk(node))

    def visit(node, scope=None, parent_kind=None):
        if node.type == "ERROR" or node.is_missing:
            result["diagnostics"].append({"kind": "syntax-error", **position(node)})
        # Import declarations are handled as bindings, not identifier references.
        if node.type in {"import_statement", "import_from_statement", "export_statement"}:
            module = node.child_by_field_name("module_name") or node.child_by_field_name("source")
            if language == "python":
                names = node.children_by_field_name("name")
                for item in names:
                    imported = text(item.child_by_field_name("name") or item)
                    alias = text(item.child_by_field_name("alias")) or imported.split(".")[0]
                    result["imports"].append({"module": text(module) if module else imported,
                        "name": imported if module else None, "alias": alias, "scope": scope,
                        "reexport": False, **position(item)})
                exclude(node)
            elif module:
                specs = [n for n in walk(node) if n.type in {"import_specifier", "export_specifier", "namespace_import"}]
                clause = next((n for n in node.named_children if n.type == "import_clause"), None)
                if clause:
                    specs += [n for n in clause.named_children if n.type == "identifier"]
                if not specs:
                    result["imports"].append({"module": text(module).strip("\"'"), "name": None,
                        "alias": None, "scope": scope, "reexport": node.type == "export_statement", **position(node)})
                for item in specs:
                    name_node = item.child_by_field_name("name")
                    imported = text(name_node) if name_node else ("*" if item.type == "namespace_import" else "default")
                    alias_node = item.child_by_field_name("alias") or name_node
                    alias = text(alias_node) if alias_node else text(item.named_children[-1] if item.type == "namespace_import" else item)
                    result["imports"].append({"module": text(module).strip("\"'"), "name": imported,
                        "alias": alias, "scope": scope, "reexport": node.type == "export_statement", **position(item)})
                exclude(module)
                for item in specs:
                    exclude(item)

        kind = DEFINITIONS.get(node.type)
        name_node = node.child_by_field_name("name") if kind else None
        if node.type == "variable_declarator":
            value = node.child_by_field_name("value")
            if value and value.type in {"arrow_function", "function_expression"}:
                kind, name_node = "function", node.child_by_field_name("name")
        next_scope = scope
        if kind and name_node:
            name = text(name_node)
            if language == "python" and kind == "function" and parent_kind == "class":
                kind = "method"
            symbol_id = identity(path, node.start_byte, kind, name)
            parent = next((s for s in result["symbols"] if s["id"] == scope), None)
            body = node.child_by_field_name("body")
            if node.type == "variable_declarator":
                body = node.child_by_field_name("value")
            parameters = node.child_by_field_name("parameters")
            if node.type == "variable_declarator":
                parameters = body.child_by_field_name("parameters") or body.child_by_field_name("parameter")
            locals_ = [text(n) for n in walk(parameters) if n.type == "identifier"] if parameters else []
            # Assignments are shadowing barriers; full type inference is intentionally absent.
            if body:
                for n in walk(body):
                    target = n.child_by_field_name("left") if n.type in {"assignment", "augmented_assignment"} else n.child_by_field_name("name") if n.type == "variable_declarator" else None
                    if target and target.type == "identifier":
                        locals_.append(text(target))
            result["symbols"].append({"id": symbol_id, "name": name,
                "qualified_name": f"{parent['qualified_name']}.{name}" if parent else name,
                "kind": kind, "scope": scope, "locals": sorted(set(locals_)),
                "signature": raw[node.start_byte:body.start_byte].decode("utf-8").strip() if body else text(node).splitlines()[0],
                "exported": language == "python" and not name.startswith("_") or node.parent is not None and node.parent.type == "export_statement",
                **position(node)})
            exclude(name_node)
            exclude(parameters)
            next_scope = symbol_id
        if node.type in {"identifier", "property_identifier", "type_identifier"} and node.id not in excluded:
            parent = node.parent
            member = parent is not None and parent.type in {"attribute", "member_expression"}
            function = parent.child_by_field_name("function") if parent and parent.type in {"call", "call_expression"} else None
            member_call = member and parent.parent and parent.parent.type in {"call", "call_expression"}
            result["references"].append({"name": text(node), "scope": scope,
                "role": "call" if function == node or member_call else "reference",
                "member": bool(member), "status": "unresolved", "target": None, "candidates": [], **position(node)})
        for child in node.named_children:
            visit(child, next_scope, kind or parent_kind)

    visit(root)
    return result
