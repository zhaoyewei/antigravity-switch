# 排障指南

先跑一遍 `agys doctor`。它不修改任何东西，会列出平台、路径、加密方式、凭据库、
布局指纹、每个 profile 的状态、运行中进程与所有警告。

```bash
agys doctor
agys --json doctor        # 结构化输出，便于贴给脚本或 issue
agys doctor --fix         # 自检后自动修复常见问题
```

> 贴 `doctor` 输出到 issue 前，请先删掉其中的本机路径、邮箱等个人信息。

---

## 快速索引

| 现象 | 直接看 |
|---|---|
| 切换被拒绝，提示有 agy 进程在跑 | [进程守卫](#1-切换被拒绝检测到运行中的-antigravity-进程) |
| 提示「存储布局变化」 | [布局指纹](#2-提示存储布局变化-切换被拒绝) |
| 切换成功但 IDE 还显示旧邮箱 | [IDE 显示](#3-切换后-ide-仍显示旧邮箱) |
| 找不到 agy / 自动安装失败 | [agy 安装](#4-找不到-agy--自动安装失败) |
| `current` 说活跃凭据「未纳管」 | [未纳管凭据](#5-活跃凭据未纳入管理) |
| 导入报校验和不匹配 | [导入校验](#6-导入报校验和不匹配) |
| 导出的 token 看起来是旧的 | [token 轮换](#7-token-被轮换--导出内容不是最新) |
| `remove` / `restore` 要求确认 | [交互确认](#8-remove--restore-提示需要显式---yes) |
| 升级后 profile 解密失败 | [加密与迁移](#9-加密-迁移-密钥相关问题) |
| 曾经崩溃 / 断电 | [事务日志](#10-存在未完成事务) |
| macOS / Linux 行为与 Windows 不同 | [平台差异](#11-平台差异) |
| 想彻底重来 | [完全重置](#12-完全重置) |

---

## 1. 切换被拒绝：检测到运行中的 Antigravity 进程

**原因**：后台 agy 会在 access token 刷新时把**旧帐号**的凭据写回 OS 凭据库，
静默覆盖你刚完成的切换。所以默认拒绝执行，而不是给你一个「假成功」。

**解决**（任选）：

```bash
agys use work --close-all    # 自动关闭进程 → 切换 → 尽力重开（推荐）
agys use work --no-guard     # 强制切换，风险自负
```

或先手动退出所有 agy / Antigravity 窗口再切换。用 `agys status` 可以看到当前进程数。
同一帐号多开 agy 窗口不受影响（`agys as` 遇到当前帐号会跳过切换直接启动）。

---

## 2. 提示「存储布局变化」，切换被拒绝

**原因**：`agys` 会为 agy 的存储布局（版本、平台、凭据目标、各路径）生成指纹。
agy 升级换了存储位置时，继续按旧位置写入会写到失效位置——看起来成功，实际没生效。

**解决**：先确认你确实升级过 agy，然后对比并接受新布局：

```bash
agys layout                                # 对比当前探测值与缓存指纹
agys use work --allow-layout-change         # 接受变化并更新指纹
```

如果没升级过 agy 却出现这个提示，先跑 `agys doctor` 检查是否改过
`AGYS_CRED_TARGET` / `AGYS_GEMINI_HOME` 等环境变量，或改过 `AGYS_BACKEND`。

> 只读命令（`list` / `current` / `doctor` / `export`）永远可用，不受布局变化拦截。

---

## 3. 切换后 IDE 仍显示旧邮箱

CLI 与 IDE 共享同一份凭据，但 IDE 窗口可能缓存了显示状态。
在 IDE 里执行 `Developer: Reload Window`。`agys use` 成功时也会主动给出这个提示。

---

## 4. 找不到 agy / 自动安装失败

`init` / `add` / `use` / `as` 会自动检测 agy；缺失时调用官方安装脚本：

| 平台 | 官方命令 |
|---|---|
| macOS / Linux | `curl -fsSL https://antigravity.google/cli/install.sh \| bash` |
| Windows PowerShell | `irm https://antigravity.google/cli/install.ps1 \| iex` |
| Windows CMD | `curl -fsSL https://antigravity.google/cli/install.cmd -o install.cmd && install.cmd && del install.cmd` |

安装失败通常是网络 / 代理问题，不影响已有数据。可以：

```bash
AGYS_AGY_INSTALL_CMD="你的安装命令" agys init   # 用自定义命令（如走代理）
AGYS_AGY_BIN=/path/to/agy agys init              # 直接指向已有二进制
AGYS_NO_AUTO_INSTALL=1 agys list                 # 禁止任何命令触发安装
```

安装脚本执行完仍找不到 agy 时，**重开终端**刷新 PATH 再试。
文档：<https://antigravity.google/docs/getting-started?tab=cli>

---

## 5. 活跃凭据「未纳入管理」

`agys current` / `doctor` 标记活跃凭据未匹配任何已存帐号，通常是你直接在 agy 里登录了新帐号。
下次执行 `agys use` 或 `agys add` 时，agys 会自动把当前登录收录为一个新帐号，无需手动处理。
也可以立即运行 `agys init` 收录。

---

## 6. 导入报「校验和不匹配」

导出文件带 SHA-256 `checksum`，任何手工修改（哪怕只改邮箱）都会导致校验失败，这是防误改的设计。

```bash
agys import backup.json                 # 正常
agys import backup.json --no-verify     # 确认文件可信、必须跳过校验时
```

注意：跳过校验只绕过完整性检查，不会绕过凭据格式校验。

---

## 7. token 被轮换 / 导出内容不是最新

Google 会轮换 refresh token。`agys` 在**每次切换前**都会把当前活跃凭据回收进对应 profile，
因此导出的总是最新 token。如果你在 agy 里登录后没有做过任何 `agys` 切换，
可以先 `agys use <当前帐号>` 或 `agys add` 触发一次回收，再导出。

---

## 8. `remove` / `restore` 提示需要显式 `--yes`

破坏性操作在非交互终端（脚本、CI、`--json`）下无法弹确认，必须显式加 `--yes`：

```bash
agys remove old --yes
agys restore backups/agys-backup-....tar.gz --yes
```

---

## 9. 加密、迁移、密钥相关问题

- **v0.1 升级上来**：v0.2 起 profile 默认加密，旧明文 profile 会在命令启动时渐进迁移；
  也可 `agys doctor --fix` 一次迁移完。
- **macOS / Linux**：密钥文件是 `$AGYS_HOME/.vault.key`（权限 `0600`）。
  密钥丢失或被覆盖后，已加密的 profile 无法解密——请务必把 `backup` 的 tar.gz 一起备份。
- **`AGYS_NO_ENCRYPT=1`**：明文模式，仅用于迁移 / 兼容，不要长期使用；`doctor` 会给出警告。
- **Windows**：使用 DPAPI，密钥绑定当前 Windows 用户；换用户或重装系统后无法解密，
  同样需要靠备份恢复。

`agys doctor --fix` 会顺带收紧目录权限、移除损坏的 vault 索引项。

---

## 10. 存在未完成事务

切换是分两步写（凭据 → 显示状态 → vault），中间会写加密事务日志 `pending.json`。
若进程在两步之间崩溃，下次启动任意 `agys` 命令都会自动回滚到切换前的状态并给出提示。
也可以 `agys doctor --fix` 主动清理。

---

## 11. 平台差异

| 平台 | 凭据后端 | 备注 |
|---|---|---|
| Windows | Credential Manager 条目 `gemini:antigravity` | 实机验证；凭据是 OS 级全局唯一条目，**无法真并发使用多个帐号** |
| macOS | Keychain（`security` CLI） | 最佳努力实现，欢迎实机反馈 |
| Linux | 文件式 token `~/.gemini/antigravity-cli/antigravity-oauth-token` | 最佳努力实现，欢迎实机反馈 |

Linux 文件式凭据理论上支持 `HOME` 重定向做多帐号并发，目前尚未实现，见 [ROADMAP.md](../ROADMAP.md)。

---

## 12. 完全重置

```bash
agys backup                       # 先备份，别直接删
agys logout                       # 清除活跃凭据
# 然后手动删除 ~/.agy-accounts/
```

删除后所有已保存帐号都会消失，需要重新 `agys init` / `agys import`。

---

---

## 13. 代理相关

**agy 还是连不上 Google**：先 `agys proxy show` 确认代理已生效（来源应为 `config` 或
`env:AGYS_PROXY`），再 `agys proxy test` 确认端口可连。注意 agys 只给自己启动的进程注入代理；
你手动在别处打开的 agy 不受影响，需要 `AGYS_PROXY=http://127.0.0.1:7890 agy`。

**代理对 agys 自身无效**：`socks5://` 只对 agy 与 curl 生效；`agys check` / `update --check`
的版本查询走 urllib，不支持 socks，会自动退回直连。改用 http 代理即可全程生效。

**清除后仍然走代理**：`proxy clear` 只是停止注入，子进程会继承你 shell 里已有的
`HTTPS_PROXY` / `ALL_PROXY` 等变量。要彻底直连，用 `AGYS_NO_PROXY=1 agys as <帐号>`，
或在干净的 shell 里运行。

**Windows 上安装 agy 仍然超时**：agys 已为 `install.ps1` 额外设置 `DefaultWebProxy`
（该命令不读环境变量代理）；仍失败时可用 `AGYS_AGY_INSTALL_CMD` 指定自定义安装命令。

**代理地址写错端口**：`agys proxy set` 会立即做 TCP 连通性检测并告警，但配置仍会保存；
改对后重新 `agys proxy set` 即可覆盖。

---

还解决不了？请开 issue 并附上（**已脱敏**的）`agys doctor` 输出、
`agys --json doctor`、`agys version`、操作系统与 agy 版本。
安全相关的问题请按 [SECURITY.md](../SECURITY.md) 私下报告。
