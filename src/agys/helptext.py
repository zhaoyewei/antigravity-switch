"""内置帮助与补全用的纯文本数据。

单独成文件的原因：这些字符串有两三屏长，混在命令实现里会把逻辑冲淡；
补全脚本还要复用 `COMMANDS`。
"""

COMMANDS = (
    "auto add list current use as switch run ls alias tag rename remove rm export "
    "import log stats watch layout doctor version update init status whoami logout "
    "info default prompt completion backup restore check proxy history tui help ids"
).split()

TOPICS = {
    "commands": """常用命令
  agys                   按额度自动挑帐号并启动 agy（= agys auto）
  agys auto --status     查看各帐号的额度 / 可用性
  agys init              首次引导：检查/安装 agy，收录当前登录
  agys add [名字]        添加一个帐号（自动保存当前登录，再走浏览器登录）
  agys list              列出帐号（* = 当前）
  agys use <帐号>        切换帐号
  agys as <帐号> [参数]  切换并以该帐号启动 agy，参数透传
  agys status            一行状态概览
  agys whoami            输出当前活跃邮箱（适合脚本）
  agys tui               交互式选择帐号并切换（use 省略帐号也会进入）
  agys history           查看会话历史（所有帐号共用同一份，不按帐号分区）
  agys info <帐号>       查看帐号详情与 token 有效期
  agys stats             帐号使用统计（切换次数 / 最后活跃）
  agys watch             持续监控额度，当前帐号异常时提醒（--once 单轮）
  agys tag <帐号> <标签> 打标签；auto --tag <标签> 在子集内选号
  agys prompt            输出当前帐号（shell 提示符集成）
  agys logout            登出但保留所有帐号
  agys doctor            环境自检；--fix 自动修复
  agys completion bash   生成 shell 补全脚本
  agys backup / restore  完整备份与恢复

完整参考：docs/COMMANDS.md""",
    "workflows": """典型流程
  第一次        curl -fsSL .../install.sh | bash && agys init
  加第二个号    agys add work      （浏览器登录后自动生效）
  日常用        agys               （自动挑额度最多的帐号并启动）
  指定帐号      agys use work  /  agys as work -p "review this diff"
  看额度        agys auto --status
  盯额度        agys watch         （当前帐号异常时提醒，Ctrl+C 停止）
  查看当前      agys status  /  agys whoami
  换机器        agys export → 新机 agys import xxx.json → agys use <id>
  整机备份      agys backup → ~/.agy-accounts/backups/…tar.gz
  升级          agys update  /  agys check""",
    "troubleshooting": """排障
  切换不生效    先 agys doctor；布局会自动适配，仍报错看 agys layout --discover
  切换被拒绝    有 agy 进程在跑；用 --close-all 自动关闭后切换，或手动退出
  凭据未纳管    agys current 会标红；下次 use/add 会自动收录
  找不到 agy    agys init 会自动用官方脚本安装；也可设置 AGYS_AGY_BIN
  auto 选错号    agys auto --status 看探测结果；--offline 只看缓存
  IDE 显示旧号  CLI 与 IDE 共享凭据，IDE 窗口执行 Developer: Reload Window
  token 被轮换  切换前会把刷新后的 token 回收进对应 profile，无需手动处理

更多：docs/TROUBLESHOOTING.md""",
    "env": """环境变量
  AGYS_HOME            vault 目录（默认 ~/.agy-accounts）
  AGYS_INSTALL_DIR     安装目录（默认 ~/.agys；二进制与源码共用）
  AGYS_GEMINI_HOME     agy 配置目录（默认 ~/.gemini）
  AGYS_AGY_BIN         agy 二进制路径（也可写 "python stub.py" 做测试）
  AGYS_AGY_INSTALL_CMD 自定义 agy 安装命令
  AGYS_NO_AUTO_INSTALL=1  关闭 agy 自动安装
  AGYS_NO_ENCRYPT=1      本地 vault 明文（不推荐，仅迁移用）
  AGYS_BACKEND=memory    测试后端，不碰真实凭据
  AGYS_PROCESS_NAMES     自定义进程名列表
  AGYS_PROXY             一次性指定代理（覆盖配置文件），如 http://127.0.0.1:7890
  AGYS_NO_PROXY=1        本次不注入代理（临时直连）
  AGYS_AUTO_FASTFAIL     auto 判定「启动即失败」的秒数（默认 20，仅影响提示措辞）
  AGYS_AUTO_OFFLINE=1     auto 只用额度缓存，不联网探测
  AGYS_USE_SOURCE=1      强制源码安装（需要 Python），不下载免 Python 二进制
  AGYS_BIN_URL / AGYS_BIN_SHA256 / AGYS_ASSET  自定义二进制下载地址 / 校验和 / 产物名
  AGYS_REQUIRE_BINARY=1  禁止回退源码，拿不到二进制就报错
  --json                结构化输出，便于脚本集成""",
    "auto": """auto 模式
  裸 `agys` 就是 auto：不指定帐号，按额度挑一个，切换后启动 agy。

  选号依据（优先级从高到低）
    1. 帐号状态：可用 > 额度未知 > 已用尽 > 登录失效
    2. 剩余额度百分比（有配额包时才有数字）
    3. 最久没被切换过的优先（多号轮换更均衡）

  免费帐号没有配额包，接口只返回 403，所以拿不到百分比。
  这类帐号用「健康探针」判定可用性，状态显示为「额度未知」。

  额度用光怎么办
    agy 非零退出时（无论启动瞬间还是会话中途，只处理已退出的会话、
    绝不中途打断）都会探测该帐号是否 429；确认是额度问题就提醒，
    自动换下一个帐号重试；不是额度问题就原样返回真实错误。

  常用开关
    agys auto --status        看所有帐号的探测结果
    agys auto --dry-run       只说会选谁，不动任何东西
    agys auto --offline       只用 5 分钟内的缓存
    agys auto --no-launch     只切换，不启动 agy
    agys auto --tag work      只在打了 work 标签的帐号里选
    agys auto -- -p "hi"      -- 之后的参数透传给 agy""",
    "security": """安全模型
  本地 vault 加密：Windows DPAPI / macOS·Linux SHAKE256+HMAC，密钥 0600
  导出文件是明文（迁移用途），默认落在 ~/.agy-accounts/exports/
  备份 tar.gz 含加密后的凭据与密钥，请按敏感文件保管
  切换有事务日志，崩溃后下次启动自动回滚
  auto 的额度探测只读：拿 refresh_token 换 access_token 发查询请求，
  不写凭据库、不改 agy 文件；结果缓存在 ~/.agy-accounts/quota.json
  报告漏洞请看 SECURITY.md，不要公开 issue""",
}

COMPLETION = {
    "bash": """# bash: 加到 ~/.bashrc
_agys_complete() {
  local cur cmds ids
  cur="${COMP_WORDS[COMP_CWORD]}"
  cmds="%s"
  ids="$(agys ids 2>/dev/null)"
  COMPREPLY=( $(compgen -W "$cmds $ids" -- "$cur") )
}
complete -F _agys_complete agys
""" % " ".join(COMMANDS),
    "zsh": """#compdef agys
# zsh: 存为 _agys 并放到 fpath 中
_agys() {
  local -a cmds ids
  cmds=(%s)
  ids=(${(f)"$(agys ids 2>/dev/null)"})
  _describe 'agys' cmds
  _describe 'accounts' ids
}
compdef _agys agys
""" % " ".join(COMMANDS),
    "fish": """# fish: 存为 ~/.config/fish/completions/agys.fish
complete -c agys -f
complete -c agys -n '__fish_use_subcommand' -a '%s'
complete -c agys -n '__fish_seen_subcommand_from use as switch run info alias rename remove rm default' -a '(agys ids 2>/dev/null)'
""" % " ".join(COMMANDS),
    "powershell": """# PowerShell: 加到 $PROFILE
Register-ArgumentCompleter -Native -CommandName 'agys' -ScriptBlock {
  param($wordToComplete, $commandAst, $cursorPosition)
  $cmds = @(%s)
  $ids = (agys ids 2>$null) -split "`n"
  ($cmds + $ids) | Where-Object { $_ -like "$wordToComplete*" } |
    ForEach-Object { [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_) }
}
""" % ", ".join("'%s'" % c for c in COMMANDS),
}
