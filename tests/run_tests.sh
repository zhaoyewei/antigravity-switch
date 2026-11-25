#!/bin/bash
# agys 沙箱全流程测试（不触碰真实凭据，凭据条目用独立测试 target）
set -u
cd "$(dirname "$0")"

WS="$(pwd -W 2>/dev/null || pwd)/.."
T="$WS/.t"
PY="env -u PYTHONPATH python3"
TS=$(date +%s)
TARGET="agys-test-$TS"
PASS=0; FAIL=0

check() { # check <描述> <实际> <期望>
  if [ "$2" = "$3" ]; then PASS=$((PASS+1)); echo "  ok: $1";
  else FAIL=$((FAIL+1)); echo "  FAIL: $1  实际=[$2] 期望=[$3]"; fi
}
contains() { # contains <描述> <文本> <子串>
  if echo "$2" | grep -qF "$3"; then PASS=$((PASS+1)); echo "  ok: $1";
  else FAIL=$((FAIL+1)); echo "  FAIL: $1 (未找到: $3)"; fi
}

export AGYS_HOME="$T/home"
export AGYS_GEMINI_HOME="$T/gemini"
export AGYS_CRED_TARGET="$TARGET"
export AGYS_AGY_BIN="$WS/tests/stub.bat"
export AGYS_PROCESS_NAMES=""
export AGYS_STUB_TARGET="$TARGET"
export AGYS_STUB_GEMINI_HOME="$T/gemini"
export AGYS_STUB_ARGS_FILE="$T/args.json"

AGYS="$PY $WS/agys.py"
BLOB_ALICE='{"auth_method":"oauth","token":{"refresh_token":"ALICE-RT-1","email":"alice@gmail.com"}}'
BLOB_ALICE2='{"auth_method":"oauth","token":{"refresh_token":"ALICE-RT-2","email":"alice@gmail.com"}}'
BLOB_BOB='{"auth_method":"oauth","token":{"refresh_token":"BOB-RT-1","email":"bob@gmail.com"}}'
BLOB_CHARLIE='{"auth_method":"oauth","token":{"refresh_token":"CHARLIE-RT-1","email":"charlie@gmail.com"}}'

cred() { env -u PYTHONPATH AGYS_STUB_TARGET="$TARGET" python3 "$WS/tests/read_test_cred.py"; }
ga() { cat "$T/gemini/google_accounts.json" 2>/dev/null || echo ABSENT; }

rm -rf "$T"; mkdir -p "$T/home" "$T/gemini"

echo "== 1. add alice（首次，无已有登录） =="
AGYS_STUB_EMAIL=alice@gmail.com AGYS_STUB_BLOB="$BLOB_ALICE" $AGYS add alice
contains "add 提示添加成功" "$($AGYS list 2>&1)" "alice"
contains "凭据库已写入 alice blob" "$(cred)" "ALICE-RT-1"
contains "google_accounts active=alice" "$(ga)" "alice@gmail.com"

echo "== 2. add bob（已有 alice 登录，应先保存 alice） =="
AGYS_STUB_EMAIL=bob@gmail.com AGYS_STUB_BLOB="$BLOB_BOB" $AGYS add bob
contains "add bob 成功" "$($AGYS list 2>&1)" "bob"
check "当前凭据 = bob" "$(cred)" "$BLOB_BOB"
contains "ga active=bob" "$(ga)" "bob@gmail.com"

echo "== 3. list / current =="
OUT=$($AGYS list)
contains "list 含 alice" "$OUT" "alice"
contains "list 含 bob" "$OUT" "bob"
if echo "$OUT" | grep -q '^\* *bob'; then PASS=$((PASS+1)); echo "  ok: list 标记当前"; else FAIL=$((FAIL+1)); echo "  FAIL: list 标记当前"; fi
OUT=$($AGYS current)
contains "current 显示 bob" "$OUT" "bob"
contains "current 显示活跃邮箱" "$OUT" "bob@gmail.com"

echo "== 4. use alice（切换） =="
$AGYS use alice
check "凭据切到 alice" "$(cred)" "$BLOB_ALICE"
contains "ga 切到 alice" "$(ga)" "alice@gmail.com"
OUT=$($AGYS current); contains "vault 当前=alice" "$OUT" "alice"

echo "== 5. 模拟后台 token 刷新（alice 的 token 被进程刷新成 RT-2）再切走 =="
env -u PYTHONPATH AGYS_STUB_TARGET="$TARGET" AGYS_STUB_GEMINI_HOME="$T/gemini" \
  AGYS_STUB_EMAIL=alice@gmail.com AGYS_STUB_BLOB="$BLOB_ALICE2" python3 "$WS/tests/login_stub.py" >/dev/null
$AGYS use bob
check "切换后凭据=bob" "$(cred)" "$BLOB_BOB"
contains "alice profile 已回收刷新后的 RT-2" \
  "$(cat "$T/home/profiles/alice/profile.json")" "ALICE-RT-2"

echo "== 6. as alice -- -p 'hello world'（切换+参数透传） =="
rm -f "$T/args.json"
AGYS_STUB_EMAIL=alice@gmail.com AGYS_STUB_BLOB="$BLOB_ALICE2" $AGYS as alice -- -p hello world
check "agy 收到透传参数" "$(cat "$T/args.json" 2>/dev/null)" '["-p", "hello", "world"]'
check "as 后凭据=alice(RT-2)" "$(cred)" "$BLOB_ALICE2"

echo "== 7. as 当前帐号（无需切换，直接启动） =="
rm -f "$T/args.json"
AGYS_STUB_EMAIL=alice@gmail.com AGYS_STUB_BLOB="$BLOB_ALICE2" $AGYS as alice -p again
check "同帐号 as 透传参数" "$(cat "$T/args.json" 2>/dev/null)" '["-p", "again"]'

echo "== 8. export / import =="
$AGYS export "$T/export.json"
contains "导出文件含 alice" "$(cat "$T/export.json")" "alice"
contains "导出文件含迁移警告" "$(cat "$T/export.json")" "迁移用途"
contains "导出文件含 RT-2" "$(cat "$T/export.json")" "ALICE-RT-2"
AGYS_HOME="$T/home2" $AGYS import "$T/export.json" > /dev/null
OUT=$(AGYS_HOME="$T/home2" $AGYS list)
contains "导入后 home2 有 alice" "$OUT" "alice"
contains "导入后 home2 有 bob" "$OUT" "bob"
OUT=$(AGYS_HOME="$T/home2" $AGYS current)
contains "导入不自动切换" "$OUT" "当前帐号（vault）: 无"

echo "== 9. 自动收编未纳管登录（charlie） =="
env -u PYTHONPATH AGYS_STUB_TARGET="$TARGET" AGYS_STUB_GEMINI_HOME="$T/gemini" \
  AGYS_STUB_EMAIL=charlie@gmail.com AGYS_STUB_BLOB="$BLOB_CHARLIE" python3 "$WS/tests/login_stub.py" >/dev/null
OUT=$($AGYS use bob 2>&1)
contains "自动收编提示" "$OUT" "已把当前登录保存为帐号 'charlie'"
contains "list 含 charlie" "$($AGYS list)" "charlie"
check "切换后凭据=bob" "$(cred)" "$BLOB_BOB"

echo "== 10. remove（非当前 / 当前） =="
$AGYS remove alice
OUT=$($AGYS list); if echo "$OUT" | grep -qF "alice"; then echo "  FAIL: alice 仍在"; FAIL=$((FAIL+1)); else echo "  ok: alice 已删除"; PASS=$((PASS+1)); fi
$AGYS remove bob
check "删除当前帐号后凭据清除" "$(cred)" "ABSENT"
OUT=$($AGYS current); contains "vault 当前=无" "$OUT" "当前帐号（vault）: 无"

echo "== 11. 错误处理 =="
OUT=$($AGYS use nobody 2>&1); contains "未知帐号报错" "$OUT" "agys: 错误"
OUT=$($AGYS import "$T/nonexist.json" 2>&1); contains "导入文件不存在报错" "$OUT" "文件不存在"

echo
echo "===== 结果: PASS=$PASS FAIL=$FAIL ====="
[ $FAIL -eq 0 ]
