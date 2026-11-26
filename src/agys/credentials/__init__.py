"""凭据存储抽象层。

各平台实现同一个接口，便于用 memory 后端做跨平台测试，也便于
agy 升级换存储位置时只改一个文件。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import IS_LINUX, IS_MAC, IS_WIN, paths


class CredentialError(Exception):
    pass


class CredentialStore(ABC):
    name = "abstract"

    @abstractmethod
    def get(self) -> bytes | None:
        ...

    @abstractmethod
    def set(self, blob: bytes):
        ...

    @abstractmethod
    def delete(self):
        ...

    def describe(self) -> str:
        return self.name


def resolve_backend(name=None) -> str:
    p = paths()
    backend = name or p.backend
    if backend == "auto":
        backend = "windows" if IS_WIN else "macos" if IS_MAC else "linux"
    return backend


def build_store(backend=None, cred_target=None, cred_user=None,
                token_path=None, memory_file=None) -> CredentialStore:
    """按显式参数构造存储。

    布局自动发现时要试探「候选位置」，不能改动全局覆盖，所以留出这个入口；
    参数缺省时回落到 paths() 的当前值。
    """
    p = paths()
    backend = resolve_backend(backend)
    cred_target = cred_target or p.cred_target
    cred_user = cred_user or p.cred_user
    if backend == "memory":
        from .memory import MemoryStore
        return MemoryStore(memory_file or p.memory_file)
    if backend == "windows":
        if not IS_WIN:
            raise CredentialError("windows 后端只能在 Windows 上使用")
        from .windows import WindowsStore
        return WindowsStore(cred_target, cred_user)
    if backend == "macos":
        from .macos import MacStore
        return MacStore(cred_target, cred_user)
    if backend == "linux":
        from .linux import LinuxStore
        return LinuxStore(token_path or p.linux_token)
    raise CredentialError(f"未知凭据后端: {backend}")


def get_store() -> CredentialStore:
    return build_store()


__all__ = ["CredentialStore", "CredentialError", "get_store"]
