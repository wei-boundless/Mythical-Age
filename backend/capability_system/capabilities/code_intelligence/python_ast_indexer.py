from __future__ import annotations

import ast
import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any


SCHEMA_VERSION = "python_file_module_ast_index.v1"


@dataclass(frozen=True, slots=True)
class AstAnchor:
    anchor_id: str
    file_ref: str
    node_kind: str
    name: str = ""
    qualname: str = ""
    parent_anchor_id: str = ""
    stable_ast_path: str = ""
    start_line: int = 0
    end_line: int = 0
    start_col: int = 0
    end_col: int = 0
    text_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class ParameterCard:
    name: str
    kind: str
    annotation: str = ""
    default: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _drop_empty(asdict(self))


@dataclass(frozen=True, slots=True)
class FunctionEndpointCard:
    anchor: AstAnchor
    kind: str
    parameters: tuple[ParameterCard, ...] = ()
    decorators: tuple[str, ...] = ()
    returns_annotation: str = ""
    signature: str = ""
    docstring: str = ""
    call_site_anchor_ids: tuple[str, ...] = ()
    return_anchor_ids: tuple[str, ...] = ()
    assignment_anchor_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = _drop_empty(asdict(self))
        payload["anchor"] = self.anchor.to_dict()
        payload["parameters"] = [item.to_dict() for item in self.parameters]
        payload["call_site_anchor_ids"] = list(self.call_site_anchor_ids)
        payload["return_anchor_ids"] = list(self.return_anchor_ids)
        payload["assignment_anchor_ids"] = list(self.assignment_anchor_ids)
        payload["decorators"] = list(self.decorators)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ClassCard:
    anchor: AstAnchor
    bases: tuple[str, ...] = ()
    decorators: tuple[str, ...] = ()
    method_anchor_ids: tuple[str, ...] = ()
    docstring: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = _drop_empty(asdict(self))
        payload["anchor"] = self.anchor.to_dict()
        payload["bases"] = list(self.bases)
        payload["decorators"] = list(self.decorators)
        payload["method_anchor_ids"] = list(self.method_anchor_ids)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class ImportBinding:
    anchor: AstAnchor
    module: str = ""
    imported_name: str = ""
    local_name: str = ""
    level: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = _drop_empty(asdict(self))
        payload["anchor"] = self.anchor.to_dict()
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class CallSiteCard:
    anchor: AstAnchor
    scope_anchor_id: str = ""
    caller_qualname: str = ""
    callee_text: str = ""
    receiver_text: str = ""
    function_text: str = ""
    args_text: tuple[str, ...] = ()
    kwargs_text: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = _drop_empty(asdict(self))
        payload["anchor"] = self.anchor.to_dict()
        payload["args_text"] = list(self.args_text)
        payload["kwargs_text"] = dict(self.kwargs_text)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class AssignmentCard:
    anchor: AstAnchor
    scope_anchor_id: str = ""
    target_texts: tuple[str, ...] = ()
    value_text: str = ""
    assignment_kind: str = "assign"

    def to_dict(self) -> dict[str, Any]:
        payload = _drop_empty(asdict(self))
        payload["anchor"] = self.anchor.to_dict()
        payload["target_texts"] = list(self.target_texts)
        return _drop_empty(payload)


@dataclass(frozen=True, slots=True)
class FileModuleAstIndex:
    schema_version: str
    file_ref: str
    file_hash: str
    line_count: int
    module_anchor: AstAnchor | None = None
    ast_nodes: tuple[dict[str, Any], ...] = ()
    ast_edges: tuple[dict[str, Any], ...] = ()
    imports: tuple[ImportBinding, ...] = ()
    classes: tuple[ClassCard, ...] = ()
    functions: tuple[FunctionEndpointCard, ...] = ()
    call_sites: tuple[CallSiteCard, ...] = ()
    assignments: tuple[AssignmentCard, ...] = ()
    symbol_bindings: tuple[dict[str, Any], ...] = ()
    exports: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    authority: str = "capability_system.capabilities.code_intelligence.python_ast_indexer"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "file_ref": self.file_ref,
            "file_hash": self.file_hash,
            "line_count": self.line_count,
            "module_anchor": self.module_anchor.to_dict() if self.module_anchor is not None else {},
            "ast_nodes": [dict(item) for item in self.ast_nodes],
            "ast_edges": [dict(item) for item in self.ast_edges],
            "imports": [item.to_dict() for item in self.imports],
            "classes": [item.to_dict() for item in self.classes],
            "functions": [item.to_dict() for item in self.functions],
            "call_sites": [item.to_dict() for item in self.call_sites],
            "assignments": [item.to_dict() for item in self.assignments],
            "symbol_bindings": [dict(item) for item in self.symbol_bindings],
            "exports": list(self.exports),
            "limitations": list(self.limitations),
            "authority": self.authority,
        }


@dataclass(slots=True)
class _Scope:
    qualname: str
    kind: str
    anchor_id: str


class _PythonAstIndexBuilder:
    def __init__(self, *, file_ref: str, source: str) -> None:
        self.file_ref = str(file_ref or "")
        self.source = str(source or "")
        self.file_hash = hashlib.sha256(self.source.encode("utf-8", errors="ignore")).hexdigest()
        self.ast_nodes: list[dict[str, Any]] = []
        self.ast_edges: list[dict[str, Any]] = []
        self.imports: list[ImportBinding] = []
        self.classes: list[ClassCard] = []
        self.functions: list[FunctionEndpointCard] = []
        self.call_sites: list[CallSiteCard] = []
        self.assignments: list[AssignmentCard] = []
        self.symbol_bindings: list[dict[str, Any]] = []
        self.exports: list[str] = []
        self._class_method_anchor_ids: dict[str, list[str]] = {}
        self._function_calls: dict[str, list[str]] = {}
        self._function_returns: dict[str, list[str]] = {}
        self._function_assignments: dict[str, list[str]] = {}

    def build(self) -> FileModuleAstIndex:
        tree = ast.parse(self.source, filename=self.file_ref, type_comments=True)
        module_anchor = self._module_anchor()
        self._add_ast_node(module_anchor)
        self._walk_body(getattr(tree, "body", []), path="Module.body", scopes=(), parent_anchor_id=module_anchor.anchor_id)
        functions = tuple(
            FunctionEndpointCard(
                anchor=item.anchor,
                kind=item.kind,
                parameters=item.parameters,
                decorators=item.decorators,
                returns_annotation=item.returns_annotation,
                signature=item.signature,
                docstring=item.docstring,
                call_site_anchor_ids=tuple(self._function_calls.get(item.anchor.anchor_id, ())),
                return_anchor_ids=tuple(self._function_returns.get(item.anchor.anchor_id, ())),
                assignment_anchor_ids=tuple(self._function_assignments.get(item.anchor.anchor_id, ())),
            )
            for item in self.functions
        )
        classes = tuple(
            ClassCard(
                anchor=item.anchor,
                bases=item.bases,
                decorators=item.decorators,
                method_anchor_ids=tuple(self._class_method_anchor_ids.get(item.anchor.anchor_id, ())),
                docstring=item.docstring,
            )
            for item in self.classes
        )
        return FileModuleAstIndex(
            schema_version=SCHEMA_VERSION,
            file_ref=self.file_ref,
            file_hash=self.file_hash,
            line_count=len(self.source.splitlines()),
            module_anchor=module_anchor,
            ast_nodes=tuple(self.ast_nodes),
            ast_edges=tuple(self.ast_edges),
            imports=tuple(self.imports),
            classes=classes,
            functions=functions,
            call_sites=tuple(self.call_sites),
            assignments=tuple(self.assignments),
            symbol_bindings=tuple(self.symbol_bindings),
            exports=tuple(dict.fromkeys(self.exports)),
            limitations=("dynamic_import_unresolved", "runtime_dispatch_unresolved", "interprocedural_dataflow_not_computed"),
        )

    def _module_anchor(self) -> AstAnchor:
        line_count = len(self.source.splitlines())
        digest = self.file_hash[:16]
        raw_id = "|".join([self.file_ref, "module", "Module", digest])
        return AstAnchor(
            anchor_id="pyast:" + hashlib.sha256(raw_id.encode("utf-8", errors="ignore")).hexdigest()[:24],
            file_ref=self.file_ref,
            node_kind="module",
            name=self.file_ref.rsplit("/", 1)[-1],
            qualname=self.file_ref,
            stable_ast_path="Module",
            start_line=1 if line_count else 0,
            end_line=line_count,
            start_col=0,
            end_col=0,
            text_digest=digest,
        )

    def _walk_body(self, body: list[ast.stmt], *, path: str, scopes: tuple[_Scope, ...], parent_anchor_id: str) -> None:
        for index, node in enumerate(body):
            child_path = f"{path}[{index}]"
            self._walk_statement(node, path=child_path, scopes=scopes, parent_anchor_id=parent_anchor_id)

    def _walk_statement(self, node: ast.stmt, *, path: str, scopes: tuple[_Scope, ...], parent_anchor_id: str) -> None:
        if isinstance(node, ast.ClassDef):
            self._handle_class(node, path=path, scopes=scopes, parent_anchor_id=parent_anchor_id)
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._handle_function(node, path=path, scopes=scopes, parent_anchor_id=parent_anchor_id)
            return
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            self._handle_import(node, path=path, scopes=scopes, parent_anchor_id=parent_anchor_id)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            self._handle_assignment(node, path=path, scopes=scopes, parent_anchor_id=parent_anchor_id)
        if isinstance(node, ast.Return):
            self._handle_return(node, path=path, scopes=scopes, parent_anchor_id=parent_anchor_id)
        self._walk_child_nodes(node, path=path, scopes=scopes, parent_anchor_id=parent_anchor_id)

    def _walk_child_nodes(self, node: ast.AST, *, path: str, scopes: tuple[_Scope, ...], parent_anchor_id: str) -> None:
        for field_name, value in ast.iter_fields(node):
            if field_name in {"body", "orelse", "finalbody"}:
                continue
            if isinstance(value, ast.AST):
                self._walk_expression(value, path=f"{path}.{field_name}", scopes=scopes, parent_anchor_id=parent_anchor_id)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    if isinstance(child, ast.AST):
                        self._walk_expression(child, path=f"{path}.{field_name}[{index}]", scopes=scopes, parent_anchor_id=parent_anchor_id)
        for field_name in ("body", "orelse", "finalbody"):
            value = getattr(node, field_name, None)
            if isinstance(value, list):
                self._walk_body(value, path=f"{path}.{field_name}", scopes=scopes, parent_anchor_id=parent_anchor_id)

    def _walk_expression(self, node: ast.AST, *, path: str, scopes: tuple[_Scope, ...], parent_anchor_id: str) -> None:
        if isinstance(node, ast.Call):
            self._handle_call(node, path=path, scopes=scopes, parent_anchor_id=parent_anchor_id)
        for field_name, value in ast.iter_fields(node):
            if isinstance(value, ast.AST):
                self._walk_expression(value, path=f"{path}.{field_name}", scopes=scopes, parent_anchor_id=parent_anchor_id)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    if isinstance(child, ast.AST):
                        self._walk_expression(child, path=f"{path}.{field_name}[{index}]", scopes=scopes, parent_anchor_id=parent_anchor_id)

    def _handle_class(self, node: ast.ClassDef, *, path: str, scopes: tuple[_Scope, ...], parent_anchor_id: str) -> None:
        parent_qualname = scopes[-1].qualname if scopes else ""
        qualname = f"{parent_qualname}.{node.name}" if parent_qualname else node.name
        anchor = self._anchor(node, node_kind="class", name=node.name, qualname=qualname, stable_ast_path=path, parent_anchor_id=parent_anchor_id)
        self._add_ast_node(anchor)
        self._add_parent_edge(parent_anchor_id, anchor.anchor_id, "contains_class")
        self.classes.append(
            ClassCard(
                anchor=anchor,
                bases=tuple(_expr_text(base) for base in node.bases if _expr_text(base)),
                decorators=tuple(_expr_text(item) for item in node.decorator_list if _expr_text(item)),
                docstring=str(ast.get_docstring(node) or ""),
            )
        )
        self.symbol_bindings.append(_symbol_binding(self.file_ref, scopes, node.name, "class", anchor.anchor_id))
        if not scopes and not node.name.startswith("_"):
            self.exports.append(node.name)
        next_scopes = (*scopes, _Scope(qualname=qualname, kind="class", anchor_id=anchor.anchor_id))
        self._walk_body(node.body, path=f"{path}.body", scopes=next_scopes, parent_anchor_id=anchor.anchor_id)

    def _handle_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        path: str,
        scopes: tuple[_Scope, ...],
        parent_anchor_id: str,
    ) -> None:
        parent_qualname = scopes[-1].qualname if scopes else ""
        qualname = f"{parent_qualname}.{node.name}" if parent_qualname else node.name
        in_class = bool(scopes and scopes[-1].kind == "class")
        if isinstance(node, ast.AsyncFunctionDef):
            kind = "async_method" if in_class else "async_function"
        else:
            kind = "method" if in_class else "function"
        anchor = self._anchor(node, node_kind=kind, name=node.name, qualname=qualname, stable_ast_path=path, parent_anchor_id=parent_anchor_id)
        self._add_ast_node(anchor)
        self._add_parent_edge(parent_anchor_id, anchor.anchor_id, "contains_function")
        parameters = tuple(_parameter_cards(node.args))
        function_card = FunctionEndpointCard(
            anchor=anchor,
            kind=kind,
            parameters=parameters,
            decorators=tuple(_expr_text(item) for item in node.decorator_list if _expr_text(item)),
            returns_annotation=_expr_text(node.returns) if node.returns is not None else "",
            signature=_signature_text(qualname, parameters),
            docstring=str(ast.get_docstring(node) or ""),
        )
        self.functions.append(function_card)
        self.symbol_bindings.append(_symbol_binding(self.file_ref, scopes, node.name, kind, anchor.anchor_id))
        if scopes and scopes[-1].kind == "class":
            self._class_method_anchor_ids.setdefault(scopes[-1].anchor_id, []).append(anchor.anchor_id)
        if not scopes and not node.name.startswith("_"):
            self.exports.append(node.name)
        next_scopes = (*scopes, _Scope(qualname=qualname, kind="function", anchor_id=anchor.anchor_id))
        self._walk_body(node.body, path=f"{path}.body", scopes=next_scopes, parent_anchor_id=anchor.anchor_id)

    def _handle_import(self, node: ast.Import | ast.ImportFrom, *, path: str, scopes: tuple[_Scope, ...], parent_anchor_id: str) -> None:
        module = str(getattr(node, "module", "") or "")
        level = int(getattr(node, "level", 0) or 0)
        for index, alias in enumerate(node.names):
            imported_name = f"{module}.{alias.name}" if module and isinstance(node, ast.ImportFrom) else alias.name
            local_name = alias.asname or alias.name.split(".", 1)[0] if isinstance(node, ast.Import) else alias.asname or alias.name
            anchor = self._anchor(
                node,
                node_kind="import",
                name=str(local_name or imported_name),
                qualname=str(local_name or imported_name),
                stable_ast_path=f"{path}.names[{index}]",
                parent_anchor_id=parent_anchor_id,
            )
            self._add_ast_node(anchor)
            self._add_parent_edge(parent_anchor_id, anchor.anchor_id, "contains_import")
            self.imports.append(
                ImportBinding(anchor=anchor, module=module, imported_name=imported_name, local_name=local_name, level=level)
            )
            self.symbol_bindings.append(_symbol_binding(self.file_ref, scopes, local_name, "import", anchor.anchor_id))

    def _handle_assignment(self, node: ast.Assign | ast.AnnAssign | ast.AugAssign, *, path: str, scopes: tuple[_Scope, ...], parent_anchor_id: str) -> None:
        targets = list(getattr(node, "targets", [])) if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        target_texts = tuple(item for target in targets for item in _target_texts(target))
        if not target_texts:
            return
        anchor = self._anchor(node, node_kind="assignment", name=",".join(target_texts), stable_ast_path=path, parent_anchor_id=parent_anchor_id)
        self._add_ast_node(anchor)
        self._add_parent_edge(parent_anchor_id, anchor.anchor_id, "contains_assignment")
        current_function = _nearest_scope(scopes, "function")
        if current_function:
            self._function_assignments.setdefault(current_function.anchor_id, []).append(anchor.anchor_id)
        card = AssignmentCard(
            anchor=anchor,
            scope_anchor_id=scopes[-1].anchor_id if scopes else "",
            target_texts=target_texts,
            value_text=_expr_text(getattr(node, "value", None)),
            assignment_kind=type(node).__name__,
        )
        self.assignments.append(card)
        for target in target_texts:
            self.symbol_bindings.append(_symbol_binding(self.file_ref, scopes, target, "assignment", anchor.anchor_id))
        if not scopes:
            self.exports.extend(target for target in target_texts if target and not target.startswith("_"))
            self._maybe_record_all_exports(node)

    def _handle_return(self, node: ast.Return, *, path: str, scopes: tuple[_Scope, ...], parent_anchor_id: str) -> None:
        current_function = _nearest_scope(scopes, "function")
        if current_function is None:
            return
        anchor = self._anchor(node, node_kind="return", stable_ast_path=path, parent_anchor_id=parent_anchor_id)
        self._add_ast_node(anchor)
        self._add_parent_edge(parent_anchor_id, anchor.anchor_id, "contains_return")
        self._function_returns.setdefault(current_function.anchor_id, []).append(anchor.anchor_id)

    def _handle_call(self, node: ast.Call, *, path: str, scopes: tuple[_Scope, ...], parent_anchor_id: str) -> None:
        current_function = _nearest_scope(scopes, "function")
        anchor = self._anchor(node, node_kind="call_site", name=_expr_text(node.func), stable_ast_path=path, parent_anchor_id=parent_anchor_id)
        self._add_ast_node(anchor)
        self._add_parent_edge(parent_anchor_id, anchor.anchor_id, "contains_call")
        if current_function:
            self._function_calls.setdefault(current_function.anchor_id, []).append(anchor.anchor_id)
        receiver_text = _expr_text(node.func.value) if isinstance(node.func, ast.Attribute) else ""
        function_text = str(node.func.attr) if isinstance(node.func, ast.Attribute) else _expr_text(node.func)
        self.call_sites.append(
            CallSiteCard(
                anchor=anchor,
                scope_anchor_id=current_function.anchor_id if current_function else (scopes[-1].anchor_id if scopes else ""),
                caller_qualname=current_function.qualname if current_function else (scopes[-1].qualname if scopes else ""),
                callee_text=_expr_text(node.func),
                receiver_text=receiver_text,
                function_text=function_text,
                args_text=tuple(_expr_text(item) for item in node.args if _expr_text(item)),
                kwargs_text={str(keyword.arg or "**"): _expr_text(keyword.value) for keyword in node.keywords},
            )
        )

    def _maybe_record_all_exports(self, node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> None:
        targets = list(getattr(node, "targets", [])) if isinstance(node, ast.Assign) else [getattr(node, "target", None)]
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            return
        value = getattr(node, "value", None)
        if not isinstance(value, (ast.List, ast.Tuple)):
            return
        for item in value.elts:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                self.exports.append(item.value)

    def _anchor(
        self,
        node: ast.AST,
        *,
        node_kind: str,
        stable_ast_path: str,
        name: str = "",
        qualname: str = "",
        parent_anchor_id: str = "",
    ) -> AstAnchor:
        text_digest = _node_text_digest(self.source, node)
        start_line = int(getattr(node, "lineno", 0) or 0)
        end_line = int(getattr(node, "end_lineno", start_line) or start_line)
        start_col = int(getattr(node, "col_offset", 0) or 0)
        end_col = int(getattr(node, "end_col_offset", start_col) or start_col)
        raw_id = "|".join([self.file_ref, node_kind, stable_ast_path, str(start_line), str(start_col), text_digest])
        anchor_id = "pyast:" + hashlib.sha256(raw_id.encode("utf-8", errors="ignore")).hexdigest()[:24]
        return AstAnchor(
            anchor_id=anchor_id,
            file_ref=self.file_ref,
            node_kind=node_kind,
            name=str(name or ""),
            qualname=str(qualname or name or ""),
            parent_anchor_id=parent_anchor_id,
            stable_ast_path=stable_ast_path,
            start_line=start_line,
            end_line=end_line,
            start_col=start_col,
            end_col=end_col,
            text_digest=text_digest,
        )

    def _add_ast_node(self, anchor: AstAnchor) -> None:
        self.ast_nodes.append(anchor.to_dict())

    def _add_parent_edge(self, parent_anchor_id: str, child_anchor_id: str, edge_kind: str) -> None:
        if not parent_anchor_id or not child_anchor_id:
            return
        edge_key = "|".join([self.file_ref, parent_anchor_id, child_anchor_id, edge_kind])
        self.ast_edges.append(
            {
                "ast_edge_id": "pyastedge:" + hashlib.sha256(edge_key.encode("utf-8", errors="ignore")).hexdigest()[:24],
                "src_ast_node_id": parent_anchor_id,
                "dst_ast_node_id": child_anchor_id,
                "edge_kind": edge_kind,
                "confidence": "ast_exact",
            }
        )


def build_python_file_module_ast_index(*, file_ref: str, source: str) -> FileModuleAstIndex:
    return _PythonAstIndexBuilder(file_ref=file_ref, source=source).build()


def _parameter_cards(arguments: ast.arguments) -> list[ParameterCard]:
    cards: list[ParameterCard] = []
    pos_defaults = [None] * (len(arguments.posonlyargs) + len(arguments.args) - len(arguments.defaults)) + list(arguments.defaults)
    positional = [*arguments.posonlyargs, *arguments.args]
    for arg, default in zip(positional, pos_defaults):
        kind = "positional_only" if arg in arguments.posonlyargs else "positional_or_keyword"
        cards.append(_parameter_card(arg, kind=kind, default=default))
    if arguments.vararg is not None:
        cards.append(_parameter_card(arguments.vararg, kind="vararg", default=None))
    for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        cards.append(_parameter_card(arg, kind="keyword_only", default=default))
    if arguments.kwarg is not None:
        cards.append(_parameter_card(arguments.kwarg, kind="kwarg", default=None))
    return cards


def _parameter_card(arg: ast.arg, *, kind: str, default: ast.AST | None) -> ParameterCard:
    return ParameterCard(
        name=str(arg.arg or ""),
        kind=kind,
        annotation=_expr_text(arg.annotation) if arg.annotation is not None else "",
        default=_expr_text(default) if default is not None else "",
    )


def _signature_text(qualname: str, parameters: tuple[ParameterCard, ...]) -> str:
    names: list[str] = []
    for item in parameters:
        prefix = "*" if item.kind == "vararg" else "**" if item.kind == "kwarg" else ""
        suffix = f"={item.default}" if item.default else ""
        names.append(f"{prefix}{item.name}{suffix}")
    return f"{qualname}({', '.join(names)})"


def _expr_text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def _target_texts(target: ast.AST | None) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [_expr_text(target)]
    if isinstance(target, (ast.Tuple, ast.List)):
        result: list[str] = []
        for item in target.elts:
            result.extend(_target_texts(item))
        return result
    return []


def _nearest_scope(scopes: tuple[_Scope, ...], kind: str) -> _Scope | None:
    for scope in reversed(scopes):
        if scope.kind == kind:
            return scope
    return None


def _symbol_binding(
    file_ref: str,
    scopes: tuple[_Scope, ...],
    symbol_name: str,
    binding_kind: str,
    definition_anchor_id: str,
) -> dict[str, Any]:
    scope_anchor_id = scopes[-1].anchor_id if scopes else ""
    raw_id = "|".join([file_ref, scope_anchor_id, symbol_name, binding_kind, definition_anchor_id])
    return _drop_empty(
        {
            "binding_id": "pybind:" + hashlib.sha256(raw_id.encode("utf-8", errors="ignore")).hexdigest()[:24],
            "file_ref": file_ref,
            "scope_ast_node_id": scope_anchor_id,
            "symbol_name": str(symbol_name or ""),
            "binding_kind": binding_kind,
            "definition_ast_node_id": definition_anchor_id,
            "reference_ast_node_ids": [],
            "confidence": "definition_exact_reference_unresolved",
        }
    )


def _node_text_digest(source: str, node: ast.AST) -> str:
    try:
        segment = ast.get_source_segment(source, node) or ""
    except Exception:
        segment = ""
    if not segment:
        segment = f"{type(node).__name__}:{getattr(node, 'lineno', 0)}:{getattr(node, 'col_offset', 0)}"
    return hashlib.sha256(segment.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if value not in ("", None, [], {}, ())
    }
