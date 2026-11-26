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
contains "version" "$($AGYS version)" "0.4.0"
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

echo "== 7. 布局变化拒绝切换 =="
OUT=$(AGYS_CRED_TARGET="gemini:changed" $AGYS use bob 2>&1)
contains "拒绝切换提示" "$OUT" "存储布局变化"
AGYS_CRED_TARGET="gemini:changed" $AGYS use bob --allow-layout-change >/dev/null
PASS=$((PASS+1)); echo "  ok: --allow-layout-change 可放行"

echo "== 8. remove（确认 + 登出） =="
if $AGYS remove bob >/dev/null 2>&1; then FAIL=$((FAIL+1)); echo "  FAIL: 无 --yes 应拒绝"; else PASS=$((PASS+1)); echo "  ok: 无 --yes 被拒绝"; fi
$AGYS remove bob --yes >/dev/null
check "删除当前帐号后凭据清除" "$(mem)" "ABSENT"
contains "vault 当前=无" "$($AGYS current)" "当前帐号（vault）: 无"

echo "== 9. 错误处理 =="
contains "未知帐号报错" "$($AGYS use nobody 2>&1)" "找不到帐号"
contains "导入不存在文件报错" "$($AGYS import "$T/nope.json" 2>&1)" "无法读取导入文件"

echo
echo "===== 结果: PASS=$PASS FAIL=$FAIL ====="
rm -rf "$T"
[ $FAIL -eq 0 ]
