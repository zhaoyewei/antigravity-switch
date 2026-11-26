"""测试用内存/文件后端：跨进程持久化到 JSON 文件，绝不触碰真实凭据。"""
from __future__ import annotations

import base64
import json
import os

from ..crypto import secure_write
from . import CredentialError, CredentialStore


class MemoryStore(CredentialStore):
    name = "memory-test-backend"

    def __init__(self, path: str):
        self.path = path

    def describe(self) -> str:
        return f"{self.name} ({self.path})"

    def _read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, ValueError):
            return {}

    def get(self):
        raw = self._read().get("blob")
        if raw is None:
            return None
        try:
            return base64.b64decode(raw)
        except Exception as e:
            raise CredentialError(f"memory backend 数据损坏: {e}")

    def set(self, blob: bytes):
        secure_write(self.path, (json.dumps(
            {"blob": base64.b64encode(blob).decode("ascii")}) + "\n").encode("utf-8"))

    def delete(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
