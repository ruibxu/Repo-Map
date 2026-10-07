"""Conservative lexical and import binding across a captured source corpus."""

import posixpath
import re
from collections import defaultdict


def resolve_module(path, module, language, files, tsconfig=None):
    if language == "python":
        dots = len(module) - len(module.lstrip("."))
        suffix = module[dots:].replace(".", "/")
        prefix = posixpath.dirname(path) if dots else ""
        for _ in range(max(0, dots - 1)):
            prefix = posixpath.dirname(prefix)
        base = posixpath.join(prefix, suffix)
        candidates = [base + ".py", posixpath.join(base, "__init__.py")]
        if not dots:
            candidates += ["src/" + candidate for candidate in candidates]
    else:
        bases = []
        if module.startswith("."):
            bases.append(posixpath.normpath(posixpath.join(posixpath.dirname(path), module)))
        config = tsconfig or {}
        for pattern, values in config.get("paths", {}).items():
            expression = "^" + re.escape(pattern).replace(r"\*", "(.*)") + "$"
            match = re.match(expression, module)
            if match:
                for value in values:
                    bases.append(posixpath.normpath(posixpath.join(config.get("baseUrl", ""), value.replace("*", match.group(1) if match.groups() else ""))))
        candidates = []
        for base in bases:
            candidates.append(base)
            if base.endswith(".js"):
                candidates += [base[:-3] + ".ts", base[:-3] + ".tsx"]
            candidates += [base + ext for ext in (".ts", ".tsx", ".js", ".jsx")]
            candidates += [posixpath.join(base, "index" + ext) for ext in (".ts", ".tsx", ".js", ".jsx")]
    return next((candidate for candidate in candidates if candidate in files), None)


def bind(files: dict, tsconfig=None) -> list[dict]:
    # Index names by lexical scope: identical names in unrelated functions
    # must not become evidence for each other.
    symbols = {s["id"]: (path, s) for path, file in files.items() for s in file["parsed"]["symbols"]}
    edges = []
    scope_symbols, scope_imports, barriers, exports, reexports = (defaultdict(list) for _ in range(5))
    locals_by_symbol = {id_: set(symbol["locals"]) for id_, (_, symbol) in symbols.items()}
    module_cache, export_cache = {}, {}
    for path, file in files.items():
        parsed = file["parsed"]
        for symbol in parsed["symbols"]:
            scope_symbols[path, symbol["scope"], symbol["name"]].append(symbol["id"])
            if symbol["scope"] is None:
                for name in symbol.get("export_names", []):
                    exports[path, name].append(symbol["id"])
        for barrier in parsed.get("barriers", []):
            barriers[path, barrier["scope"], barrier["name"]].append(True)
        for imp in parsed["imports"]:
            if imp["reexport"]:
                reexports[path].append(imp)
            else:
                scope_imports[path, imp["scope"]].append(imp)

    def module(path, name, language):
        key = path, name, language
        if key not in module_cache:
            module_cache[key] = resolve_module(path, name, language, files, tsconfig)
        return module_cache[key]

    def exported(path, name, seen=None):
        # Guard re-export cycles per traversal. Cache complete root lookups only;
        # cycle-shortened recursive answers may be incomplete.
        root = seen is None
        if root and (path, name) in export_cache:
            return export_cache[path, name]
        seen = set() if seen is None else seen
        if (path, name) in seen:
            return []
        seen.add((path, name))
        parsed = files[path]["parsed"]
        found = list(exports[path, name])
        for imp in reexports[path]:
            if imp["reexport"] and (imp["alias"] == name or imp["name"] is None):
                target = module(path, imp["module"], parsed["language"])
                if target:
                    found += exported(target, imp["name"] or name, seen)
        found = list(dict.fromkeys(found))
        if root:
            export_cache[path, name] = found
        return found

    for path, file in files.items():
        parsed = file["parsed"]
        for imp in parsed["imports"]:
            target = module(path, imp["module"], parsed["language"])
            imp["target_path"] = target
            edges.append({"kind": "import", "source_path": path, "target_path": target,
                          "source_symbol": imp["scope"], "target_symbol": None,
                          "external_module": None if target else imp["module"],
                          "status": "resolved" if target else "unresolved"})
        for symbol in parsed["symbols"]:
            if symbol["scope"]:
                edges.append({"kind": "contains", "source_path": path, "target_path": path,
                    "source_symbol": symbol["scope"], "target_symbol": symbol["id"], "status": "resolved"})
        for ref in parsed["references"]:
            candidates = []
            scope = ref["scope"]
            blocked = False
            lookup = ref.get("member_base") if ref["member"] else ref["name"]
            # Walk outward until a local binding, reassignment, symbol, or import
            # determines the lookup. Unknown member access stays unresolved.
            while not blocked:
                if barriers[path, scope, lookup]:
                    break
                if scope is not None and lookup in locals_by_symbol[scope]:
                    break
                candidates = list(scope_symbols[path, scope, lookup]) if not ref["member"] else []
                if candidates:
                    break
                imports = [imp for imp in scope_imports[path, scope] if imp["alias"] == lookup or ref["member"] and imp["module"] == lookup and imp["name"] is None]
                if imports:
                    for imp in imports:
                        if imp["target_path"]:
                            if ref["member"] and imp["name"] in {None, "*"}:
                                candidates += exported(imp["target_path"], ref["name"])
                            elif not ref["member"] and imp["name"] not in {None, "*"}:
                                candidates += exported(imp["target_path"], imp["name"])
                    break
                if scope is None:
                    break
                symbol = symbols[scope][1]
                if lookup in locals_by_symbol[scope]:
                    blocked = True
                    break
                scope = symbol["scope"]
            # Only a unique supported binding becomes a definite call edge.
            # Preserve alternatives for definition/reference inspection.
            ref["candidates"] = sorted(set(candidates))
            ref["status"] = "resolved" if len(ref["candidates"]) == 1 else "candidate" if candidates else "unresolved"
            ref["target"] = ref["candidates"][0] if ref["status"] == "resolved" else None
            if ref["role"] == "call" and ref["target"]:
                edges.append({"kind": "call", "source_path": path, "target_path": symbols[ref["target"]][0],
                    "source_symbol": ref["scope"], "target_symbol": ref["target"], "status": "resolved"})
    return edges
