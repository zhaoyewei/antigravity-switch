#!/usr/bin/env bash
# antigravity-switch (agys) 一键安装脚本
#   macOS / Linux:  curl -fsSL https://raw.githubusercontent.com/OWNER/antigravity-switch/main/install.sh | bash
#   Windows PowerShell（推荐）: irm .../install.ps1 | iex
#
# 默认下载 GitHub Release 里的**单文件二进制**（内置 Python 运行时），
# 用户机器不需要安装 Python。若该平台没有产物 / 下载失败，回退源码安装（需 Python 3.9+）。
# 也可在仓库目录内运行：bash install.sh（离线开发安装，用本地 src/）。
set -euo pipefail

OWNER="${GITHUB_OWNER:-${AGYS_GITHUB_OWNER:-zhaoyewei}}"
REPO="antigravity-switch"
REF="${AGYS_REF:-main}"
if [ "$REF" = "main" ] || [ "$REF" = "master" ]; then
  TARBALL="https://github.com/$OWNER/$REPO/archive/refs/heads/$REF.tar.gz"
else
  TARBALL="https://github.com/$OWNER/$REPO/archive/refs/tags/$REF.tar.gz"
fi

IS_WINDOWS=0
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;; esac
DEST="${AGYS_INSTALL_DIR:-$HOME/.agys}"
# 内部文件操作统一用 MSYS 风格路径（避免 Windows 盘符路径被删除策略拒绝）
if [ "$IS_WINDOWS" = "1" ]; then DEST="$(cygpath -u "$DEST")"; fi
LIB="$DEST/lib"
BIN="$DEST/bin"

echo "==> 安装 antigravity-switch (agys) 到 $DEST"

TMP="$(mktemp -d)"
# Git Bash 的 TMPDIR 常是 C:\...\Temp（反斜杠），cygpath 归一成 POSIX 路径，
# 否则 rm / curl 在混合路径上会出问题。清理失败不该影响安装结果。
if [ "$IS_WINDOWS" = "1" ] && command -v cygpath >/dev/null 2>&1; then
  TMP="$(cygpath -u "$TMP")"
fi
trap 'rm -rf "$TMP" 2>/dev/null || true' EXIT

# ---------------------------------------------------------------- 平台与产物名
# 与 src/agys/installer.py 的 asset_name() 保持一致（不含版本号，latest/download 直接可用）
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) OS_KIND="windows" ;;
  Darwin)               OS_KIND="macos" ;;
  Linux)                OS_KIND="linux" ;;
  *)                    OS_KIND="" ;;
esac
case "$(uname -m)" in
  x86_64|amd64) ARCH="x86_64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *)            ARCH="" ;;
esac
ASSET=""
if [ -n "$OS_KIND" ] && [ -n "$ARCH" ]; then
  ASSET="agys-$OS_KIND-$ARCH"
  if [ "$OS_KIND" = "windows" ]; then ASSET="$ASSET.exe"; fi
fi
# 自定义镜像若产物命名不同，可用 AGYS_ASSET 覆盖
if [ -n "${AGYS_ASSET:-}" ]; then ASSET="$AGYS_ASSET"; fi

# 跨平台 SHA-256（macOS 没有 sha256sum）。
# 用 stdin 而不是文件名：Git Bash 的临时路径含反斜杠时，sha256sum 会给哈希行
# 加上转义前缀 '\'，直接 cut 会把 '\' 带进哈希里导致校验永远失败。
digest_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum < "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 < "$1" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 < "$1" | awk '{print $NF}'
  else
    echo ""
  fi
}

BIN_TARGET="$BIN/agys"
case "$ASSET" in *.exe) BIN_TARGET="$BIN/agys.exe" ;; esac

# ---------------------------------------------------------------- 二进制安装（无需 Python）
try_binary() {
  if [ -z "$ASSET" ]; then
    echo "==> 当前平台/架构没有预编译产物（$(uname -s) / $(uname -m)）" >&2
    return 1
  fi
  if [ -n "${AGYS_BIN_REF:-}" ] && [ "$AGYS_BIN_REF" != "latest" ]; then
    DEFAULT_URL="https://github.com/$OWNER/$REPO/releases/download/$AGYS_BIN_REF/$ASSET"
  else
    DEFAULT_URL="https://github.com/$OWNER/$REPO/releases/latest/download/$ASSET"
  fi
  URL="${AGYS_BIN_URL:-$DEFAULT_URL}"
  echo "==> 下载独立二进制（内置运行时，无需 Python）：$ASSET"
  if ! curl -fsSL --retry 2 --connect-timeout 15 "$URL" -o "$TMP/agys.bin"; then
    echo "==> 下载失败：$URL" >&2
    return 1
  fi
  if [ ! -s "$TMP/agys.bin" ]; then
    echo "==> 下载内容为空，拒绝安装" >&2
    return 1
  fi
  EXPECTED="${AGYS_BIN_SHA256:-}"
  if [ -z "$EXPECTED" ] && [ -z "${AGYS_BIN_URL:-}" ]; then
    if curl -fsSL --connect-timeout 10 "$URL.sha256" -o "$TMP/agys.sha256" 2>/dev/null; then
      EXPECTED="$(awk 'NF {print $1; exit}' "$TMP/agys.sha256")"
    fi
  fi
  if [ -n "$EXPECTED" ]; then
    ACTUAL="$(digest_file "$TMP/agys.bin")"
    if [ -z "$ACTUAL" ] || [ "$ACTUAL" != "$(printf '%s' "$EXPECTED" | tr 'A-Z' 'a-z')" ]; then
      echo "!! SHA-256 校验失败：期望 $EXPECTED，实际 $ACTUAL" >&2
      return 1
    fi
    echo "==> SHA-256 校验通过"
  else
    echo "==> 提示：未找到 .sha256 校验文件，跳过校验（可设置 AGYS_BIN_SHA256）"
  fi
  mkdir -p "$BIN"
  # 清掉旧版源码安装的 shim，避免 PATH 里优先命中它们
  if [ "$OS_KIND" = "windows" ]; then
    rm -f "$BIN/agys" "$BIN/agys.cmd"
  else
    rm -f "$BIN/agys.exe" "$BIN/agys.cmd"
  fi
  cp "$TMP/agys.bin" "$BIN_TARGET"
  chmod 755 "$BIN_TARGET"
  return 0
}

# ---------------------------------------------------------------- 决定安装模式
LOCAL=0
if [ -f "$(pwd)/src/agys/__init__.py" ] && [ -f "$(pwd)/install.sh" ]; then LOCAL=1; fi
MODE="${AGYS_INSTALL_MODE:-binary}"
case "$MODE" in binary|source) ;; *) MODE="binary" ;; esac
if [ "$LOCAL" = "1" ] && [ -z "${AGYS_INSTALL_MODE:-}" ]; then
  MODE="source"
  echo "==> 离线模式：使用本地仓库 src/（源码安装）"
fi
if [ "${AGYS_USE_SOURCE:-0}" = "1" ]; then MODE="source"; fi

if [ "$MODE" = "binary" ]; then
  if try_binary; then
    printf 'binary\n' > "$DEST/install-mode"
  elif [ "${AGYS_REQUIRE_BINARY:-0}" = "1" ]; then
    echo "!! 无法获取预编译二进制，且 AGYS_REQUIRE_BINARY=1（不回退源码）" >&2
    exit 1
  else
    echo "==> 预编译二进制不可用，回退源码安装（需要 Python 3.9+）"
    MODE="source"
  fi
fi

# ---------------------------------------------------------------- 源码安装（回退路径）
if [ "$MODE" = "source" ]; then
  PY=""
  if command -v python3 >/dev/null 2>&1; then PY="python3"
  elif command -v python >/dev/null 2>&1; then PY="python"
  fi
  if [ -z "$PY" ]; then
    echo "!! 源码安装需要 Python 3.9+；当前平台也没有可用的预编译二进制。" >&2
    echo "   请安装 Python 后重试，或从 GitHub Releases 手动下载对应二进制。" >&2
    exit 1
  fi
  SRC=""
  if [ "$LOCAL" = "1" ]; then
    SRC="$(pwd)"
  else
    echo "==> 下载 $TARBALL"
    curl -fsSL "$TARBALL" -o "$TMP/agys.tar.gz"
    if [ -n "${AGYS_EXPECT_SHA256:-}" ]; then
      ACTUAL="$(digest_file "$TMP/agys.tar.gz")"
      if [ "$ACTUAL" != "$AGYS_EXPECT_SHA256" ]; then
        echo "!! SHA-256 校验失败：期望 $AGYS_EXPECT_SHA256，实际 $ACTUAL" >&2
        exit 1
      fi
      echo "==> SHA-256 校验通过"
    fi
    tar -xzf "$TMP/agys.tar.gz" -C "$TMP"
    FOUND="$(find "$TMP" -path '*/src/agys/__init__.py' -print -quit)"
    [ -n "$FOUND" ] || { echo "!! 下载内容中找不到 agys 包" >&2; exit 1; }
    SRC="$(cd "$(dirname "$(dirname "$(dirname "$FOUND")")")" && pwd)"
  fi
  if [ ! -f "$SRC/src/agys/__init__.py" ]; then
    echo "!! 找不到 src/agys/__init__.py（仓库结构异常）" >&2; exit 1
  fi
  grep -q '__version__' "$SRC/src/agys/__init__.py" || {
    echo "!! 包内缺少版本标记，拒绝安装" >&2; exit 1; }

  rm -rf "$LIB/agys"
  mkdir -p "$LIB" "$BIN"
  cp -R "$SRC/src/agys" "$LIB/agys"
  find "$LIB/agys" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

  SHIM_LIB="$LIB"
  SEP=":"
  if [ "$IS_WINDOWS" = "1" ]; then SHIM_LIB="$(cygpath -m "$LIB")"; SEP=";"; fi
  cat > "$BIN/agys" << EOF
#!/bin/sh
# agys launcher (installed, source mode)
PYTHONPATH="$SHIM_LIB\${PYTHONPATH:+$SEP\$PYTHONPATH}" exec $PY -m agys "\$@"
EOF
  chmod +x "$BIN/agys"
  if [ "$IS_WINDOWS" = "1" ]; then
    WINLIB="$(cygpath -w "$LIB")"
    printf '@echo off\r\nrem agys launcher (installed)\r\nset "PYTHONPATH=%s;%%PYTHONPATH%%"\r\npython -m agys %%*\r\nexit /b %%errorlevel%%\r\n' "$WINLIB" > "$BIN/agys.cmd"
  fi
  printf 'source\n' > "$DEST/install-mode"
fi

# ---------------------------------------------------------------- PATH（两种模式共用）
if [ "${AGYS_SKIP_PATH:-0}" = "1" ]; then
  echo "==> 跳过 PATH 修改（AGYS_SKIP_PATH=1）"
else
case ":$PATH:" in
  *":$BIN:"*) echo "==> PATH 已包含 $BIN" ;;
  *)
    if [ "$IS_WINDOWS" = "1" ]; then
      WINBIN="$(cygpath -w "$BIN")"
      HAVE="$(powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('PATH','User')" 2>/dev/null || true)"
      if [ -n "$HAVE" ] && echo "$HAVE" | grep -qiF "$WINBIN"; then
        echo "==> Windows 用户 PATH 已包含 $WINBIN"
      elif powershell -NoProfile -Command "[Environment]::SetEnvironmentVariable('PATH', [Environment]::GetEnvironmentVariable('PATH','User') + ';$WINBIN', 'User')" 2>/dev/null; then
        echo "==> 已把 $WINBIN 加入 Windows 用户 PATH（重开终端后生效）"
      else
        echo "!! 无法自动修改 Windows PATH，请手动加入：$WINBIN"
      fi
    else
      RC="$HOME/.bashrc"; touch "$RC"
      grep -qF "$BIN" "$RC" 2>/dev/null || printf '\n# added by agys installer\nexport PATH="%s:$PATH"\n' "$BIN" >> "$RC"
      echo "==> 已把 $BIN 写入 ~/.bashrc（新终端生效）"
    fi ;;
esac
fi

echo "==> 验证安装"
if [ "$MODE" = "binary" ]; then
  "$BIN_TARGET" version
else
  "$BIN/agys" version
fi
echo
echo "安装完成（$MODE 模式）。运行 agys doctor 自检，或直接 agys add 添加第一个帐号。"
echo "升级：agys update    卸载：curl -fsSL .../uninstall.sh | bash"
