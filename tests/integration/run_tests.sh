#!/usr/bin/env bash
# 跨平台集成测试：全程使用 memory 后端，绝不触碰真实的 OS 凭据库。
set -u
cd "$(dirname "$0")/../.." || exit 1
ROOT="$(pwd -W 2>/dev/null || pwd)"
STUB="$ROOT/tests/integration/login_stub.py"
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
T="$ROOT/.test-sandbox"
PASS=0; FAIL=0

check() {
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "  ok: $1";
  else FAIL=$((FAIL+1)); echo "  FAIL: $1  实际=[$2] 期望=[$3]"; fi
}
contains() {
  if echo "$2" | grep -qF "$3"; then PASS=$((PASS+1)); echo "  ok: $1";
  else FAIL=$((FAIL+1)); echo "  FAIL: $1 (未找到: $3)"; fi
}
not_contains() {
  if echo "$2" | grep -qF "$3"; then FAIL=$((FAIL+1)); echo "  FAIL: $1 (不应包含: $3)";
  else PASS=$((PASS+1)); echo "  ok: $1"; fi
}
# 安装脚本内部统一用 MSYS 风格路径（Git Bash 下是 /c/... 而不是 C:/...），
# 断言 PATH 内容前先归一化
posix_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -u "$1"; else printf '%s' "$1"; fi
}

export PYTHONPATH="$ROOT/src"
export AGYS_HOME="$T/home"
export AGYS_GEMINI_HOME="$T/gemini"
export AGYS_MEMORY_FILE="$T/home/memory_credential.json"
export AGYS_STUB_MEMORY_FILE="$AGYS_MEMORY_FILE"
export AGYS_STUB_GEMINI_HOME="$T/gemini"
export AGYS_STUB_ARGS_FILE="$T/args.json"
export AGYS_STUB_ENV_FILE="$T/stub-env.json"
export AGYS_BACKEND=memory
export AGYS_PROCESS_NAMES=""
export AGYS_AGY_BIN="$PY $STUB"
AGYS="$PY -m agys"

BLOB_ALICE='{"auth_method":"oauth","token":{"refresh_token":"ALICE-RT-1","email":"alice@gmail.com"}}'
BLOB_ALICE2='{"auth_method":"oauth","token":{"refresh_token":"ALICE-RT-2","email":"alice@gmail.com"}}'
BLOB_BOB='{"auth_method":"oauth","token":{"refresh_token":"BOB-RT-1","email":"bob@gmail.com"}}'
BLOB_CHARLIE='{"auth_method":"oauth","token":{"refresh_token":"CHARLIE-RT-1","email":"charlie@gmail.com"}}'

mem() { cat "$AGYS_MEMORY_FILE" 2>/dev/null || echo ABSENT; }
mem_blob() { "$PY" -c "import json,base64,sys; d=json.load(open(sys.argv[1])); print(base64.b64decode(d['blob']).decode())" "$AGYS_MEMORY_FILE"; }
exp_blob() { "$PY" -c "import json,base64,sys; d=json.load(open(sys.argv[1])); print(base64.b64decode(d['accounts'][0]['credential_b64']).decode())" "$1"; }
login() { AGYS_STUB_BLOB="$2" AGYS_STUB_EMAIL="$3" $PY "$STUB" "$1" >/dev/null; }

rm -rf "$T"; mkdir -p "$T/home" "$T/gemini"

echo "== 1. add（两个帐号） =="
AGYS_STUB_BLOB="$BLOB_ALICE" AGYS_STUB_EMAIL=alice@gmail.com $AGYS add >/dev/null
AGYS_STUB_BLOB="$BLOB_BOB" AGYS_STUB_EMAIL=bob@gmail.com $AGYS add bob >/dev/null
contains "list 含 alice" "$($AGYS list)" "alice"
contains "list 含 bob" "$($AGYS list)" "bob"
contains "活跃凭据=bob" "$(mem_blob)" "BOB-RT-1"

echo "== 2. use + 读回验证 =="
$AGYS use alice >/dev/null
contains "凭据切到 alice" "$(mem_blob)" "ALICE-RT-1"
contains "--json current 一致" "$($AGYS --json current)" '"consistent": true'

echo "== 3. token 轮换回收（切走后导出应含 RT-2） =="
login noop "$BLOB_ALICE2" alice@gmail.com
$AGYS use bob >/dev/null
EXPORT="$T/home/exports/agys-export-$(date +%F).json"
$AGYS export >/dev/null
contains "alice 的刷新后 token 已回收" "$(exp_blob "$EXPORT")" "ALICE-RT-2"

echo "== 4. as 参数透传 + flags 重排 =="
rm -f "$T/args.json"
AGYS_STUB_BLOB="$BLOB_ALICE2" AGYS_STUB_EMAIL=alice@gmail.com $AGYS as alice -- -p hello world >/dev/null
check "透传参数" "$(cat "$T/args.json")" '["-p", "hello", "world"]'
rm -f "$T/args.json"
AGYS_STUB_BLOB="$BLOB_BOB" AGYS_STUB_EMAIL=bob@gmail.com $AGYS as bob --no-guard -p again >/dev/null
check "--no-guard 被 agys 吃掉，未透传" "$(cat "$T/args.json")" '["-p", "again"]'

echo "== 5. alias / rename / log / layout / doctor =="
$AGYS alias alice work primary >/dev/null
contains "list 显示别名" "$($AGYS list)" "work,primary"
$AGYS use work >/dev/null
contains "别名可切换" "$(mem_blob)" "ALICE-RT-2"
$AGYS rename alice alice-main >/dev/null
contains "rename 生效" "$($AGYS list)" "alice-main"
contains "审计日志有记录" "$($AGYS log -n 50)" "switch"
contains "layout 输出指纹" "$($AGYS layout)" "fingerprint"
contains "doctor 输出加密方式" "$($AGYS doctor)" "加密"
contains "version" "$($AGYS version)" "0.7.0"
contains "--json doctor" "$($AGYS --json doctor)" '"ok": true'

echo "== 5b. 扩展命令（status / whoami / ids / info / default / 别名 / help / 补全 / 自检修复 / 备份 / 登出） =="
contains "status 显示当前帐号" "$($AGYS status)" "alice-main"
check "whoami 输出邮箱" "$($AGYS whoami)" "alice@gmail.com"
contains "ids 含别名" "$($AGYS ids)" "work"
contains "info 显示凭据大小" "$($AGYS info)" "凭据大小"
$AGYS default alice-main >/dev/null
contains "default 生效" "$($AGYS default)" "alice-main"
contains "别名 ls" "$($AGYS ls)" "alice-main"
contains "别名 switch" "$($AGYS switch alice-main 2>&1)" "已切换到"
contains "help 主题" "$($AGYS help security)" "安全模型"
contains "completion bash" "$($AGYS completion bash)" "_agys_complete"
contains "doctor --fix" "$($AGYS doctor --fix)" "自动修复"
BK="$T/integration-backup.tar.gz"
$AGYS backup "$BK" >/dev/null
if [ -f "$BK" ]; then PASS=$((PASS+1)); echo "  ok: backup 生成文件"; else FAIL=$((FAIL+1)); echo "  FAIL: backup 未生成文件"; fi
$AGYS logout >/dev/null
check "logout 清除活跃凭据" "$(mem)" "ABSENT"
$AGYS use alice-main >/dev/null
contains "use 恢复活跃凭据" "$(mem_blob)" "ALICE-RT-2"

echo "== 5c. 代理配置（只注入子进程，不改系统代理） =="
contains "proxy 初始未配置" "$($AGYS proxy)" "未配置代理"
$AGYS proxy set 127.0.0.1:1 >/dev/null 2>&1
contains "proxy set 生效" "$($AGYS proxy show)" "127.0.0.1:1"
if [ -f "$AGYS_HOME/config.json" ]; then PASS=$((PASS+1)); echo "  ok: 配置文件已生成"; else FAIL=$((FAIL+1)); echo "  FAIL: 配置文件未生成"; fi
contains "proxy 来源为 config" "$($AGYS --json proxy)" '"source": "config"'
$AGYS proxy clear >/dev/null
contains "proxy clear 生效" "$($AGYS proxy)" "未配置代理"

# 黑盒验证：代理确实注入到 agy 子进程，clear 后不再注入
$AGYS proxy set 127.0.0.1:7890 >/dev/null 2>&1
rm -f "$T/stub-env.json"
AGYS_STUB_BLOB="$BLOB_ALICE2" AGYS_STUB_EMAIL=alice@gmail.com $AGYS as alice-main >/dev/null 2>&1
contains "agy 子进程拿到 HTTPS_PROXY" "$(cat "$T/stub-env.json" 2>/dev/null)" "127.0.0.1:7890"
contains "agy 子进程 NO_PROXY 含 localhost" "$(cat "$T/stub-env.json" 2>/dev/null)" "localhost"
$AGYS proxy clear >/dev/null
rm -f "$T/stub-env.json"
AGYS_STUB_BLOB="$BLOB_ALICE2" AGYS_STUB_EMAIL=alice@gmail.com $AGYS as alice-main >/dev/null 2>&1
not_contains "clear 后不再注入配置的代理" "$(cat "$T/stub-env.json" 2>/dev/null)" "127.0.0.1:7890"

echo "== 5d. history（会话历史，跨帐号共享） =="
"$PY" - "$AGYS_GEMINI_HOME" << 'PYEOF'
import os, sqlite3, sys
base = os.path.join(sys.argv[1], "antigravity-cli")
os.makedirs(os.path.join(base, "conversations"), exist_ok=True)
c = sqlite3.connect(os.path.join(base, "conversation_summaries.db"))
c.execute("create table conversation_summaries (conversation_id text, title text,"
          " preview text, step_count integer, last_modified_time datetime,"
          " workspace_uris text, project_id text, status text)")
c.execute("insert into conversation_summaries values (?,?,?,?,?,?,?,?)",
          ("itest-1", "", "集成测试会话", 3, "2026-07-18 02:28:54+00:00",
           '["file:///C:/Users/zhao"]', "", ""))
c.commit(); c.close()
d = sqlite3.connect(os.path.join(base, "conversations", "itest-1.db"))
d.execute("create table steps (idx integer primary key, step_type integer,"
          " status integer, render_info blob, step_payload blob)")
d.execute("insert into steps values (0,14,0,null,?)", (b"Search for codex",))
d.commit(); d.close()
PYEOF
contains "history 列出会话" "$($AGYS history)" "集成测试会话"
contains "history 说明共享" "$($AGYS history)" "所有帐号共用"
contains "history 搜索命中" "$($AGYS history --search 集成)" "itest-1"
contains "history show 步骤摘要" "$($AGYS history show itest-1)" "Search for codex"
$AGYS history export "$T/hist.json" >/dev/null
contains "history 导出 json" "$(cat "$T/hist.json")" '"kind": "history"'
$AGYS history export "$T/hist.md" --format md --detail >/dev/null
contains "history 导出 md" "$(cat "$T/hist.md")" "所有帐号共用"

echo "== 5e. TUI 非交互保护 =="
contains "use 无参回落到默认帐号" "$($AGYS use 2>&1)" "已切换到"
contains "tui 非交互下报错" "$($AGYS tui 2>&1)" "用法：agys use"

echo "== 5f. import 冲突策略 =="
$AGYS export "$T/conflict.json" >/dev/null
contains "on-conflict skip" "$($AGYS import "$T/conflict.json" --on-conflict skip)" "跳过"
contains "on-conflict rename" "$($AGYS import "$T/conflict.json" --on-conflict rename)" "alice-main-2"
contains "JSON 报告策略" "$($AGYS --json import "$T/conflict.json" --on-conflict skip)" '"on_conflict": "skip"'

echo "== 6. export / import（校验和） =="
contains "导出含校验和" "$(cat "$EXPORT")" '"checksum"'
AGYS_HOME="$T/home2" AGYS_MEMORY_FILE="$T/home2/memory_credential.json" \
  $AGYS import "$EXPORT" >/dev/null
contains "导入到新 vault" "$(AGYS_HOME="$T/home2" AGYS_MEMORY_FILE="$T/home2/memory_credential.json" $AGYS list)" "alice"
"$PY" - "$EXPORT" << 'PYEOF'
import json, sys
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
d["accounts"][0]["email"] = "tampered@evil.com"
open(p, "w", encoding="utf-8").write(json.dumps(d))
PYEOF
if $AGYS import "$EXPORT" >/dev/null 2>&1; then FAIL=$((FAIL+1)); echo "  FAIL: 篡改文件应被拒绝"; else PASS=$((PASS+1)); echo "  ok: 篡改文件被拒绝"; fi

echo "== 7. 布局自动发现与自动兼容 =="
contains "layout --discover 列出候选" "$($AGYS layout --discover)" "候选布局"
OUT=$(AGYS_CRED_TARGET="gemini:changed" $AGYS use bob 2>&1)
contains "环境变量指定的位置直接采纳" "$OUT" "环境变量"
contains "切换仍然成功" "$OUT" "已切换到"
contains "layout --adopt 可执行" "$($AGYS layout --adopt)" "布局"
AGYS_CRED_TARGET="gemini:changed" $AGYS use bob --allow-layout-change >/dev/null
PASS=$((PASS+1)); echo "  ok: --allow-layout-change 仍可强制放行"

echo "== 7b. auto 选号（离线，不联网不启动） =="
contains "auto --status 列出帐号" "$($AGYS auto --status --offline)" "额度"
contains "auto --status 标注额度未知" "$($AGYS auto --status --offline)" "额度未知"
contains "auto --status 说明免费帐号无配额包" "$($AGYS auto --status --offline)" "免费帐号"
contains "auto --dry-run 报告会选中谁" "$($AGYS auto --dry-run --offline)" "会选中"
contains "auto --dry-run JSON 带 choice" "$($AGYS --json auto --dry-run --offline)" '"choice"'
contains "auto 状态表覆盖全部帐号" "$($AGYS auto --status --offline)" " bob "
contains "裸 agys --status 等价 auto" "$($AGYS --status --offline)" "额度"
contains "裸 agys 等同 auto（空 vault 提示加号）" \
  "$(AGYS_HOME="$T/home3" AGYS_MEMORY_FILE="$T/home3/memory_credential.json" \
    $AGYS 2>&1)" "还没有任何帐号"

echo "== 8. remove（确认 + 登出） =="
if $AGYS remove bob >/dev/null 2>&1; then FAIL=$((FAIL+1)); echo "  FAIL: 无 --yes 应拒绝"; else PASS=$((PASS+1)); echo "  ok: 无 --yes 被拒绝"; fi
$AGYS remove bob --yes >/dev/null
check "删除当前帐号后凭据清除" "$(mem)" "ABSENT"
contains "vault 当前=无" "$($AGYS current)" "当前帐号（vault）: 无"

echo "== 9. 错误处理 =="
contains "未知帐号报错" "$($AGYS use nobody 2>&1)" "找不到帐号"
contains "导入不存在文件报错" "$($AGYS import "$T/nope.json" 2>&1)" "无法读取导入文件"

echo "== 9b. 免 Python 二进制安装（离线，file:// 假二进制） =="
sha_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}
FAKE="$T/fake-agys"
printf '#!/bin/sh\necho "agys 0.7.0 (fake binary)"\n' > "$FAKE"
chmod +x "$FAKE"
FAKE_URL="file://$FAKE"
case "$FAKE" in [A-Za-z]:*) FAKE_URL="file:///$FAKE" ;; esac
BIN_HOME="$T/bin-home"
rm -rf "$BIN_HOME"
OUT=$(cd "$T" && AGYS_INSTALL_DIR="$BIN_HOME" AGYS_SKIP_PATH=1 \
  AGYS_BIN_URL="$FAKE_URL" AGYS_BIN_SHA256="$(sha_of "$FAKE")" \
  AGYS_ASSET="agys-test" bash "$ROOT/install.sh" 2>&1)
contains "下载二进制并校验 SHA-256" "$OUT" "SHA-256 校验通过"
contains "二进制安装验证 version" "$OUT" "0.7.0"
check "install-mode 标记为 binary" "$(cat "$BIN_HOME/install-mode")" "binary"
check "可执行文件已就位" "$(test -x "$BIN_HOME/bin/agys" && echo yes || echo no)" "yes"
contains "安装模式提示为 binary" "$OUT" "binary 模式"
# 校验和不匹配时必须拒绝（强制二进制、不允许回退）
if (cd "$T" && AGYS_INSTALL_DIR="$T/bin-home2" AGYS_SKIP_PATH=1 \
    AGYS_BIN_URL="$FAKE_URL" AGYS_BIN_SHA256="deadbeef" AGYS_ASSET="agys-test" \
    AGYS_REQUIRE_BINARY=1 bash "$ROOT/install.sh" >/dev/null 2>&1); then
  FAIL=$((FAIL+1)); echo "  FAIL: SHA-256 不匹配应拒绝安装"
else
  PASS=$((PASS+1)); echo "  ok: SHA-256 不匹配不会误装"
fi
# 强制二进制模式且下载失败时必须明确失败（不悄悄装源码）
if (cd "$T" && AGYS_INSTALL_DIR="$T/bin-home3" AGYS_SKIP_PATH=1 \
    AGYS_BIN_URL="file:///nonexistent-agys-binary" AGYS_REQUIRE_BINARY=1 \
    AGYS_ASSET="agys-test" bash "$ROOT/install.sh" >/dev/null 2>&1); then
  FAIL=$((FAIL+1)); echo "  FAIL: AGYS_REQUIRE_BINARY=1 下载失败应报错"
else
  PASS=$((PASS+1)); echo "  ok: AGYS_REQUIRE_BINARY=1 下载失败会报错"
fi

echo "== 9c. 安装后 shell 启动文件（新终端直接可用，不需要 source） =="
blk_count() { grep -cF '# >>> agys installer >>>' "$1" 2>/dev/null || true; }
install_rc() {  # $1 = 假 HOME
  (cd "$T" && HOME="$1" AGYS_INSTALL_DIR="$1/.agys" AGYS_SKIP_WIN_PATH=1 \
    AGYS_BIN_URL="$FAKE_URL" AGYS_BIN_SHA256="$(sha_of "$FAKE")" AGYS_ASSET="agys-test" \
    bash "$ROOT/install.sh" 2>&1)
}
RC_HOME="$T/rc-home"
rm -rf "$RC_HOME"; mkdir -p "$RC_HOME"
OUT=$(install_rc "$RC_HOME")
check "写入 ~/.bashrc" "$(blk_count "$RC_HOME/.bashrc")" "1"
check "自建 ~/.bash_profile（Git Bash / macOS 登录 shell 读它）" "$(blk_count "$RC_HOME/.bash_profile")" "1"
contains "提示新终端会自动生效" "$OUT" "新开一个终端则自动生效"
# 真正模拟登录 shell：Git Bash 窗口与 macOS Terminal 都走这条链（旧版只写 .bashrc 所以失效）
LOGIN_PATH=$(HOME="$RC_HOME" bash --login -c 'printf "%s" "$PATH"' 2>/dev/null || true)
contains "登录 shell 的 PATH 含安装目录" "$LOGIN_PATH" "$(posix_path "$RC_HOME/.agys/bin")"
# 交互式非登录 shell（Linux 终端 / VS Code / WSL）读 ~/.bashrc
NONLOGIN_PATH=$(HOME="$RC_HOME" bash -i -c 'printf "%s" "$PATH"' 2>/dev/null || true)
contains "非登录交互 shell 的 PATH 含安装目录" "$NONLOGIN_PATH" "$(posix_path "$RC_HOME/.agys/bin")"
# 重复安装不能把 PATH 行堆叠
install_rc "$RC_HOME" >/dev/null
check "重复安装不重复写入" "$(blk_count "$RC_HOME/.bashrc")" "1"
# 已有 ~/.profile 但没有任何登录启动文件时，写进 ~/.profile（不新建 .bash_profile）
RC_HOME2="$T/rc-home2"
rm -rf "$RC_HOME2"; mkdir -p "$RC_HOME2"
printf 'export AGYS_TEST_PROFILE=1\n' > "$RC_HOME2/.profile"
install_rc "$RC_HOME2" >/dev/null
check "尊重已有的 ~/.profile" "$(blk_count "$RC_HOME2/.profile")" "1"
check "不额外创建 .bash_profile" "$(test -f "$RC_HOME2/.bash_profile" && echo yes || echo no)" "no"
# 卸载要把标记块摘干净，且不能误删用户自己的行
(cd "$T" && HOME="$RC_HOME" AGYS_INSTALL_DIR="$RC_HOME/.agys" AGYS_SKIP_WIN_PATH=1 \
  bash "$ROOT/uninstall.sh" >/dev/null 2>&1)
check "卸载后 ~/.bashrc 已无 agys 配置" "$(blk_count "$RC_HOME/.bashrc")" "0"
check "卸载后 ~/.bash_profile 已无 agys 配置" "$(blk_count "$RC_HOME/.bash_profile")" "0"
(cd "$T" && HOME="$RC_HOME2" AGYS_INSTALL_DIR="$RC_HOME2/.agys" AGYS_SKIP_WIN_PATH=1 \
  bash "$ROOT/uninstall.sh" >/dev/null 2>&1)
check "卸载后 ~/.profile 已无 agys 配置" "$(blk_count "$RC_HOME2/.profile")" "0"
contains "卸载保留用户原有行" "$(cat "$RC_HOME2/.profile" 2>/dev/null)" "AGYS_TEST_PROFILE"

echo
echo "===== 结果: PASS=$PASS FAIL=$FAIL ====="
rm -rf "$T"
[ $FAIL -eq 0 ]
