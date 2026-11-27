# Changelog

## 0.7.0

**429 兜底覆盖会话中途（最被需要的改进）**
- agy 非零退出时——无论启动瞬间还是会话中途撞 429——都探测确认真实状态：
  是额度问题就提醒并自动换下一个帐号重试；不是就原样返回真实错误
- 依旧**绝不主动打断正在跑的会话**，只处理已退出的；换号重试是新会话，
  原会话历史仍可在 `agys history` 查看
- `AGYS_AUTO_FASTFAIL` 窗口只影响提示措辞（「启动即失败」 vs 「会话中途退出」），
  换号与否一律由探测确认
- 最后一个帐号也用尽时，提醒额度重置 / 重新登录，不再含糊地说「换下一个」
- `agys as` 退出非零后顺手探测：确认额度用尽会提醒一句「运行 agys 可自动换号」

**额度曲线（订阅帐号）**
- `retrieveUserQuota` 返回的 `resetTime` 现在被解析并缓存；额度用尽的订阅帐号
  在 `auto --status` 表里标注「MM-DD HH:MM 重置」（本地时间），`--json` 输出带 `reset` 字段
- `quota.reset_epoch / fmt_reset`：ISO 字符串与 epoch 秒/毫秒都能解析

**新命令：监控 / 统计 / 标签 / 提示符**
- `agys watch [--interval N] [--low 比例] [--once]`：持续监控所有帐号额度；
  状态有变化才说话，当前帐号耗尽 / 需重登 / 剩余低于阈值时提醒 + 终端响铃。
  `--once` 单轮适合 cron；持续模式不支持 `--json`（单轮支持）
- `agys stats`：各帐号切换次数 / 失败次数 / 最后切换时间 / 添加时间（审计日志，纯只读；
  已删除帐号也带出并标注）
- `agys tag [帐号] [标签...] [--remove]`：打标签；不带参数列出全部标签。
  `agys auto --tag work` 只在子集内选号（只探测打标帐号）；`list` / `info` 显示标签
- `agys prompt [格式串]`：输出当前帐号（`{id}` / `{email}`），供 starship / oh-my-posh /
  PS1 集成；只读 vault 不碰凭据库，没有帐号时输出 `none`

**token 过期预警**
- `info` 显示 token 剩余有效期（如「（3 小时）」）并在已过期 / 48 小时内过期时警告；
  `--json` 增加 `token_remaining_sec`
- `doctor` 对每个 profile 解析 token 过期时间：已过期 / 48 小时内过期的帐号进入警告列表，
  诊断输出附带每个帐号的 token 过期时间

**内部改进**
- `_token_expiry` 从 commands/accounts.py 上移到 identity.py（`token_expiry / expiry_dt /
  expiry_age / expiry_human`），info 与 doctor 共用
- vault：profile 与帐号元数据新增 `tags` 字段（保存 / 读取 / 修复索引时均保持）
- 新命令分组：`stats` / `watch` 进 diag，`prompt` 进 misc，`tag` 进 accounts

**免 Python 安装（单文件二进制）**
- 新增 `scripts/build_binary.py`：PyInstaller 打包单文件可执行程序（内置 Python 运行时），
  产物名由新增的 `installer.asset_name()` 统一决定（`agys-<os>-<arch>[.exe]`，不含版本号），
  同时产出 `.sha256`；构建后自动冒烟 `version`
- `release.yml` 改为多平台矩阵（Windows x86_64 / macOS arm64·x86_64 / Linux x86_64·arm64），
  逐平台构建 + 校验产物名 + 冒烟，并连同 sdist/wheel 一起附到 GitHub Release
- `install.sh` 默认优先下载 Release 二进制（**不需要 Python**），自动校验 `.sha256`；
  产物不可用 / 校验失败时回退源码安装（需 Python 3.9+）；`AGYS_REQUIRE_BINARY=1` 可禁止回退
- 新增 `install.ps1`（Windows PowerShell 一键安装，无需 Python / Git Bash，支持 TLS 1.2 与代理）与
  `uninstall.ps1`；两者都只删带安装标记的目录，帐号数据 `~/.agy-accounts` 不动
- `agys update` 会读 `~/.agys/install-mode`：二进制安装的 Windows 用户改跑 `install.ps1`，
  其余沿用 `install.sh`（它本身会优先下载新二进制）
- 新增 `installer.py`（产物命名 / Release URL / 安装模式标记 / 升级脚本选择），纯逻辑可单测；
  `install.sh` 的 SHA-256 计算改为 stdin 读取，规避 Git Bash Windows 临时路径转义前缀问题

**安装后立刻可用（修 PATH 只写 `.bashrc` 的老问题）**
- 以前只往 `~/.bashrc` 追加 PATH，但 Git Bash 与 macOS Terminal 起的是**登录** shell，
  读的是 `~/.bash_profile` / `~/.bash_login` / `~/.profile`，永远读不到 `.bashrc`，
  于是每开一个窗口都得手敲 `source ~/.bashrc`。现在按 bash 的加载顺序同时覆盖
  非登录（`~/.bashrc`）与登录（上述三者，都没有则自建 `~/.bash_profile` 并级联
  `.profile` / `.bashrc`）两条链，装了 zsh 再写 `~/.zshrc`
- PATH 段改为带 `# >>> agys installer >>>` 标记的幂等块：同一份 rc 反复 source 不会把
  PATH 越堆越长；卸载按标记精确摘除，不再用 `grep -v` 误删用户自己的行（也兼容清理
  0.6 及更早版本追加的无标记 `export PATH=...`）
- 安装结束打印一行 `export PATH="<安装目录>:$PATH"`，用于「已经开着的那个窗口」
  （脚本是子进程，任何安装器都改不了父 shell 的环境变量）
- `install.ps1`：`AGYS_SKIP_PATH=1` 时不再顺手改当前会话的 `$env:PATH`；通过 `irm | iex`
  运行时当前 PowerShell 会话立即可用，作为脚本文件运行时给出同样的单行提示；
  `uninstall.ps1` 也会清理 Git Bash / WSL 的启动文件
- 新增 `AGYS_SKIP_WIN_PATH=1`：只跳过 Windows 注册表 PATH，仍写入 shell 启动文件（供测试）
- 集成测试新增「9c. 安装后 shell 启动文件」12 项：登录 / 非登录 shell 真的能解析到
  `agys`、重复安装不堆叠、尊重已有的 `~/.profile`、卸载后清理干净且保留用户原有行

**从 agy 用户文件夹导入（免重新登录）**
- `agys import <文件夹>` 现在也能用：把某个帐号用过的 agy 数据目录整份拷出来
  （例如 `~/.gemini` 改名成 `~/.agy-account_userA`），一条命令纳管，不再走浏览器登录
- 只读扫描该目录（深度 ≤ 3，跳过 `cache/`、`logs/`、`bin/` 等），**按内容识别**凭据、
  不依赖文件名，支持三种形态：agy 原生 blob（`{"auth_method":"oauth","token":{…}}`，
  即 Windows/macOS 凭据库与 Linux 令牌文件的形态）、Gemini CLI 的 `oauth_creds.json`
  （字段换算成 agy 形态：`expiry_date` 毫秒 → agy 的 ISO 写法）、以及顺带识别
  `google_accounts.json` 提供邮箱 / active 显示
- 邮箱优先从 `google_accounts.json` 取，缺了就从 `id_token` 的 JWT 载荷里取，
  保证同一帐号重复导入能认出来（不会出现两个 id 指向同一身份）
- 新增 `--name`（导入后的 id）、`--dry-run`（只报告扫到哪个文件、什么形态、会导入成什么）、
  `--use`（导入后立即切换，受进程守卫与布局校验约束）
- 同一身份再次导入默认**更新已有帐号**而不是新建；`--on-conflict rename` 才并存；
  一个文件夹只导一个帐号，同目录里还有别的凭据时明确提示未采用的是哪一份
- 找不到凭据时的报错直接列出「需要哪种文件、常见的三种位置」；文件夹里放的是
  agys 导出文件时，提示改用 `agys import <那个文件>`
- 新增 `folderimport.py`（纯逻辑，可单测）与 `identity.email_from_jwt()`

**测试**
- 单测新增 24 个用例：429 中途兜底（模拟长会话时钟）、resetTime 解析与展示、
  stats / prompt / tag / watch / 过期预警；另新增 `test_installer.py` 18 个用例
  （产物命名 / URL / 模式标记 / update 分派）、`test_folder_import.py` 20 个用例
  （三种凭据形态识别 / 过期时间换算 / 同身份去重 / 冲突策略 / dry-run）：
  单测 179 passed + 1 skipped，集成 98 项全通过
- 集成测试新增「9b. 免 Python 二进制安装」：用 `file://` 假二进制离线验证下载、SHA-256 校验、
  `install-mode` 标记与版本自检，以及校验失败 / 强制二进制失败的拒绝路径
- 集成测试新增「9c. 安装后 shell 启动文件」与「9d. 从 agy 用户文件夹导入」：
  后者用假的 `oauth_creds.json` 走完 导入 → 切换 → 活跃凭据校验 全链路
- CI 增加 `bash -n` 安装脚本语法检查与 Windows PowerShell 解析器语法检查

## 0.6.0

**auto 自动选号：裸 `agys` 就是它**
- 不带任何子命令时自动按额度与可用性挑帐号：`agys` = `agys auto`
- 排序：`ok` > `额度未知` > `已用尽` > `需重新登录` > `探测失败`；同档按剩余额度降序，
  再按「最久没切换过」优先，轮换更均衡；已耗尽的帐号跳过并告警
- `--status`（看额度表）/ `--dry-run`（只报告选谁）/ `--offline`（只用缓存）/
  `--no-launch`（只切换）；`--` 之后原样透传给 agy
- 非交互终端只切换不启动，绝不把终端交给一个看不见的进程
- 全部帐号「探测失败」（多为网络 / 代理问题）时不直接拒绝，按顺序尝试并告警

**额度用光自动换号**
- agy 在 `AGYS_AUTO_FASTFAIL`（默认 20）秒内非零退出时，先探测该帐号真实状态，
  **确认**是 429 / 额度耗尽才写标记、提醒、换下一个帐号重试
- 退出码 `130` / `2`（用户取消）与超时退出不换号，避免打断真实错误

**额度探测（`quota.py`）**
- 走 Antigravity 配额接口 `retrieveUserQuota`：有订阅的帐号可拿到 `remainingFraction` 并显示百分比
- 免费帐号返回 `403 SUBSCRIPTION_REQUIRED`（无配额包，非无额度），退回零成本健康探针
  `countTokens`，确认可用后标记「额度未知」，**不编造百分比**
- 分层判定：200+配额包 → `ok`/`exhausted`；429 → `exhausted`；401 → `auth`；其余 → `error`
- 结果缓存 5 分钟于 `~/.agy-accounts/quota.json`；探测只读，只换 token 不写凭据库
- 探测请求复用 `agys proxy` 的代理配置（`proxy.open_request()`）

**代码整理（纯重构，行为不变）**
- `cli.py` 从 868 行缩到薄入口（parser + 分派 + 统一错误处理），实现按域拆到
  `commands/`：`accounts` / `switching` / `migrate` / `diag` / `hist` / `misc` / `net`
- 跨命令流程抽到 `runtime.py`：`ensure_ready` / `guard_processes` / `switch_to` /
  `switch_if_needed` / `launch` / `pick_account` / `resolve_or_pick`
- 帮助文本抽到 `helptext.py`（纯数据）；删除 `extra.py`（内容已全部迁出）
- 修复：Windows 上 `stdin` 重定向到 NUL 时 `isatty()` 误报 True，导致 `agys use`
  在脚本里被误判成交互场景；现在统一用 `tui.supported()`（同时校验 stdout）

**测试**
- 新增 `tests/unit/test_quota.py`（20 个用例，全部 mock 网络，绝不联网）
- 集成测试新增「7b. auto 选号（离线）」段；单测 105 passed + 1 skipped，集成 67 项全通过

## 0.5.0

**布局自动发现 + 自动兼容（不做数据迁移）**
- 结构指纹只包含决定「往哪写」的字段（平台 / 凭据后端 / 凭据条目名 /
  `google_accounts.json` 路径 / 受控 token 路径）；`agy_version` 只记录不参与判断，
  **agy 升级不再打断切换**
- 指纹变化或「有活跃凭据但状态文件不见了」时，自动在候选位置搜索：
  Windows 用 `CredEnumerateW` 枚举凭据条目、扫描同名状态文件与受控 token 路径
- 三道采纳关卡：新指纹确实不同 / 新位置确实有数据 / 新旧身份一致（比对 token 的 email、sub）
- 采纳只更新指针（进程级路径覆盖），**不搬文件、不改格式**；任何一步无法确认就拒绝切换
- 新命令：`agys layout --discover`（列出候选）、`agys layout --adopt`（手动采纳）
- 环境变量显式指定的位置被视为用户配置，直接采纳而不再触发拒绝
- 覆盖值会做存活检查，陈旧指针自动丢弃，避免工具被历史配置带偏

**`agys history`：会话历史（跨帐号共享）**
- 只读解析 `conversation_summaries.db` + `conversations/*.db`，不修改任何 agy 文件
- `history` 列表 / `--search` / `--workspace` / `--no-orphans` / `show <id 前缀>` /
  `export --format json|md --detail`
- 从 protobuf blob 中提取可读摘要作为步骤描述（正文无法逐字还原）
- 摘要库里没有记录的孤立会话也会被扫出来，用 `?` 标记

**交互式 TUI**
- 新命令 `agys tui`；`agys use` 在交互终端下省略帐号时也会进入
- 方向键移动、`1-9` 跳转、`Enter` 切换、`q` 取消；显示当前帐号与活跃凭据
- 纯标准库（Windows `msvcrt` / Unix `termios`），不引入 `curses`；非 TTY 明确报错

**导入冲突策略**
- `import --on-conflict ask|skip|overwrite|rename`，默认 `overwrite` 保持兼容
- `rename` 自动排号（`alice` → `alice-2` → `alice-3`…），`ask` 在非交互终端下报错
- 输出与 `--json` 结果区分「新导入 / 更新 / 跳过 / 重命名」

**其它**
- Linux 凭据后端完成实机验证（README 已更新平台状态表）
- `status` 增加会话历史概览；`doctor` 增加布局指纹不一致与状态文件缺失的警告
- 文档：README / COMMANDS / TROUBLESHOOTING / ROADMAP 全面同步

## 0.4.0

**代理支持（只影响 agys 启动的子进程，不改系统代理）**
- 新命令：`agys proxy set <url>` / `show` / `clear` / `test`，支持 http / https / socks5
- 注入点：`add` / `as` 启动的 agy、`--close-all` 后重开的 agy、agy 安装脚本、
  `update`，以及 `check` / `update --check` 的版本查询
- 未配置代理时完全不注入，行为与之前一致
- `NO_PROXY` 自动追加 `localhost,127.0.0.1,::1`，避免本地 language server 被代理
- `AGYS_PROXY` 临时覆盖、`AGYS_NO_PROXY=1` 临时禁用
- 配置写入 `~/.agy-accounts/config.json`（0600），`show` 输出会对密码打码
- Windows 安装 agy 时额外设置 `DefaultWebProxy`（`irm` 不读环境变量代理）

## 0.3.0

面向公开发布的一轮打磨：更像一个正式 repo，也更好用。

**新命令**
- `init` 首次引导（自动检测 / 安装 agy 并收录当前登录）
- `status` 一行状态概览、`whoami` 输出活跃邮箱（脚本友好）、`ids` 列出所有 id 与别名
- `logout` 登出但保留帐号、`info <帐号>` 查看凭据详情与过期时间
- `default [帐号]` 查看 / 设置默认帐号（非交互下 `agys use` 省略帐号时回落到它）
- `completion bash|zsh|fish|powershell` 生成补全脚本
- `backup` / `restore` 完整备份恢复、`check` 版本与自检、`help <主题>` 内置帮助
- `doctor --fix` 自动修复：迁移明文 profile、回滚未完成事务、修复 vault 索引、收紧目录权限
- 命令别名：`ls` / `switch` / `run` / `rm`

**agy 自动安装**
- `init` / `add` / `use` / `as` 前自动检测 agy；缺失时用官方安装脚本安装
  （macOS·Linux `install.sh`、Windows `install.ps1` / `install.cmd`）
- 只读 / 诊断命令不触发安装；`AGYS_NO_AUTO_INSTALL=1` 可关闭，`AGYS_AGY_INSTALL_CMD` 可覆盖
- 安装成功后自动放行一次布局指纹变化

**工程与文档**
- 补齐 CONTRIBUTING / SECURITY / CODE_OF_CONDUCT / ROADMAP、docs、issue / PR 模板、
  release workflow、dependabot、Makefile、.editorconfig、pre-commit 配置
- README 重写为项目首页，移除个人环境排障内容

**修复**
- 修正 Unix 下文件锁解锁使用了不存在的常量（Linux / macOS 上 `agys use` 退出时会报错）
- 修复登出状态下 `agys whoami` 因空身份崩溃；身份解析函数现在容忍空值
- `restore` 在新版 Python 使用 `filter="data"` 安全解压，消除弃用警告
- 清理未使用的导入；`doctor` 的 `--fix` 正式接入参数解析

## 0.2.0

针对 v0.1.0"能跑但不敢用"的问题做了一次结构性重构。

**正确性闭环**
- 切换后读回凭据并校验身份，杜绝"假成功"；失败自动回滚
- 存储布局探测 + 指纹比对：agy 升级换存储位置时拒绝切换，不再静默写到失效位置
- 用 token 内的稳定身份（email / sub / refresh token 指纹）判定帐号，替代邮箱字符串匹配
- 加密事务日志 `pending.json`：两处写之间崩溃，下次启动自动回滚
- 登出态统一定义；`remove` 当前帐号同步清理活跃凭据与显示邮箱

**安全边界**
- 本地 vault 加密：Windows DPAPI；macOS/Linux SHAKE256 流密码 + HMAC-SHA256，密钥 0600
- 文件权限收紧（0600 / 0700，Windows 目录 ACL），兼容并渐进迁移 v0.1 明文 profile
- 导出默认落在 `~/.agy-accounts/exports/`，带 schema 版本与 SHA-256 校验和；导入校验
- 安装脚本支持 SHA-256 校验与包内版本标记检查；新增 `agys update` / `uninstall.sh`

**体验与并发**
- 进程托管：列出 PID，`--close-all` 自动关闭后切换并尽力重开；`--no-guard` 强制跳过
- `alias` / `rename` 补齐别名写入路径；`remove` 需要确认（或 `--yes`）
- 全局 `--json` 输出；`use` 无参数时的交互 picker；`agys log` 审计日志
- IDE 窗口仍显示旧邮箱时给出重载提示；`as` 的 agys flags 自动重排，`--` 后透传
- 新增 `layout` / `version` / `update` 命令

**工程化**
- 拆成 `src/agys/` 包 + 凭据后端抽象（windows / macos / linux / memory）
- pytest 单元测试 + 跨平台集成测试（memory 后端，不触碰真实凭据）
- GitHub Actions 三平台 × Python 3.9/3.11/3.13 矩阵
- `pyproject.toml`（`pip install` / `pipx install` 分发）、语义化版本

## 0.1.0

首个可用版本：Windows Credential Manager + `google_accounts.json` 原子替换、
token 回收、进程守卫、add/list/current/use/as/remove/export/import/doctor、
`curl | bash` 安装。
