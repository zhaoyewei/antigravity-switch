#!/usr/bin/env bash
# antigravity-switch (agys) 一键安装脚本
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/OWNER/antigravity-switch/main/install.sh | bash
# 也可在本仓库目录内直接运行：bash install.sh（离线安装）

set -euo pipefail

OWNER="${GITHUB_OWNER:-yvws}"
REPO="antigravity-switch"
BRANCH="${GITHUB_BRANCH:-main}"
BASE="https://raw.githubusercontent.com/$OWNER/$REPO/$BRANCH"

DEST="${AGYS_INSTALL_DIR:-$HOME/.agys}"
BIN="$DEST/bin"
IS_WINDOWS=0
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;;
esac

echo "==> 安装 antigravity-switch (agys) 到 $BIN"

# --- 检查 Python ---
PY=""
if command -v python3 >/dev/null 2>&1; then PY="python3"
elif command -v python >/dev/null 2>&1; then PY="python"
elif command -v py >/dev/null 2>&1; then PY="py -3"
fi
if [ -z "$PY" ]; then
  echo "!!  未找到 Python（需要 3.9+）。请先安装 Python 后重跑本脚本。" >&2
  exit 1
fi

# --- 获取 agys.py：仓库目录内优先，否则从 GitHub 下载 ---
mkdir -p "$BIN"
if [ -f "$(pwd)/agys.py" ] && [ -f "$(pwd)/install.sh" ]; then
  cp "$(pwd)/agys.py" "$BIN/agys.py"
  echo "==> 使用本地副本 agys.py"
else
  echo "==> 从 GitHub 下载 $BASE/agys.py"
  curl -fsSL "$BASE/agys.py" -o "$BIN/agys.py"
fi

# --- Unix shim（Git Bash / macOS / Linux） ---
cat > "$BIN/agys" << 'EOF'
#!/bin/sh
# agys launcher
DIR="$(cd "$(dirname "$0")" && pwd)"
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$DIR/agys.py" "$@"
else
  exec python "$DIR/agys.py" "$@"
fi
EOF
chmod +x "$BIN/agys"

# --- Windows cmd/PowerShell shim ---
if [ "$IS_WINDOWS" = "1" ]; then
  printf '@echo off\r\nrem agys launcher\r\npython "%%~dp0agys.py" %%*\r\nif errorlevel 1 exit /b %%errorlevel%%\r\n' > "$BIN/agys.cmd"
fi

# --- PATH ---
case ":$PATH:" in
  *":$BIN:"*) echo "==> PATH 已包含 $BIN" ;;
  *)
    if [ "$IS_WINDOWS" = "1" ]; then
      :
    else
      # macOS / Linux：追加到 ~/.bashrc
      RC="$HOME/.bashrc"
      touch "$RC"
      if ! grep -qF '.agys/bin' "$RC" 2>/dev/null; then
        printf '\n# added by agys installer\nexport PATH="$HOME/.agys/bin:$PATH"\n' >> "$RC"
      fi
      echo "==> 已把 $BIN 写入 ~/.bashrc（新终端生效）"
    fi
    ;;
esac

if [ "$IS_WINDOWS" = "1" ]; then
  # Git Bash 的 PATH 不等于 Windows 用户 PATH；尝试把 Windows 路径写入用户 PATH
  if command -v cygpath >/dev/null 2>&1; then
    WINBIN="$(cygpath -w "$BIN")"
    ALREADY="$(powershell -NoProfile -Command "[Environment]::GetEnvironmentVariable('PATH','User')" 2>/dev/null || true)"
    if [ -n "$ALREADY" ] && echo "$ALREADY" | grep -qiF "$WINBIN"; then
      echo "==> Windows 用户 PATH 已包含 $WINBIN"
    else
      if powershell -NoProfile -Command "[Environment]::SetEnvironmentVariable('PATH', [Environment]::GetEnvironmentVariable('PATH','User') + ';$WINBIN', 'User')" 2>/dev/null; then
        echo "==> 已把 $WINBIN 加入 Windows 用户 PATH（重开终端后生效）"
      else
        echo "!!  无法自动修改 Windows PATH，请手动把以下目录加入用户 PATH："
        echo "    $WINBIN"
      fi
    fi
  fi
fi

# --- 验证 ---
echo "==> 验证安装"
"$BIN/agys" --version
echo
echo "安装完成！运行 agys doctor 检查环境，或直接 agys add 添加第一个帐号"
echo "（首次 add 会自动把你当前已登录的帐号保存为第一个帐号）"
