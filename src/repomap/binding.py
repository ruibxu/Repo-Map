"""Conservative lexical and import binding across a captured source corpus."""

import posixpath
import re


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
    symbols = {s["id"]: (path, s) for path, file in files.items() for s in file["parsed"]["symbols"]}
    edges = []

    def exported(path, name, seen=None):
        seen = set() if seen is None else seen
        if (path, name) in seen:
            return []
        seen.add((path, name))
        parsed = files[path]["parsed"]
        found = [s["id"] for s in parsed["symbols"] if s["scope"] is None and name in s.get("export_names", [])]
        for imp in parsed["imports"]:
            if imp["reexport"] and (imp["alias"] == name or imp["name"] is None):
                target = resolve_module(path, imp["module"], parsed["language"], files, tsconfig)
                if target:
                    found += exported(target, imp["name"] or name, seen)
        return list(dict.fromkeys(found))

    for path, file in files.items():
        parsed = file["parsed"]
        for imp in parsed["imports"]:
            target = resolve_module(path, imp["module"], parsed["language"], files, tsconfig)
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
            while not blocked:
                if any(b["name"] == lookup and b["scope"] == scope for b in parsed.get("barriers", [])):
                    break
                if scope is not None and lookup in symbols[scope][1]["locals"]:
                    break
                candidates = [s["id"] for s in parsed["symbols"] if s["scope"] == scope and s["name"] == lookup] if not ref["member"] else []
                if candidates:
                    break
                imports = [imp for imp in parsed["imports"] if imp["scope"] == scope and (imp["alias"] == lookup or ref["member"] and imp["module"] == lookup and imp["name"] is None) and not imp["reexport"]]
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
                if lookup in symbol["locals"]:
                    blocked = True
                    break
                scope = symbol["scope"]
            ref["candidates"] = sorted(set(candidates))
            ref["status"] = "resolved" if len(ref["candidates"]) == 1 else "candidate" if candidates else "unresolved"
            ref["target"] = ref["candidates"][0] if ref["status"] == "resolved" else None
            if ref["role"] == "call" and ref["target"]:
                edges.append({"kind": "call", "source_path": path, "target_path": symbols[ref["target"]][0],
                    "source_symbol": ref["scope"], "target_symbol": ref["target"], "status": "resolved"})
    return edges
