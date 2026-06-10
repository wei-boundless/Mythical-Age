import ast
import json
import re
from pathlib import Path

# ---------- config ----------
EXCLUDE_DIR_NAMES = {"__pycache__", "node_modules", ".next", ".git", "venv", ".venv", "migrations", "test"}
PYTHON_ROOTS = [
    Path("D:/AI应用/langchain-agent/backend/runtime"),
    Path("D:/AI应用/langchain-agent/backend/task_system"),
    Path("D:/AI应用/langchain-agent/backend/agent_system"),
    Path("D:/AI应用/langchain-agent/backend/memory_system"),
    Path("D:/AI应用/langchain-agent/backend/prompt_composition"),
    Path("D:/AI应用/langchain-agent/backend/api"),
]
FRONTEND_ROOT = Path("D:/AI应用/langchain-agent/frontend/src")
OUTPUT_PATH = Path("mythical-agent/sessions/session-23803172d7a64356/environments/general/workspace/artifacts/quality_findings.json")

findings = {
    "naming": [],
    "error_handling": [],
    "type_safety": [],
    "duplicate_code": [],
    "dead_code": [],
}

all_py_files_content = {}
all_py_imported_names = {}
all_py_function_names = {}

def should_exclude(path: Path):
    return any(part in EXCLUDE_DIR_NAMES for part in path.parts)

def is_snake_case(name):
    if name.startswith("_"):
        name = name.lstrip("_")
    if name == "":
        return True
    return re.fullmatch(r'[a-z][a-z0-9_]*', name) is not None

def is_camel_case(name):
    if name.startswith("_"):
        name = name.lstrip("_")
    return re.fullmatch(r'[a-z]+[A-Za-z0-9]*', name) is not None

def is_pascal_case(name):
    if name.startswith("_"):
        name = name.lstrip("_")
    return re.fullmatch(r'[A-Z][a-zA-Z0-9]*', name) is not None

def add(dim, file, line, severity, msg):
    findings.setdefault(dim, []).append({
        "file": str(Path(file).as_posix()),
        "line": line,
        "severity": severity,
        "message": msg,
    })

def _check_naming_python(file_path, tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if not is_pascal_case(node.name):
                add("naming", file_path, node.lineno, "medium", f"Class '{node.name}' not PascalCase")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            if not is_snake_case(node.name):
                add("naming", file_path, node.lineno, "low", f"Function '{node.name}' not snake_case")

def _check_error_handling_python(file_path, tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                add("error_handling", file_path, node.lineno, "high", "Bare except clause (no exception type)")
            elif isinstance(node.type, ast.Name) and node.type.id == "Exception":
                add("error_handling", file_path, node.lineno, "medium", "Catches general Exception, consider more specific")

def _check_type_safety_python(file_path, tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("__") and node.name.endswith("__"):
                continue
            for arg in node.args.args:
                if arg.arg == "self":
                    continue
                if arg.annotation is None:
                    add("type_safety", file_path, node.lineno, "low", f"Missing type annotation for argument '{arg.arg}' in function '{node.name}'")
            if node.returns is None:
                add("type_safety", file_path, node.lineno, "low", f"Missing return type annotation for function '{node.name}'")

def analyze_python_file(file_path: Path):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            source = f.read()
        tree = ast.parse(source, filename=str(file_path))
        all_py_files_content[str(file_path)] = (source, tree)
        _file_imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name.split('.')[0]
                    _file_imported_names.add(name)
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None:
                    for alias in node.names:
                        name = alias.asname if alias.asname else alias.name
                        _file_imported_names.add(name)
        all_py_imported_names[str(file_path)] = _file_imported_names
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                key = f"{file_path.stem}.{node.name}"
                all_py_function_names[key] = (file_path, node.lineno)
            elif isinstance(node, ast.ClassDef):
                key = f"{file_path.stem}.{node.name}"
                all_py_function_names[key] = (file_path, node.lineno)
        _check_naming_python(file_path, tree)
        _check_error_handling_python(file_path, tree)
        _check_type_safety_python(file_path, tree)
    except Exception as e:
        add("error_handling", file_path, 0, "low", f"Parse failed: {e}")

def analyze_all_python():
    for root in PYTHON_ROOTS:
        if not root.exists():
            continue
        for py_file in root.rglob("*.py"):
            if should_exclude(py_file):
                continue
            analyze_python_file(py_file)

def detect_unused_imports():
    global_ignore = {"__builtins__", "__name__", "__doc__", "__package__"}
    for file_path, (source, tree) in all_py_files_content.items():
        imported_names = all_py_imported_names.get(file_path, set())
        if not imported_names:
            continue
        used_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                used_names.add(node.value.id)
        unused = imported_names - used_names - global_ignore
        if not unused:
            continue
        # locate line
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name.split('.')[0]
                    if name in unused:
                        add("dead_code", file_path, node.lineno, "low", f"Unused import '{name}'")
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    if name in unused:
                        add("dead_code", file_path, node.lineno, "low", f"Unused import '{name}'")

def detect_duplicate_code():
    body_map = {}
    for file_path, (source, tree) in all_py_files_content.items():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                try:
                    body_text = ast.unparse(node)
                except Exception:
                    continue
                normalized = re.sub(r'\s+', ' ', body_text).strip()
                if len(normalized) < 30:
                    continue
                if normalized in body_map:
                    prev_file, prev_line = body_map[normalized]
                    add("duplicate_code", file_path, node.lineno, "medium", f"Duplicate of function in {prev_file} line {prev_line}")
                else:
                    body_map[normalized] = (file_path, node.lineno)

def detect_dead_functions():
    function_refs = {key: 0 for key in all_py_function_names}
    for file_path, (source, tree) in all_py_files_content.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                simple = node.id
                for key in all_py_function_names:
                    if key.endswith(f".{simple}"):
                        function_refs[key] = function_refs.get(key, 0) + 1
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                simple = node.func.id
                for key in all_py_function_names:
                    if key.endswith(f".{simple}"):
                        function_refs[key] = function_refs.get(key, 0) + 1
    for key, (file_path, line) in all_py_function_names.items():
        if function_refs.get(key, 0) == 0:
            simple = key.split('.')[-1]
            add("dead_code", file_path, line, "low", f"Potentially unused function/class '{simple}' (no direct name reference found)")

def analyze_typescript_file(file_path: Path):
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.search(r'\bcatch\s*\(', stripped) and 'any' not in line.lower() and not re.search(r':\s*\w+Error\b', stripped):
            add("error_handling", file_path, i+1, "low", "Catch block may be too broad")
        if re.search(r':\s*any\b', stripped) and not re.search(r'//\s*.*any', stripped.lower()):
            add("type_safety", file_path, i+1, "medium", "Use of 'any' type")
        # naming
        match = re.match(r'export\s+(const|let|var)\s+([A-Z_]+)\s*[=:]', stripped)
        if match:
            name = match.group(2)
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*', name):
                add("naming", file_path, i+1, "low", f"Constant/variable '{name}' should be camelCase or UPPER_CASE")
        match = re.match(r'export\s+function\s+([a-zA-Z_][\w$]*)', stripped)
        if match:
            name = match.group(1)
            if not is_camel_case(name) and not is_pascal_case(name):
                add("naming", file_path, i+1, "low", f"Function '{name}' should follow camelCase or PascalCase")
        match = re.match(r'export\s+class\s+([A-Z][\w$]*)', stripped)
        if match:
            name = match.group(1)
            if not is_pascal_case(name):
                add("naming", file_path, i+1, "low", f"Class '{name}' should PascalCase")

def analyze_all_typescript():
    if not FRONTEND_ROOT.exists():
        return
    for ext in ['*.ts', '*.tsx']:
        for file in FRONTEND_ROOT.rglob(ext):
            if should_exclude(file):
                continue
            analyze_typescript_file(file)

def main():
    analyze_all_python()
    detect_unused_imports()
    detect_duplicate_code()
    detect_dead_functions()
    analyze_all_typescript()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as out:
        json.dump(findings, out, indent=2, ensure_ascii=False)
    print(f"Quality findings written to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()