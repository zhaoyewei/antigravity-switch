"""macOS Keychain 后端（go-keyring 惯例：service=gemini, account=antigravity）。"""
from __future__ import annotations

import subprocess

from . import CredentialError, CredentialStore


class MacStore(CredentialStore):
    name = "macos-keychain"

    def __init__(self, target: str, user: str):
        if ":" in target:
            self.service, self.account = target.split(":", 1)
        else:
            self.service, self.account = target, user

    def describe(self) -> str:
        return f"{self.name} ({self.service}/{self.account})"

    def get(self):
        r = subprocess.run(
            ["security", "find-generic-password", "-s", self.service,
             "-a", self.account, "-w"], capture_output=True)
        if r.returncode != 0:
            return None
        return r.stdout.rstrip(b"\r\n")

    def set(self, blob: bytes):
        r = subprocess.run(
            ["security", "add-generic-password", "-U", "-s", self.service,
             "-a", self.account, "-w", blob.decode("utf-8")],
            capture_output=True)
        if r.returncode != 0:
            raise CredentialError(
                f"security add-generic-password 失败: {r.stderr.decode(errors='replace').strip()}")

    def delete(self):
        subprocess.run(
            ["security", "delete-generic-password", "-s", self.service,
             "-a", self.account], capture_output=True)
