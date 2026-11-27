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

# ---------------------------------------------------------------- PATH / shell 启动文件
# 目标：装完就能用，不需要手动 source。分三层保障：
#   1) shell 启动文件（bash 的「非登录」+「登录」两条链，以及 zsh）—— 新开终端直接可用；
#   2) Windows 用户注册表 PATH —— cmd / PowerShell / 之后启动的进程也能找到；
#   3) 脚本结束时打印一行 export —— 供「已经开着的当前窗口」立刻生效。
# 旧版只写 ~/.bashrc：但 Git Bash 与 macOS Terminal 起的是登录 shell，读的是
# ~/.bash_profile / ~/.profile，永远读不到 ~/.bashrc，于是每开一个窗口都得手敲
# `source ~/.bashrc` —— 这就是本次修的问题。
BLOCK_BEGIN="# >>> agys installer >>>"
BLOCK_END="# <<< agys installer <<<"

# 把 PATH 段写成一个带标记、且自身幂等的块：
#   - 带标记 → 卸载时能精确摘掉，不会误删用户自己的行；
#   - case 里先判断 → 同一份 rc 被反复 source 也不会把 PATH 越堆越长。
rc_write_block() {  # $1 = 启动文件路径
  local _rc="$1" _shown
  case "$_rc" in "$HOME"/*) _shown="~/${_rc#"$HOME"/}" ;; *) _shown="$_rc" ;; esac
  if [ -f "$_rc" ] && grep -qF "$BLOCK_BEGIN" "$_rc" 2>/dev/null; then
    echo "==> $_shown 已包含 agys 的 PATH 配置"
    return 0
  fi
  mkdir -p "$(dirname "$_rc")" 2>/dev/null || true
  if [ -s "$_rc" ]; then printf '\n' >> "$_rc"; fi
  {
    printf '%s\n' "$BLOCK_BEGIN"
    printf 'case ":$PATH:" in\n'
    printf '  *":%s:"*) ;;\n' "$BIN"
    printf '  *) PATH="%s:$PATH"; export PATH ;;\n' "$BIN"
    printf 'esac\n'
    printf '%s\n' "$BLOCK_END"
  } >> "$_rc"
  echo "==> 已把 $BIN 写入 $_shown"
}

# 登录 shell 按 bash 的固定顺序找启动文件，先命中者胜；都没有时返回 ~/.bash_profile
bash_login_rc() {
  local _f
  for _f in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
    if [ -f "$_f" ]; then printf '%s\n' "$_f"; return 0; fi
  done
  printf '%s\n' "$HOME/.bash_profile"
}

SKIP_RC="${AGYS_SKIP_PATH:-0}"
SKIP_OS_PATH="${AGYS_SKIP_PATH:-0}"
# 测试用：只跳过注册表这类系统级 PATH，仍验证启动文件逻辑
if [ "${AGYS_SKIP_WIN_PATH:-0}" = "1" ]; then SKIP_OS_PATH=1; fi

if [ "$SKIP_RC" = "1" ]; then
  echo "==> 跳过 PATH / 启动文件修改（AGYS_SKIP_PATH=1）"
else
  case ":$PATH:" in
    *":$BIN:"*) echo "==> 当前 PATH 已包含 $BIN" ;;
  esac

  # bash 非登录交互 shell：Linux 桌面终端、WSL、VS Code 集成终端、tmux
  rc_write_block "$HOME/.bashrc"

  # bash 登录 shell：Git Bash 窗口、macOS Terminal、ssh 登录、`bash -lc`
  LOGIN_RC="$(bash_login_rc)"
  if [ ! -f "$LOGIN_RC" ]; then
    # 没有任何登录启动文件时自建一个，并按 Git for Windows 的惯例级联 .profile / .bashrc，
    # 免得以后用户往 ~/.bashrc 里加东西却在登录 shell 里失效。
    printf '# 由 agys 安装脚本创建：登录 shell 先加载 ~/.profile 与 ~/.bashrc\n' > "$LOGIN_RC"
    printf 'test -f "$HOME/.profile" && . "$HOME/.profile"\n' >> "$LOGIN_RC"
    printf 'test -f "$HOME/.bashrc" && . "$HOME/.bashrc"\n' >> "$LOGIN_RC"
    echo "==> 已创建 ${LOGIN_RC#"$HOME"/}（登录 shell 用）"
  fi
  rc_write_block "$LOGIN_RC"

  # zsh：macOS 默认 shell，也常被 Linux 用户切换使用
  HAS_ZSH=0
  if [ -f "$HOME/.zshrc" ] || [ -d "$HOME/.oh-my-zsh" ]; then HAS_ZSH=1; fi
  case "${SHELL:-}" in *zsh*) HAS_ZSH=1 ;; esac
  if [ "$HAS_ZSH" = "1" ]; then
    if [ ! -f "$HOME/.zshrc" ]; then : > "$HOME/.zshrc"; fi
    rc_write_block "$HOME/.zshrc"
  fi

  # Windows 注册表 PATH（只负责 cmd / PowerShell / 新进程；Git Bash 靠上面的启动文件）
  if [ "$IS_WINDOWS" = "1" ] && [ "$SKIP_OS_PATH" = "0" ]; then
    WINBIN="$(cygpath -w "$BIN")"
    HAVE="$(powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('PATH','User')" 2>/dev/null || true)"
    if [ -n "$HAVE" ] && echo "$HAVE" | grep -qiF "$WINBIN"; then
      echo "==> Windows 用户 PATH 已包含 $WINBIN"
    elif powershell -NoProfile -Command "[Environment]::SetEnvironmentVariable('PATH', [Environment]::GetEnvironmentVariable('PATH','User') + ';$WINBIN', 'User')" 2>/dev/null; then
      echo "==> 已把 $WINBIN 加入 Windows 用户 PATH（cmd / PowerShell 新窗口生效）"
    else
      echo "!! 无法自动修改 Windows PATH，请手动加入：$WINBIN"
    fi
  fi
fi

echo "==> 验证安装"
if [ "$MODE" = "binary" ]; then
  "$BIN_TARGET" version
else
  "$BIN/agys" version
fi
echo
echo "安装完成（$MODE 模式）。运行 agys doctor 自检，或直接 agys add 添加第一个帐号。"

# 已经开着的这个窗口：脚本是子进程，改不了父 shell 的环境变量（任何安装器都做不到），
# 所以只给出可以整行复制的最小命令。新开的窗口已经由启动文件接管，不需要这一步。
case ":$PATH:" in
  *":$BIN:"*) ;;
  *)
    echo
    echo "当前窗口立刻可用（复制这一行执行；只影响当前窗口）："
    echo "    export PATH=\"$BIN:\$PATH\""
    echo "新开一个终端则自动生效，无需再 source 任何文件。"
    ;;
esac

echo "升级：agys update    卸载：curl -fsSL .../uninstall.sh | bash"
