#!/usr/bin/env bash
# antigravity-switch (agys) 一键安装脚本
#   curl -fsSL https://raw.githubusercontent.com/OWNER/antigravity-switch/main/install.sh | bash
# 也可在仓库目录内运行：bash install.sh（离线，用本地 src/）
set -euo pipefail

OWNER="${GITHUB_OWNER:-zhaoyewei}"
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

PY=""
if command -v python3 >/dev/null 2>&1; then PY="python3"
elif command -v python >/dev/null 2>&1; then PY="python"
fi
if [ -z "$PY" ]; then echo "!! 需要 Python 3.9+" >&2; exit 1; fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
SRC=""
if [ -f "$(pwd)/src/agys/__init__.py" ] && [ -f "$(pwd)/install.sh" ]; then
  SRC="$(pwd)"
  echo "==> 离线模式：使用本地仓库 src/"
else
  echo "==> 下载 $TARBALL"
  curl -fsSL "$TARBALL" -o "$TMP/agys.tar.gz"
  if [ -n "${AGYS_EXPECT_SHA256:-}" ]; then
    ACTUAL="$(sha256sum "$TMP/agys.tar.gz" | cut -d' ' -f1)"
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
  echo "!! 找不到 src/agys/__init__.py（仓库结构异常）" >&2
  exit 1
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
# agys launcher (installed)
PYTHONPATH="$SHIM_LIB\${PYTHONPATH:+$SEP\$PYTHONPATH}" exec $PY -m agys "\$@"
EOF
chmod +x "$BIN/agys"

if [ "$IS_WINDOWS" = "1" ]; then
  WINLIB="$(cygpath -w "$LIB")"
  printf '@echo off\r\nrem agys launcher (installed)\r\nset "PYTHONPATH=%s;%%PYTHONPATH%%"\r\npython -m agys %%*\r\nexit /b %%errorlevel%%\r\n' "$WINLIB" > "$BIN/agys.cmd"
fi

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
"$BIN/agys" version
echo
echo "安装完成。运行 agys doctor 自检，或直接 agys add 添加第一个帐号。"
echo "升级：agys update    卸载：curl -fsSL .../uninstall.sh | bash"
