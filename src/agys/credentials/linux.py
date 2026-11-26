"""Linux 文件式 token 后端。

agy 在 Linux 上以 GEMINI_FORCE_FILE_STORAGE=true 时把凭据写到
~/.gemini/antigravity-cli/antigravity-oauth-token；文件权限 0600。
"""
from __future__ import annotations

import os

from ..crypto import secure_write
from . import CredentialError, CredentialStore


class LinuxStore(CredentialStore):
    name = "linux-file-token"

    def __init__(self, token_path: str):
        self.token_path = token_path

    def describe(self) -> str:
        return f"{self.name} ({self.token_path})"

    def get(self):
        try:
            with open(self.token_path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None
        except OSError as e:
            raise CredentialError(f"读取 {self.token_path} 失败: {e}")

    def set(self, blob: bytes):
        secure_write(self.token_path, blob)

    def delete(self):
        try:
            os.unlink(self.token_path)
        except FileNotFoundError:
            pass
