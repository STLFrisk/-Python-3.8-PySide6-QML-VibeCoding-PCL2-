"""账号模型: 离线账号 UUID 生成、微软账号占位与序列化。

离线 UUID 采用 Minecraft 官方规则: md5("OfflinePlayer:" + 名字) 取前 16 字节作为
UUID v3 的字节内容。
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

# 账号类型
KIND_OFFLINE = "offline"
KIND_MICROSOFT = "microsoft"


@dataclass
class Account:
    """一个启动器账号。kind 取 "offline" / "microsoft"。"""

    name: str
    kind: str = KIND_OFFLINE
    uuid: str = ""
    token: str = ""


def offline_uuid(name: str) -> str:
    """按官方规则计算离线账号 UUID(小写带连字符)。"""
    raw = ("OfflinePlayer:" + str(name or "")).encode("utf-8")
    digest = hashlib.md5(raw).digest()
    try:
        return str(uuid.UUID(bytes=digest, version=3))
    except Exception:
        return ""


def offline(name: str) -> Account:
    """构造一个离线账号。"""
    return Account(name=str(name or ""), kind=KIND_OFFLINE, uuid=offline_uuid(name), token="")


def to_dict(a: Account) -> dict:
    """账号转字典(用于写入配置)。"""
    if a is None:
        return {}
    return {
        "name": str(getattr(a, "name", "") or ""),
        "kind": str(getattr(a, "kind", KIND_OFFLINE) or KIND_OFFLINE),
        "uuid": str(getattr(a, "uuid", "") or ""),
        "token": str(getattr(a, "token", "") or ""),
    }


def from_dict(d) -> Account:
    """字典转账号; 缺字段时用安全默认值。"""
    if not isinstance(d, dict):
        return Account(name="")
    name = str(d.get("name") or "")
    kind = str(d.get("kind") or KIND_OFFLINE)
    uid = str(d.get("uuid") or "")
    if not uid and kind == KIND_OFFLINE and name:
        uid = offline_uuid(name)
    return Account(name=name, kind=kind, uuid=uid, token=str(d.get("token") or ""))


def display(a: Account) -> str:
    """账号显示名: 离线显示 "名字（离线）"。"""
    if a is None:
        return ""
    name = str(getattr(a, "name", "") or "")
    kind = str(getattr(a, "kind", KIND_OFFLINE) or KIND_OFFLINE)
    if kind == KIND_MICROSOFT:
        return "%s（微软）" % name
    if kind == KIND_OFFLINE:
        return "%s（离线）" % name
    return "%s（%s）" % (name, kind)
