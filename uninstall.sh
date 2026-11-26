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

echo "==> 卸载 $DISPLAY（帐号数据 ~/.agy-accounts 保留）"
if [ -d "$DEST" ]; then rm -rf "$DEST"; echo "==> 已删除 $DEST"; fi

if [ "$IS_WINDOWS" = "1" ]; then
  WINBIN="$(cygpath -w "$DEST/bin")"
  powershell -NoProfile -Command "
    \$p = [Environment]::GetEnvironmentVariable('PATH','User');
    if (\$p) {
      \$parts = \$p -split ';' | Where-Object { \$_ -and \$_ -ne '$WINBIN' };
      [Environment]::SetEnvironmentVariable('PATH', (\$parts -join ';'), 'User')
    }" 2>/dev/null && echo "==> 已从 Windows 用户 PATH 移除" \
    || echo "!! 无法自动修改 Windows PATH，请手动移除：$WINBIN"
else
  RC="$HOME/.bashrc"
  if [ -f "$RC" ]; then
    grep -v -F "$DEST/bin" "$RC" | grep -v -F "# added by agys installer" > "$RC.tmp" || true
    mv "$RC.tmp" "$RC"
    echo "==> 已清理 ~/.bashrc 中的 PATH 行"
  fi
fi
echo "卸载完成。如需删除帐号数据，请手动删除 ~/.agy-accounts（内含凭据）。"
