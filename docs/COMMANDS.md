# 命令参考

```
agys [--json] <命令> [参数...]
agys [--json] [--status|--dry-run|--offline|--no-launch] ['--' agy 参数...]   # = agys auto
```

全局参数：

| 参数 | 作用 |
|---|---|
| `--json` | 以单个 JSON 对象输出，便于脚本集成；错误也以 JSON 返回 |
| `--version` | 打印版本并退出 |
| `-h` / `--help` | 帮助（也可 `agys <命令> --help`） |

内置离线帮助：`agys help [commands|workflows|troubleshooting|env|security|auto]`。

---

## 帐号标识

所有需要 `<帐号>` 的命令都接受以下任意一种（大小写不敏感）：

| 形式 | 示例 |
|---|---|
| 帐号 id | `work` |
| 邮箱 | `me@company.com` |
| 别名 | `primary` |
| 稳定身份 | `email:me@company.com` |
| id 的唯一前缀 | `wo`（仅当只匹配到一个帐号时） |

匹配到多个或零个会报错。用 `agys list` 查看详情、`agys ids` 拿到可直接用于补全的列表。

---

## 引导与日常

### `auto`（裸 `agys`）

不带任何子命令时就是 `auto`：按额度与可用性挑一个帐号切过去，然后启动 `agy`。

```bash
agys                                  # 挑帐号 → 切换 → 启动 agy
agys --status                         # 只列出各帐号的额度与可用性
agys --dry-run                        # 只报告"会选中谁"，不切换不启动
agys --no-launch                      # 只切换，不启动 agy
agys --offline --status               # 只用缓存（5 分钟 TTL），不联网
agys -- --model gemini-2.5-pro        # `--` 之后原样透传给 agy
agys auto --status                    # 显式写法，等价
```

| 参数 | 作用 |
|---|---|
| `--status` | 打印帐号表（ID / 状态 / 邮箱 / 说明），并标注「额度未知」的原因 |
| `--dry-run` | 同上，外加「会选中谁」；不写凭据、不启动进程 |
| `--offline` | 不联网探测，只用 `~/.agy-accounts/quota.json` 的缓存 |
| `--no-launch` | 只完成切换，不启动 agy |
| `--close-all` / `--no-guard` / `--yes` / `--allow-layout-change` | 同其它切换类命令 |

**选号规则**：`ok` > `额度未知` > `已用尽` > `需重新登录` > `探测失败`；同档按剩余额度降序，
再按「最久没切换过」优先。已耗尽的帐号会被跳过并打印警告。
若**全部帐号都探测失败**（多为网络 / 代理问题），不会直接拒绝，而是按顺序尝试并给出警告。

**额度用光后自动换号**：agy 在 `AGYS_AUTO_FASTFAIL`（默认 20）秒内非零退出时，
会探测该帐号真实状态；确认是 429 / 额度耗尽才写标记、提醒、换下一个帐号重试。
退出码 `130` / `2`（用户取消）与超时退出都视为正常结束，不换号。

```bash
AGYS_AUTO_FASTFAIL=30 agys      # 放宽判定窗口（agy 启动较慢的机器）
agys < /dev/null                # 非交互环境：只切换，不启动 agy
```

### `init`

检测 agy 是否安装（缺失时用官方脚本自动安装），并把当前已登录的帐号收录为第一个帐号。
只读当前状态，不会启动登录流程。

```bash
agys init
```

### `add [名字] [--alias 别名]`

先保存当前活跃登录，再启动 `agy` 的浏览器登录流程；登录完成后自动把新凭据存为一个帐号并切换到它。
`--alias` 可重复指定多个别名。若登录的还是同一个帐号，只刷新其 token，不会创建重复项。

```bash
agys add
agys add work --alias primary --alias office
```

> `add` 会临时清除活跃凭据再唤起 agy 登录；若中途取消且未产生新登录，会自动恢复原帐号凭据。

### `list` / `ls`

列出所有帐号，`*` 标记当前帐号，并显示邮箱与别名。

### `use` / `switch <帐号>`

切换帐号。省略 `<帐号>` 时：交互终端进入 TUI 选择器；非交互 / `--json` 场景下若设置了默认帐号则切到默认帐号，否则明确报错。

```bash
agys use work
agys switch work --close-all
agys use                 # 打开 TUI 选择器
```

### `tui`

独立的交互式选择器：方向键移动、`1-9` 跳转、`Enter` 切换、`q` 取消。
纯标准库实现，不依赖 `curses`；非交互终端会直接报错。

### `as` / `run <帐号> [--] [agy 参数...]`

切换到指定帐号并以它启动 `agy`，后续参数原样透传。若目标已是当前活跃帐号，跳过切换直接启动。

```bash
agys as work
agys as work -p "review this diff"
agys as work -- --some-agy-flag value
```

`agys` 自身的 flag（`--no-guard` / `--close-all` / `--yes` / `--allow-layout-change` / `--json`）
写在帐号名前会被 agys 消费；`--` 之后的一切都传给 agy。

### `current`

显示 vault 记录的当前帐号、活跃凭据身份、`google_accounts.json` 的活跃邮箱，以及三者是否一致。

### `status`

一行概览：当前帐号、活跃身份、一致性、帐号数、运行中进程数、加密方式、agy 版本。

### `whoami`

只输出当前活跃邮箱，供脚本使用；未登录时返回非零退出码。

```bash
EMAIL="$(agys whoami)"
```

### `ids`

逐行输出所有 id 与别名，供 shell 补全与脚本使用。

### `logout`

清除活跃凭据与显示邮箱（相当于登出），但**保留所有已保存的帐号**。之后用 `agys use <id>` 即可重新登录。

---

## 帐号管理

| 命令 | 说明 |
|---|---|
| `alias <帐号> <别名...> [--remove]` | 添加别名；`--remove` 改为删除这些别名。别名与其它帐号 id 冲突时拒绝 |
| `rename <帐号> <新id>` | 重命名 id（同时迁移 profile 目录与 vault 索引） |
| `info [帐号]` | 显示邮箱、身份、别名、创建/更新时间、凭据字节数、token 过期时间、是否为默认帐号；省略帐号时用当前帐号 |
| `default [帐号]` | 省略参数时查看默认帐号；指定时设置 |
| `remove` / `rm <帐号> [--yes]` | 删除帐号；删除当前帐号会同时清除活跃凭据（登出）。需要确认，非交互环境须加 `--yes` |

```bash
agys alias work primary
agys alias work old-name --remove
agys rename work work-2026
agys info work
agys default work
agys remove old-account --yes
```

---

## 迁移与备份

### `export [路径]`

导出所有帐号为 JSON。缺省落在 `~/.agy-accounts/exports/agys-export-<日期>.json`。
文件包含 **明文** 登录凭据、`format` / `version` 字段与 SHA-256 `checksum`，仅供迁移使用。

```bash
agys export
agys export /tmp/migration.json
```

> 迁移完成后请删除导出文件；refresh token 会被 Google 轮换，两台机器同时使用同一份凭据会互相踢下线。

### `import <文件> [--no-verify] [--on-conflict ...]`

导入导出文件，校验 SHA-256（可用 `--no-verify` 跳过），兼容 v0.1 格式。
**导入不会自动切换**，需再执行 `agys use <id>`。

id 已存在时按 `--on-conflict` 处理：

| 取值 | 行为 |
|---|---|
| `overwrite`（默认） | 覆盖现有帐号，保持与旧版本一致 |
| `skip` | 保留现有帐号，跳过这一条 |
| `rename` | 换个不冲突的 id 并存（`alice` → `alice-2` → `alice-3`…） |
| `ask` | 逐个询问；非交互终端下会报错，可加 `--yes` 表示全部覆盖 |

```bash
agys import backup.json --on-conflict skip
agys import backup.json --on-conflict ask --yes
```

### `backup [路径]`

把整个 `~/.agy-accounts/` 打包为 tar.gz，缺省落在 `backups/`。
跳过 `backups/`、`__pycache__`、`.switch.lock`、`pending.json`、测试后端凭据文件。
备份内含加密凭据与密钥，按敏感文件保管。

### `restore <文件> [--yes]`

从备份恢复 vault、审计日志、密钥与所有 profile；会覆盖当前数据，需要确认。
恢复后请执行 `agys use <id>` 让活跃凭据与恢复后的 vault 对齐。

---

## 诊断与维护

| 命令 | 说明 |
|---|---|
| `doctor` | 完整环境自检：平台、路径、加密方式、agy 版本、凭据库、布局、各 profile、运行中进程、警告 |
| `doctor --fix` | 在自检后自动修复：迁移 v0.1 明文 profile、回滚未完成事务、修复 vault 索引（补入孤立 profile / 移除损坏项）、收紧目录权限 |
| `layout` | 显示当前 agy 存储布局探测结果与缓存指纹的差异 |
| `layout --discover` | 列出所有候选布局（凭据条目 / 状态文件 / token 路径），只读探测 |
| `layout --adopt` | 自动发现并采纳可用布局；没有更合适的候选时把当前布局记为基准 |
| `log [-n 数量]` | 查看 JSONL 审计日志（默认 20 条），只含元数据不含 token |
| `check` | 显示当前版本、查询仓库最新版本（离线时跳过）、快速自检提示数 |
| `version` | 显示版本 |
| `update [--check]` | 重新下载并运行安装脚本完成升级；`--check` 只查询最新版本 |

```bash
agys doctor
agys doctor --fix
agys layout --discover
agys check
agys update --check
```

---

## 会话历史

agy 的本地历史**不按帐号分区**：`~/.gemini/antigravity-cli/` 下的
`conversation_summaries.db`、`conversations/<uuid>.db`、`history.jsonl` 里
没有任何 account / email / user 字段，云端也没有会话列表接口。
所以切换帐号不会换出一套历史——所有帐号天然共用同一份。

`agys history` 只读，不修改任何 agy 文件。

| 用法 | 作用 |
|---|---|
| `history` | 列出所有会话（按最后修改时间倒序） |
| `history -n 50` | 只看最近 50 条 |
| `history --search 关键词` | 在标题 / preview / workspace / id 里过滤 |
| `history --workspace D:/work` | 按 workspace 路径过滤 |
| `history --no-orphans` | 隐藏摘要库里没有记录的孤立会话 |
| `history show <id 前缀>` | 会话详情 + 步骤摘要（`--steps N` 控制条数） |
| `history export <路径>` | 导出；`--format json\|md`、`--detail` 附带步骤摘要 |

```bash
agys history
agys history --search 论文
agys history show 5520
agys history export ~/Desktop/hist.md --format md --detail
```

输出里 `?` 标记表示该会话不在摘要库中、仅从会话文件推断（可能已被清理）。

列表字段来自 `conversation_summaries` 表；正文是 protobuf blob，无法逐字还原，
`show` / `export --detail` 给出的是从 blob 中提取的可读摘要（优先中文原文）。

---

## 代理

只影响 agys 启动的子进程，**不修改系统代理**。配置保存在 `~/.agy-accounts/config.json`（权限 0600）。

| 命令 | 说明 |
|---|---|
| `proxy show`（也是 `agys proxy` 的默认行为） | 显示当前生效的代理、来源（config / env）、NO_PROXY |
| `proxy set <url>` | 设置并立即测试连通性；支持 `http` / `https` / `socks5` |
| `proxy set <url> --no-proxy a,b` | 同时设置 NO_PROXY；`localhost,127.0.0.1,::1` 始终追加 |
| `proxy test [url]` | 只测 TCP 连通性 |
| `proxy clear` | 清除配置；不再注入，agy 继承父进程原有网络设置 |

```bash
agys proxy set 127.0.0.1:7890            # 自动补全为 http://
agys proxy set socks5://127.0.0.1:7890
agys proxy test
agys proxy clear
```

注入范围：`add` / `as` 启动的 agy、`--close-all` 后重开的 agy、agy 安装脚本、
`update`、`check`。未配置时不注入任何变量。

---

## 脚本与集成

### `completion <shell>`

生成补全脚本，支持 `bash` / `zsh` / `fish` / `powershell`。

```bash
agys completion bash >> ~/.bashrc
agys completion zsh > ~/.zsh/completions/_agys
agys completion fish > ~/.config/fish/completions/agys.fish
agys completion powershell >> $PROFILE
```

补全会把 `agys ids` 的输出作为帐号候选。

### `help [主题]`

| 主题 | 内容 |
|---|---|
| `commands` | 常用命令速查 |
| `workflows` | 首次使用、加号、切换、换机器、备份、升级的典型流程 |
| `troubleshooting` | 常见排障摘要 |
| `env` | 环境变量清单 |
| `security` | 安全模型摘要 |

---

## 切换类命令的通用 flag

`add` / `use` / `as` 支持：

| flag | 作用 |
|---|---|
| `--close-all` | 自动关闭运行中的 agy 进程后再切换，切换完尽力重开 |
| `--no-guard` | 不检测 / 不关闭进程，强制切换（风险自负） |
| `--yes` | 跳过交互确认 |
| `--allow-layout-change` | 跳过自动发现，直接把当前布局记为基准（确认 agy 换了位置时用） |

---

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `AGYS_HOME` | `~/.agy-accounts` | vault 目录 |
| `AGYS_GEMINI_HOME` | `~/.gemini` | agy 配置目录 |
| `AGYS_EXPORTS_DIR` | `$AGYS_HOME/exports` | 导出目录 |
| `AGYS_CRED_TARGET` | `gemini:antigravity` | Windows 凭据条目名 |
| `AGYS_CRED_USER` | `antigravity` | macOS Keychain account |
| `AGYS_AGY_BIN` | 自动探测 | agy 二进制；可写 `"python stub.py"` 形式的命令串做测试替身 |
| `AGYS_AGY_INSTALL_CMD` | 官方脚本 | 自定义 agy 安装命令 |
| `AGYS_NO_AUTO_INSTALL=1` | — | 关闭 agy 自动安装 |
| `AGYS_NO_ENCRYPT=1` | 关闭 | 本地 vault 明文（不推荐，仅迁移 / 兼容用） |
| `AGYS_BACKEND=memory` | `auto` | 测试后端，不碰真实凭据 |
| `AGYS_PROCESS_NAMES` | 平台相关 | 自定义进程名（逗号分隔；设为空串可禁用检测） |
| `AGYS_PROXY` | — | 一次性覆盖代理 URL（优先于配置文件） |
| `AGYS_NO_PROXY=1` | — | 本次不注入代理（临时直连） |
| `AGYS_GITHUB_OWNER` | `zhaoyewei` | `update` / `check` 使用的仓库 owner |
| `AGYS_INSTALL_URL` | 官方 install.sh | 自定义升级脚本 URL |

---

## 退出码

| 码 | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 可预期的错误（找不到帐号、校验失败、布局变化被拒绝、凭据错误等） |
| `2` | 命令行参数错误（argparse） |
| `130` | 用户 Ctrl+C 取消 |
| agy 自身的退出码 | `agys as` 会原样返回 agy 的退出码 |
