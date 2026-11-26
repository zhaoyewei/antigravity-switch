"""跨平台登录桩：模拟 agy 登录，把凭据写进 memory 后端与 google_accounts.json。

环境变量：AGYS_STUB_BLOB / AGYS_STUB_EMAIL / AGYS_MEMORY_FILE /
AGYS_GEMINI_HOME / AGYS_STUB_ARGS_FILE
"""
import base64
import json
import os
import sys

if "--version" in sys.argv:
    print("1.1.4-stub")
    sys.exit(0)

blob = os.environ["AGYS_STUB_BLOB"].encode("utf-8")
email = os.environ["AGYS_STUB_EMAIL"]
mem = os.environ["AGYS_MEMORY_FILE"]
gemini = os.environ["AGYS_GEMINI_HOME"]

os.makedirs(os.path.dirname(mem), exist_ok=True)
os.makedirs(gemini, exist_ok=True)
with open(mem, "w", encoding="utf-8") as f:
    json.dump({"blob": base64.b64encode(blob).decode("ascii")}, f)
with open(os.path.join(gemini, "google_accounts.json"), "w", encoding="utf-8") as f:
    json.dump({"active": email, "old": []}, f)

args_file = os.environ.get("AGYS_STUB_ARGS_FILE")
if args_file:
    with open(args_file, "w", encoding="utf-8") as f:
        json.dump(sys.argv[1:], f)

print(f"stub: logged in {email}")
sys.exit(0)
