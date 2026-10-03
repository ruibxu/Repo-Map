import json
import subprocess

import pytest

from repomap.binding import bind
from repomap.indexing import Indexer, IndexStore, TaskManager
from repomap.parsing import parse
from repomap.repositories import RepositoryCatalog


def corpus(sources):
    return {path: {"content": source, "parsed": parse(path, source)} for path, source in sources.items()}


def test_python_alias_and_parameter_shadowing():
    files = corpus({"pkg/auth.py": "def login():\n    return True\n",
                    "pkg/main.py": "from .auth import login as sign_in\ndef run():\n    return sign_in()\ndef shadow(sign_in):\n    return sign_in()\n"})
    edges = bind(files)
    calls = [r for r in files["pkg/main.py"]["parsed"]["references"] if r["name"] == "sign_in"]
    assert [r["status"] for r in calls] == ["resolved", "unresolved"]
    assert any(e["kind"] == "call" and e["target_path"] == "pkg/auth.py" for e in edges)


def test_typescript_alias_paths_and_reexport():
    files = corpus({"src/auth.ts": "export function login() { return true; }",
                    "src/index.ts": "export { login as authenticate } from './auth';",
                    "src/main.ts": "import { authenticate as signIn } from '@app/index'; export const run = () => signIn();"})
    bind(files, {"baseUrl": ".", "paths": {"@app/*": ["src/*"]}})
    ref = next(r for r in files["src/main.ts"]["parsed"]["references"] if r["name"] == "signIn")
    assert ref["status"] == "resolved"


@pytest.mark.parametrize("extension", ["js", "jsx", "ts", "tsx"])
def test_javascript_variants_and_ambiguous_members(extension):
    files = corpus({f"app.{extension}": "function login() { return true; } function run(obj) { return obj.login(); }"})
    bind(files)
    refs = files[f"app.{extension}"]["parsed"]["references"]
    assert all(r["status"] != "resolved" for r in refs if r["name"] == "login")


def test_unicode_offsets_and_syntax_diagnostics():
    source = "# café\ndef good():\n    return 1\ndef broken(\n"
    parsed = parse("a.py", source)
    good = next(s for s in parsed["symbols"] if s["name"] == "good")
    assert source.encode()[good["start_byte"]:good["end_byte"]].decode().startswith("def good")
    assert good["start_line"] == 2
    assert parsed["diagnostics"]


@pytest.fixture
def indexed_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=t@example.invalid", "commit", "-m", "fixture"], check=True, capture_output=True)
    catalog = RepositoryCatalog(tmp_path / "data")
    repository = catalog.import_repository("local", str(root))
    return root, repository, IndexStore(catalog)


def test_captured_sources_are_immutable_and_cached(indexed_repo):
    root, repository, store = indexed_repo
    indexer = Indexer(store)
    first = indexer.run(repository["id"])
    second = indexer.run(repository["id"])
    assert store.snapshots(repository["id"])[0]["metrics"]["parse_cache_hits"] == 1
    (root / "auth.py").write_text("def logout():\n    pass\n")
    third = indexer.run(repository["id"])
    assert "login" in store.source(first, "auth.py")["content"]
    assert "logout" in store.source(third, "auth.py")["content"]
    assert first != second != third
    with pytest.raises(ValueError, match="fully indexed"):
        store.require(repository["id"], third)


def test_restart_marks_interrupted_tasks_failed(indexed_repo):
    _, repository, store = indexed_repo
    with store.catalog.connect() as db:
        db.execute("INSERT INTO tasks VALUES ('old',?,NULL,'running',0.2,NULL,0)", (repository["id"],))
    manager = TaskManager(Indexer(store))
    try:
        assert manager.get("old")["status"] == "failed"
    finally:
        manager.close()


def test_deletion_and_exclusion_reasons(indexed_repo):
    root, repository, store = indexed_repo
    (root / "auth.py").unlink()
    (root / "data.bin").write_bytes(b"\0binary")
    (root / "generated.py").write_text("# @generated\npass\n")
    subprocess.run(["git", "-C", str(root), "add", "data.bin", "generated.py"], check=True)
    Indexer(store).run(repository["id"])
    skipped = store.snapshots(repository["id"])[0]["metrics"]["skipped"]
    assert {r["reason"] for r in skipped} == {"deleted-or-non-file", "binary", "generated"}


def test_ambiguous_definitions_remain_candidates():
    files = corpus({"a.py": "def f():\n    pass\ndef f():\n    pass\nf()\n"})
    bind(files)
    ref = files["a.py"]["parsed"]["references"][-1]
    assert ref["status"] == "candidate"
    assert len(ref["candidates"]) == 2


def test_default_and_local_export_aliases_do_not_bind_other_symbols():
    files = corpus({"a.ts": "export default function first(){} export function second(){} const run=()=>1; export {run as action};",
                    "b.ts": "import defaultFn, { action } from './a'; defaultFn(); action();"})
    bind(files)
    references = {r["name"]: r for r in files["b.ts"]["parsed"]["references"]}
    symbols = {s["id"]: s["name"] for s in files["a.ts"]["parsed"]["symbols"]}
    assert symbols[references["defaultFn"]["target"]] == "first"
    assert symbols[references["action"]["target"]] == "run"


def test_assigned_javascript_functions_have_qualified_names():
    parsed = parse("app.js", "app.handle = function handle(req) { return req; };")
    assert parsed["symbols"][0]["qualified_name"] == "app.handle"


def test_explicit_imported_module_members_and_commonjs_edges():
    files = corpus({"auth.py": "def login():\n    return True\n", "main.py": "import auth\nauth.login()\n",
                    "auth.js": "function login(){return true;} exports.login=login;",
                    "main.js": "const auth=require('./auth'); auth.login();"})
    edges = bind(files)
    for path in ("main.py", "main.js"):
        reference = next(r for r in files[path]["parsed"]["references"] if r["name"] == "login")
        assert reference["status"] == "resolved"
    assert any(e["kind"] == "import" and e["source_path"] == "main.js" for e in edges)


def test_anonymous_parameter_and_reassignment_are_not_false_bindings():
    files = corpus({"a.py": "def login():\n    return True\ncallback = lambda login: login()\nlogin = unknown\nlogin()\n"})
    bind(files)
    refs = [r for r in files["a.py"]["parsed"]["references"] if r["name"] == "login"]
    assert all(r["status"] != "resolved" for r in refs)


def test_namespace_is_a_scope():
    parsed = parse("parser.ts", "namespace Parser { export function parse() { return true; } }")
    assert any(s["qualified_name"] == "Parser.parse" for s in parsed["symbols"])


def test_syntax_error_regions_cannot_create_definite_references():
    files = corpus({"broken.py": "def login():\n    return True\n\nlogin ??? invalid\n"})
    bind(files)
    parsed = files["broken.py"]["parsed"]
    assert parsed["diagnostics"]
    for diagnostic in parsed["diagnostics"]:
        assert not any(diagnostic["start_byte"] <= ref["start_byte"] < diagnostic["end_byte"] for ref in parsed["references"])
    assert any(symbol["name"] == "login" for symbol in parsed["symbols"])


def test_reexport_cycles_preserve_distinct_exports_for_repeated_lookups():
    files = corpus({
        "a.ts": "export function first() {} export * from './b';",
        "b.ts": "export function second() {} export * from './a';",
        "main.ts": "import {first, second} from './a'; first(); second(); first(); second();",
    })
    bind(files)
    calls = [ref for ref in files["main.ts"]["parsed"]["references"] if ref["role"] == "call"]
    assert len(calls) == 4
    assert all(ref["status"] == "resolved" for ref in calls)
    assert calls[0]["target"] == calls[2]["target"] != calls[1]["target"] == calls[3]["target"]
