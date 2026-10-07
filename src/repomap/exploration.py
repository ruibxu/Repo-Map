"""Snapshot-bound source browsing, definitions, references, and graph neighbors."""

from pathlib import PurePosixPath


class Explorer:
    def __init__(self, store):
        self.store = store

    def context(self, repository_id, snapshot_id):
        self.store.require(repository_id, snapshot_id)
        return {"repository_id": repository_id, "snapshot_id": snapshot_id}

    def file(self, repository_id, snapshot_id, path, start_line=1, end_line=None):
        context = self.context(repository_id, snapshot_id)
        if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts or "\\" in path:
            raise ValueError("Use a repository-relative POSIX path.")
        # Read captured source from SQLite, never the live working tree.
        file = self.store.source(snapshot_id, path)
        lines = file["content"].splitlines()
        if not lines and start_line == 1 and end_line is None:
            return {**context, "path": path, "language": file["language"], "start_line": 1,
                    "end_line": 0, "content": "", "total_lines": 0, "content_hash": file["content_hash"]}
        end_line = len(lines) if end_line is None else end_line
        if start_line < 1 or end_line < start_line or end_line > max(1, len(lines)):
            raise ValueError("Invalid source line range.")
        return {**context, "path": path, "language": file["language"], "start_line": start_line,
                "end_line": end_line, "content": "\n".join(lines[start_line - 1:end_line]),
                "total_lines": len(lines), "content_hash": file["content_hash"]}

    def symbols(self, repository_id, snapshot_id, path=None):
        context = self.context(repository_id, snapshot_id)
        return {**context, "symbols": [s for s in self.store.records("symbols", snapshot_id) if not path or s["path"] == path]}

    def definitions(self, repository_id, snapshot_id, symbol_id=None, path=None, line=None, column=0):
        context = self.context(repository_id, snapshot_id)
        symbols = self.store.records("symbols", snapshot_id)
        if symbol_id:
            found = [s for s in symbols if s["id"] == symbol_id]
            if not found:
                raise ValueError("Symbol not found in this snapshot.")
            return {**context, "status": "resolved", "definitions": found}
        if path is None or line is None or line < 1 or column < 0:
            raise ValueError("Provide a symbol ID or a path, 1-based line, and 0-based UTF-8 byte column.")
        content = self.store.source(snapshot_id, path)["content"]
        lines = content.splitlines(keepends=True)
        if line > len(lines) or column > len(lines[line - 1].encode()):
            raise ValueError("Source position is outside the file.")
        # Convert lines and UTF-8 byte columns into Tree-sitter coordinates,
        # including non-ASCII identifiers.
        byte = sum(len(text.encode()) for text in lines[:line - 1]) + column
        references = [r for r in self.store.records("refs", snapshot_id) if r["path"] == path and r["start_byte"] <= byte < r["end_byte"]]
        if references:
            ref = min(references, key=lambda r: r["end_byte"] - r["start_byte"])
            return {**context, "status": ref["status"], "reference": ref,
                    "definitions": [s for s in symbols if s["id"] in ref["candidates"]]}
        containing = [s for s in symbols if s["path"] == path and s["start_byte"] <= byte < s["end_byte"]]
        found = sorted(containing, key=lambda s: s["end_byte"] - s["start_byte"])[:1]
        return {**context, "status": "resolved" if found else "unresolved", "definitions": found}

    def references(self, repository_id, snapshot_id, symbol_id=None, path=None, line=None, column=0):
        definition = self.definitions(repository_id, snapshot_id, symbol_id, path, line, column)
        targets = {s["id"] for s in definition["definitions"]}
        refs = [r for r in self.store.records("refs", snapshot_id) if targets.intersection(r["candidates"])]
        return {**definition, "references": refs}

    def graph(self, repository_id, snapshot_id, path=None, symbol_id=None, limit=100):
        context = self.context(repository_id, snapshot_id)
        if not path and not symbol_id:
            raise ValueError("Select a file or symbol for graph exploration.")
        symbols = {s["id"]: s for s in self.store.records("symbols", snapshot_id)}
        if symbol_id and symbol_id not in symbols:
            raise ValueError("Symbol not found in this snapshot.")
        if path:
            self.store.source(snapshot_id, path)
        edges = self.store.records("edges", snapshot_id)
        selected = [e for e in edges if (symbol_id and symbol_id in {e["source_symbol"], e["target_symbol"]}) or (not symbol_id and path in {e["source_path"], e["target_path"]})]
        nodes = {}

        def node(path, symbol, external=None):
            key = "symbol:" + symbol if symbol else "file:" + path if path else "external:" + str(external)
            nodes[key] = {"id": key, "path": path, "symbol_id": symbol,
                          "label": symbols[symbol]["qualified_name"] if symbol in symbols else path or external,
                          "external": path is None}
            return key

        node(symbols[symbol_id]["path"] if symbol_id else path, symbol_id)
        output = []
        for edge in selected[:limit]:
            output.append({**edge, "source": node(edge["source_path"], edge["source_symbol"]),
                           "target": node(edge["target_path"], edge["target_symbol"], edge.get("external_module"))})
        return {**context, "nodes": list(nodes.values()), "edges": output, "truncated": len(selected) > limit}
