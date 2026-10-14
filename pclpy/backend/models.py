"""给 QML 用的字典列表模型。

每一行都是一个 dict, 键就是 QML 里的角色名 (model.name / model.subtitle ...)。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from PySide6.QtCore import QAbstractListModel, QModelIndex, Property, Qt, Signal, Slot


class DictListModel(QAbstractListModel):
    countChanged = Signal()

    def __init__(self, roles: Iterable[str], parent=None) -> None:
        super().__init__(parent)
        self._roles: List[str] = list(roles)
        self._rows: List[Dict[str, Any]] = []
        self._role_ids: Dict[int, str] = {
            int(Qt.UserRole) + 1 + i: name for i, name in enumerate(self._roles)
        }
        # 角色名 → role id(update_row 只报"真的变了"的角色时要用)
        self._name_ids: Dict[str, int] = {
            name: rid for rid, name in self._role_ids.items()
        }
        self._filter: str = ""

    # ------------------------------------------------------------ Qt 接口
    def roleNames(self) -> Dict[int, bytes]:  # noqa: N802
        return {rid: name.encode("utf-8") for rid, name in self._role_ids.items()}

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent is not None and parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if index.row() < 0 or index.row() >= len(self._rows):
            return None
        name = self._role_ids.get(int(role))
        if name is None:
            return None
        value = self._rows[index.row()].get(name, "")
        return "" if value is None else value

    # ------------------------------------------------------------ 属性
    @Property(int, notify=countChanged)
    def count(self) -> int:  # type: ignore[override]
        return len(self._rows)

    # ------------------------------------------------------------ 操作
    def set_rows(self, rows: Iterable[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = [dict(r) for r in rows]
        self.endResetModel()
        self.countChanged.emit()

    def rows(self) -> List[Dict[str, Any]]:
        return self._rows

    @Slot(int, result="QVariantMap")
    def at(self, index: int) -> Dict[str, Any]:
        if 0 <= index < len(self._rows):
            return dict(self._rows[index])
        return {}

    def update_row(self, index: int, values: Dict[str, Any],
                   roles: Optional[Iterable[str]] = None) -> None:
        """更新一行的若干字段, 并且**只为真正变化的角色**发 dataChanged。

        以前这里是"无论改什么都发全部角色的 dataChanged"。任务页的委托里嵌套着
        12 行步骤的 Repeater, 于是每个进度回调都会把整张卡片(含全部步骤行)重建一遍 ——
        实测单次更新要 30ms 上下, 峰值 1.3s; 高并发下载(几十条连接每秒几百次回调)时
        主线程被这些重建彻底占满, 界面直接"未响应"。
        现在: 没变的角色不报, 全部没变时连 dataChanged 都不发。
        ``roles`` 给出时只允许报告这批角色(可选, 默认不限制)。
        """
        if not (0 <= index < len(self._rows)):
            return
        row = self._rows[index]
        allowed = None if roles is None else set(str(item) for item in roles)
        changed = []
        for name, value in values.items():
            key = str(name)
            if allowed is not None and key not in allowed:
                continue
            if key not in row or row.get(key) != value:
                changed.append(key)
            row[key] = value
        if not changed:
            return
        ids = [self._name_ids[key] for key in changed if key in self._name_ids]
        if not ids:
            return
        left = self.index(index, 0)
        self.dataChanged.emit(left, left, ids)

    def set_role(self, index: int, role: str, value: Any) -> None:
        self.update_row(index, {role: value})

    def clear(self) -> None:
        self.set_rows([])


class FilterableListModel(DictListModel):
    """带本地搜索过滤的列表模型(按 search 字段匹配)。"""

    filterChanged = Signal()

    def __init__(self, roles: Iterable[str], parent=None) -> None:
        super().__init__(roles, parent)
        self._all: List[Dict[str, Any]] = []
        self._filter = ""

    @Property(str, notify=filterChanged)
    def filter(self) -> str:
        return self._filter

    def set_source(self, rows: Iterable[Dict[str, Any]]) -> None:
        self._all = [dict(r) for r in rows]
        self._apply()

    def source(self) -> List[Dict[str, Any]]:
        return self._all

    @Slot(str)
    def set_filter(self, text: str) -> None:
        self._filter = (text or "").strip().lower()
        self.filterChanged.emit()
        self._apply()

    def _apply(self) -> None:
        if not self._filter:
            self.set_rows(self._all)
            return
        f = self._filter
        hits = [r for r in self._all if f in str(r.get("search", "")).lower()
                or f in str(r.get("name", "")).lower()]
        self.set_rows(hits)
