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


def get_store() -> CredentialStore:
    p = paths()
    backend = p.backend
    if backend == "auto":
        backend = "windows" if IS_WIN else "macos" if IS_MAC else "linux"
    if backend == "memory":
        from .memory import MemoryStore
        return MemoryStore(p.memory_file)
    if backend == "windows":
        if not IS_WIN:
            raise CredentialError("windows 后端只能在 Windows 上使用")
        from .windows import WindowsStore
        return WindowsStore(p.cred_target, p.cred_user)
    if backend == "macos":
        from .macos import MacStore
        return MacStore(p.cred_target, p.cred_user)
    if backend == "linux":
        from .linux import LinuxStore
        return LinuxStore(p.linux_token)
    raise CredentialError(f"未知凭据后端: {backend}")


__all__ = ["CredentialStore", "CredentialError", "get_store"]
