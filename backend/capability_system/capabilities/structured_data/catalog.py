from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from core.project_layout import ProjectLayout


class StructuredDataCatalog:
    DATASET_CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "knowledge/E-commerce Data/employees.xlsx",
            (
                "employee",
                "employees",
                "staff",
                "salary",
                "wage",
                "pay",
                "base_salary",
                "department",
                "title",
                "manager",
                "hire",
                "employee_id",
                "员工",
                "薪水",
                "工资",
                "薪资",
                "底薪",
                "部门",
                "职位",
                "入职",
                "经理",
                "销售人员",
                "人员",
            ),
        ),
        (
            "knowledge/E-commerce Data/inventory.xlsx",
            (
                "inventory",
                "stock",
                "reorder",
                "warehouse",
                "sku",
                "库存",
                "缺货",
                "补货",
                "安全库存",
                "仓库",
                "商品",
                "货物",
            ),
        ),
        (
            "knowledge/E-commerce Data/sales_orders.xlsx",
            (
                "sales",
                "sale",
                "order",
                "orders",
                "revenue",
                "region",
                "amount",
                "unit_price",
                "quantity",
                "gmv",
                "销量",
                "销售额",
                "销售",
                "订单",
                "地区",
                "区域",
                "金额",
                "总额",
                "成交",
                "排名",
                "排行",
            ),
        ),
        (
            "knowledge/E-commerce Data/customers.xlsx",
            (
                "customer",
                "customers",
                "segment",
                "signup",
                "email",
                "province",
                "客户",
                "用户",
                "分群",
                "注册",
                "邮箱",
                "省份",
            ),
        ),
    )

    COLUMN_ALIASES: dict[str, set[str]] = {
        "employee_id": {"employee_id", "员工编号", "工号"},
        "order_id": {"order_id", "订单编号"},
        "customer_id": {"customer_id", "客户编号", "用户编号"},
        "manager_id": {"manager_id", "上级编号", "直属经理编号"},
        "name": {"name", "姓名", "员工姓名", "客户姓名", "用户名"},
        "department": {"department", "部门"},
        "title": {"title", "职位", "职级"},
        "hire_date": {"hire_date", "入职日期"},
        "city": {"city", "城市"},
        "province": {"province", "省份"},
        "base_salary": {"base_salary", "salary", "薪水", "工资", "薪资", "底薪"},
        "sku": {"sku", "SKU", "商品SKU"},
        "product": {"product", "商品名称", "商品", "产品"},
        "category": {"category", "类别", "品类"},
        "warehouse": {"warehouse", "仓库"},
        "stock_on_hand": {"stock_on_hand", "当前库存", "库存", "stock", "qty", "quantity"},
        "reorder_level": {"reorder_level", "安全库存", "补货阈值", "reorder", "safety_stock"},
        "unit_cost": {"unit_cost", "成本", "单价", "价格", "cost", "price"},
        "last_restock_date": {"last_restock_date", "最后补货日期", "补货日期"},
        "order_date": {"order_date", "订单日期"},
        "quantity": {"quantity", "销量", "数量", "件数"},
        "unit_price": {"unit_price", "成交单价", "订单单价"},
        "total_amount": {"total_amount", "销售额", "订单总额", "总金额", "金额"},
        "region": {"region", "区域", "地区"},
        "status": {"status", "订单状态", "状态"},
        "segment": {"segment", "客群", "客户分群"},
        "signup_date": {"signup_date", "注册日期"},
        "email": {"email", "邮箱"},
    }

    METRIC_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("base_salary", ("salary", "wage", "pay", "薪水", "工资", "薪资", "底薪")),
        ("total_amount", ("total_amount", "sales", "revenue", "gmv", "销售额", "总额", "金额", "成交额", "销售")),
        ("quantity", ("quantity", "销量", "件数", "数量")),
        ("stock_on_hand", ("stock", "inventory", "库存", "现有库存", "当前库存")),
        ("reorder_level", ("reorder", "safety_stock", "安全库存", "补货阈值")),
        ("unit_price", ("unit_price", "成交单价", "售价")),
        ("unit_cost", ("unit_cost", "cost", "成本", "单价", "价格")),
    )

    GROUP_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("region", ("region", "区域", "地区")),
        ("warehouse", ("warehouse", "仓库")),
        ("category", ("category", "类别", "品类")),
        ("department", ("department", "部门")),
        ("title", ("title", "职位")),
        ("city", ("city", "城市")),
        ("province", ("province", "省份")),
        ("segment", ("segment", "分群", "客群")),
        ("status", ("status", "状态")),
        ("product", ("product", "商品", "产品")),
        ("name", ("name", "姓名", "员工", "客户", "销售人员")),
    )

    DISPLAY_LABELS: dict[str, str] = {
        "employee_id": "员工编号",
        "order_id": "订单编号",
        "customer_id": "客户编号",
        "manager_id": "上级编号",
        "name": "姓名",
        "department": "部门",
        "title": "职位",
        "hire_date": "入职日期",
        "city": "城市",
        "province": "省份",
        "base_salary": "薪水",
        "sku": "SKU",
        "product": "商品名称",
        "category": "类别",
        "warehouse": "仓库",
        "stock_on_hand": "当前库存",
        "reorder_level": "安全库存",
        "unit_cost": "成本",
        "last_restock_date": "最后补货日期",
        "order_date": "订单日期",
        "quantity": "数量",
        "unit_price": "单价",
        "total_amount": "总金额",
        "region": "地区",
        "status": "状态",
        "segment": "客群",
        "signup_date": "注册日期",
        "email": "邮箱",
    }

    PRIORITY_DATASET_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("knowledge/E-commerce Data/inventory.xlsx", ("库存", "缺货", "补货", "安全库存", "仓库", "sku")),
        ("knowledge/E-commerce Data/employees.xlsx", ("薪水", "工资", "薪资", "底薪", "员工", "部门", "职位", "入职")),
        ("knowledge/E-commerce Data/customers.xlsx", ("客户", "用户", "分群", "邮箱", "注册")),
        ("knowledge/E-commerce Data/sales_orders.xlsx", ("销售", "销售额", "订单", "成交", "金额", "区域", "地区", "销量")),
    )

    DEFAULT_GROUP_BY: dict[str, str] = {
        "knowledge/E-commerce Data/sales_orders.xlsx": "product",
        "knowledge/E-commerce Data/employees.xlsx": "name",
        "knowledge/E-commerce Data/inventory.xlsx": "product",
        "knowledge/E-commerce Data/customers.xlsx": "name",
    }

    DEFAULT_METRIC: dict[str, tuple[str, ...]] = {
        "knowledge/E-commerce Data/sales_orders.xlsx": ("total_amount", "quantity", "unit_price"),
        "knowledge/E-commerce Data/employees.xlsx": ("base_salary",),
        "knowledge/E-commerce Data/inventory.xlsx": ("stock_on_hand", "reorder_level", "unit_cost"),
        "knowledge/E-commerce Data/customers.xlsx": (),
    }

    @classmethod
    def list_dataset_paths(cls, root_dir: Path) -> list[Path]:
        knowledge_dir = ProjectLayout.from_backend_dir(root_dir).knowledge_storage_dir.resolve()
        found: list[Path] = []
        for relative_path, _keywords in cls.DATASET_CANDIDATES:
            candidate = cls._resolve_knowledge_relative_path(knowledge_dir, relative_path)
            if candidate.exists() and candidate.is_file():
                found.append(candidate)
        return found

    @classmethod
    def resolve_dataset_path(cls, root_dir: Path, path: str, query: str) -> Path:
        normalized = (path or "").strip()
        if not normalized:
            normalized = cls.default_path_for_query(query)
        knowledge_dir = ProjectLayout.from_backend_dir(root_dir).knowledge_storage_dir.resolve()
        candidate = cls._resolve_knowledge_relative_path(knowledge_dir, normalized)
        if knowledge_dir not in candidate.parents and candidate != knowledge_dir:
            raise ValueError("检测到非法路径访问。")
        return candidate

    @classmethod
    def default_path_for_query(cls, query: str) -> str:
        lowered = (query or "").lower()
        for path, markers in cls.PRIORITY_DATASET_RULES:
            if any(marker.lower() in lowered for marker in markers):
                return path

        scored: list[tuple[int, str]] = []
        for path, keywords in cls.DATASET_CANDIDATES:
            score = sum(1 for keyword in keywords if keyword.lower() in lowered)
            if score > 0:
                scored.append((score, path))
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            return scored[0][1]
        raise ValueError("未能根据问题自动判断数据文件，请显式提供 path。")

    @classmethod
    def target_object_for_path(cls, path: str | Path) -> str:
        normalized = str(path or "").replace("\\", "/").lower()
        if normalized.endswith("/inventory.xlsx"):
            return "inventory"
        if normalized.endswith("/employees.xlsx"):
            return "employee"
        if normalized.endswith("/sales_orders.xlsx"):
            return "sales"
        if normalized.endswith("/customers.xlsx"):
            return "customer"
        return ""

    @classmethod
    def display_label(cls, column: str) -> str:
        if column == "shortage_qty":
            return "缺口"
        return cls.DISPLAY_LABELS.get(column, column)

    @classmethod
    def relative_path(cls, root_dir: Path, path: Path) -> str:
        knowledge_dir = ProjectLayout.from_backend_dir(root_dir).knowledge_storage_dir.resolve()
        relative = path.resolve().relative_to(knowledge_dir).as_posix()
        return f"knowledge/{relative}".rstrip("/")

    @classmethod
    def resolve_dataset_path_from_history(cls, root_dir: Path, history: list[dict[str, Any]]) -> Path | None:
        candidates = cls.list_dataset_paths(root_dir)
        if not candidates:
            return None

        recent_texts: list[str] = []
        for item in reversed(history[-12:]):
            content = str(item.get("content", "") or "").strip()
            if content:
                recent_texts.append(content)

        for text in recent_texts:
            for matched_name in re.findall(r"([^\s:：\n]+\.(?:xlsx|csv|json))", text, flags=re.IGNORECASE):
                resolved = cls._match_filename(root_dir, candidates, matched_name)
                if resolved is not None:
                    return resolved

        transcript = "\n".join(recent_texts)
        if not transcript:
            return None
        scored = cls._score_candidates(root_dir, candidates, transcript)
        if scored and scored[0][0] > 0:
            return scored[0][1]
        return None

    @classmethod
    def _match_filename(cls, root_dir: Path, candidates: list[Path], filename: str) -> Path | None:
        normalized = filename.strip().lower()
        for candidate in candidates:
            if candidate.name.lower() == normalized:
                return candidate
            rel = cls.relative_path(root_dir, candidate).lower()
            if rel.endswith(normalized):
                return candidate
        stem = Path(filename).stem.lower()
        for candidate in candidates:
            if candidate.stem.lower() == stem:
                return candidate
        return None

    @classmethod
    def _score_candidates(cls, root_dir: Path, candidates: list[Path], query: str) -> list[tuple[int, Path]]:
        query_text = (query or "").lower()
        query_tokens = cls._extract_tokens(query_text)
        scored: list[tuple[int, Path]] = []
        for candidate in candidates:
            rel = cls.relative_path(root_dir, candidate).lower()
            stem = candidate.stem.lower()
            tokens = cls._extract_tokens(stem) + cls._extract_tokens(rel)
            score = 0
            for token in set(tokens):
                if len(token) < 2:
                    continue
                if token in query_text:
                    score += max(2, len(token))
            for token in query_tokens:
                if token and token in stem:
                    score += max(1, len(token))
            scored.append((score, candidate))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored

    @staticmethod
    def _resolve_knowledge_relative_path(knowledge_dir: Path, path: str) -> Path:
        normalized = str(path or "").replace("\\", "/").strip("/")
        if normalized.lower().startswith("knowledge/"):
            normalized = normalized.split("/", 1)[1]
        return (knowledge_dir / normalized).resolve()

    @classmethod
    def _extract_tokens(cls, text: str) -> list[str]:
        parts = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", text)
        return [part.strip() for part in parts if part.strip()]



