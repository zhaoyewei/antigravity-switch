#!/usr/bin/env bash
# 卸载 agys 安装产物（保留 ~/.agy-accounts 里的帐号数据）
#   curl -fsSL https://raw.githubusercontent.com/OWNER/antigravity-switch/main/uninstall.sh | bash
set -euo pipefail

DEST="${AGYS_INSTALL_DIR:-$HOME/.agys}"
IS_WINDOWS=0
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;; esac
DISPLAY="$DEST"
# 内部文件操作统一用 MSYS 风格路径（避免 Windows 盘符路径被删除策略拒绝）
if [ "$IS_WINDOWS" = "1" ]; then DEST="$(cygpath -u "$DEST")"; fi
BIN="$DEST/bin"

# 同一目录的三种写法，用于匹配历史版本写进启动文件的 PATH 行
WINBIN=""; WINBIN_MIX=""
if [ "$IS_WINDOWS" = "1" ] && command -v cygpath >/dev/null 2>&1; then
  WINBIN="$(cygpath -w "$BIN")"
  WINBIN_MIX="$(cygpath -m "$BIN")"
fi

BLOCK_BEGIN="# >>> agys installer >>>"
BLOCK_END="# <<< agys installer <<<"

echo "==> 卸载 $DISPLAY（帐号数据 ~/.agy-accounts 保留）"
if [ -d "$DEST" ]; then rm -rf "$DEST"; echo "==> 已删除 $DEST"; fi

# ---------------------------------------------------------------- 清理 shell 启动文件
# 只摘掉安装器写的标记块（含老版本留下的两种写法），不动用户自己的行。
strip_block() {  # $1 = 启动文件
  local f="$1" shown
  [ -f "$f" ] || return 0
  case "$f" in "$HOME"/*) shown="~/${f#"$HOME"/}" ;; *) shown="$f" ;; esac
  if grep -qF "$BLOCK_BEGIN" "$f" 2>/dev/null; then
    awk -v b="$BLOCK_BEGIN" -v e="$BLOCK_END" '
      index($0, b) == 1 { skip = 1; next }
      index($0, e) == 1 { skip = 0; next }
      !skip { print }
    ' "$f" > "$f.agys-tmp"
    mv "$f.agys-tmp" "$f"
    echo "==> 已清理 $shown 中的 agys PATH 配置"
    return 0
  fi
  # 0.6 及更早版本：无条件追加的一行 export（没有标记块），
  # 路径写法有 POSIX（/c/Users/...）与 Windows（C:\Users\...）两种可能
  local pat="" cand
  for cand in "$BIN" "$WINBIN" "$WINBIN_MIX"; do
    [ -n "$cand" ] || continue
    if grep -qF "$cand:\$PATH" "$f" 2>/dev/null; then pat="$cand"; break; fi
  done
  if [ -n "$pat" ]; then
    grep -v -F "$pat:\$PATH" "$f" | grep -v -F "# added by agys installer" > "$f.agys-tmp" || true
    mv "$f.agys-tmp" "$f"
    echo "==> 已清理 $shown 中旧版的 PATH 行"
  fi
}

strip_block "$HOME/.bashrc"
strip_block "$HOME/.bash_profile"
strip_block "$HOME/.bash_login"
strip_block "$HOME/.profile"
strip_block "$HOME/.zshrc"

# ---------------------------------------------------------------- 清理系统级 PATH
if [ "${AGYS_SKIP_PATH:-0}" = "1" ] || [ "${AGYS_SKIP_WIN_PATH:-0}" = "1" ]; then
  echo "==> 跳过系统 PATH 清理（AGYS_SKIP_PATH / AGYS_SKIP_WIN_PATH=1）"
elif [ "$IS_WINDOWS" = "1" ]; then
  powershell -NoProfile -Command "
    \$p = [Environment]::GetEnvironmentVariable('PATH','User');
    if (\$p) {
      \$parts = \$p -split ';' | Where-Object { \$_ -and \$_ -ne '$WINBIN' };
      [Environment]::SetEnvironmentVariable('PATH', (\$parts -join ';'), 'User')
    }" 2>/dev/null && echo "==> 已从 Windows 用户 PATH 移除" \
    || echo "!! 无法自动修改 Windows PATH，请手动移除：$WINBIN"
fi

echo "卸载完成。重开终端后 agys 命令消失；如需删除帐号数据，请手动删除 ~/.agy-accounts（内含凭据）。"
