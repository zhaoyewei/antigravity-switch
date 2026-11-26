# antigravity-switch (`agys`)

[![CI](https://github.com/zhaoyewei/antigravity-switch/actions/workflows/ci.yml/badge.svg)](https://github.com/zhaoyewei/antigravity-switch/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#跨平台支持)

**一条命令在多个 Google 帐号之间切换 Antigravity CLI（`agy`），不用反复登出登录。**

纯 Python 标准库实现、零运行时依赖，支持 Windows / macOS / Linux。
`agys` 把每个帐号的登录凭据快照到本地加密 vault，切换时原子替换并读回验证——
不是改配置骗过 UI，而是真正换掉 agy 读取的那份凭据。

> `agys` 管理的是本地 OAuth 登录凭据。使用前请先阅读 [安全模型](#安全模型)。

---

## 特性

| | |
|---|---|
| 🔐 **原子切换 + 读回验证** | 写回后重新读取凭据并校验身份，杜绝「假成功」；任一步失败自动回滚 |
| 🧬 **稳定身份判定** | 从 token 的 email / sub / refresh token 指纹识别帐号，邮箱变更或 token 轮换都不会认错 |
| 🛡️ **本地加密** | Windows DPAPI；macOS / Linux SHAKE256 流密码 + HMAC-SHA256，密钥文件 `0600` |
| 🚦 **进程守卫** | 检测运行中的 agy 进程，避免后台刷新把旧帐号写回；`--close-all` 可自动关闭并尽力重开 |
| 📐 **布局指纹** | agy 升级改变了存储位置时**拒绝切换**，不会静默写到失效位置 |
| 🩺 **自检与自愈** | `doctor` / `doctor --fix` / `layout` / `check`，出问题能定位也能修复 |
| 📦 **迁移友好** | `export` / `import`（SHA-256 校验和）、`backup` / `restore` |
| 🧰 **脚本友好** | 全局 `--json`、`whoami`、`ids`、`status`、bash/zsh/fish/PowerShell 补全 |
| 🧭 **自动安装 agy** | 需要 agy 的命令会自动检测；未安装时用官方脚本安装 |

---

## 快速开始

### 安装

**一键安装**（macOS / Linux，以及 Windows 上的 Git Bash）：

```bash
curl -fsSL https://raw.githubusercontent.com/zhaoyewei/antigravity-switch/main/install.sh | bash
```

脚本安装到 `~/.agys/` 并自动处理 PATH。也可以离线安装或直接用 pip：

```bash
git clone https://github.com/zhaoyewei/antigravity-switch.git
cd antigravity-switch && bash install.sh

# 或者
python -m pip install -e .
```

要求 **Python 3.9+**（仅标准库）。`agy` 不必预先安装——`agys init` / `add` / `use` / `as`
会自动检测，缺失时使用 [Antigravity 官方安装脚本](https://antigravity.google/docs/getting-started?tab=cli) 安装。
可用 `AGYS_NO_AUTO_INSTALL=1` 关闭自动安装。

### 三步上手

```bash
agys init            # 检测/安装 agy，并把当前已登录的帐号收录为第一个帐号
agys add work        # 走 agy 浏览器登录流程添加第二个帐号，完成后直接生效
agys use work        # 随时切换
agys as work -p "review this diff"   # 切换并以该帐号启动 agy，参数原样透传
```

`agys init` 是可选的：直接 `agys add` 同样会先保存当前登录。

---

## 命令速查

完整参考见 [docs/COMMANDS.md](docs/COMMANDS.md)，也可运行 `agys help commands`。

| 分组 | 命令 | 作用 |
|---|---|---|
| 引导 | `init` | 检测/安装 agy，收录当前登录 |
| 日常 | `add [名字]` | 添加帐号并立即生效 |
| | `list` (`ls`) | 列出所有帐号（`*` = 当前） |
| | `use` (`switch`) `<帐号>` | 切换帐号 |
| | `as` (`run`) `<帐号> [参数…]` | 切换并以该帐号启动 agy |
| | `current` / `status` | 查看当前状态 / 一行概览 |
| | `whoami` / `ids` | 输出活跃邮箱 / 所有 id 与别名（脚本用） |
| | `logout` | 登出并清除活跃凭据，但保留所有帐号 |
| 管理 | `alias` / `rename` | 设置别名 / 重命名 id |
| | `info [帐号]` | 查看凭据详情与 token 过期时间 |
| | `default [帐号]` | 查看 / 设置默认帐号 |
| | `remove` (`rm`) `<帐号>` | 删除帐号（删当前帐号会同时登出） |
| 迁移 | `export [路径]` | 导出所有帐号（**明文**，迁移用途） |
| | `import <文件>` | 导入（校验 SHA-256，不自动切换） |
| | `backup [路径]` / `restore <文件>` | 完整备份 / 恢复 vault |
| 诊断 | `doctor` / `doctor --fix` | 环境自检 / 自动修复 |
| | `layout` / `log` / `check` | 布局指纹 / 审计日志 / 版本与自检 |
| 维护 | `version` / `update` | 显示版本 / 重新运行安装脚本升级 |
| | `completion <shell>` / `help [主题]` | 生成补全脚本 / 内置帮助 |

全局参数：`--json`（结构化输出）、`--version`。
切换类命令支持 `--close-all`、`--no-guard`、`--yes`、`--allow-layout-change`。

---

## 工作原理

Antigravity 的 CLI、IDE、App、SDK 共享同一份本地登录态。`agys` 管理其中的两处：

| 位置 | 内容 | 说明 |
|---|---|---|
| OS 凭据库 | OAuth token（JSON blob） | Windows Credential Manager 条目 `gemini:antigravity`；macOS Keychain；Linux 文件式 token |
| `~/.gemini/google_accounts.json` | 活跃邮箱 / UI 显示状态 | 决定界面上显示哪个帐号 |

每个帐号被快照进 `~/.agy-accounts/profiles/<id>/profile.json`（加密）。
切换流程：**回收当前活跃凭据 → 写事务日志 → 原子写凭据与显示状态 → 读回验证 → 提交或回滚**。
切换前若检测到 agy 进程在跑，默认拒绝执行：后台进程会在 token 刷新时把旧帐号写回，导致切换被静默回退。

### 跨平台支持

| 平台 | 凭据读写 | 状态 |
|---|---|---|
| Windows | Credential Manager（`ctypes` 直调 `CredReadW` / `CredWriteW`，不经 PowerShell / cmdkey） | ✅ 实机验证（agy 1.1.4） |
| macOS | Keychain（`security` CLI，service=`gemini`, account=`antigravity`） | ⚠️ 最佳努力，未经实机验证 |
| Linux | 文件式 token（`~/.gemini/antigravity-cli/antigravity-oauth-token`） | ⚠️ 最佳努力，未经实机验证 |

凭据后端通过 `CredentialStore` 抽象隔离，新增平台只需实现一个后端。

---

## 安全模型

- **本地 vault 默认加密**：Windows DPAPI（绑定当前用户）；macOS / Linux 用 `SHAKE256` 流密码 + `HMAC-SHA256` 认证，密钥文件权限 `0600`、目录 `0700`。
- **导出文件是明文**：`export` 仅用于迁移，默认落在 `~/.agy-accounts/exports/`，带 schema 版本与 SHA-256 校验和。**迁移完成后请删除导出文件**。
- **备份含敏感数据**：`backup` 生成的 tar.gz 内含加密凭据与密钥，请按敏感文件保管。
- **审计日志不含 token**：`audit.jsonl` 只记录动作、帐号 id 与结果。
- **不要把 `~/.agy-accounts/` 放进网盘同步目录**或共享位置。
- 漏洞请按 [SECURITY.md](SECURITY.md) 私下报告，不要开公开 issue。

---

## 已知限制

| 限制 | 说明 |
|---|---|
| Windows 无法真正并发使用多个帐号 | 凭据是 OS 级全局唯一条目，当前 agy 版本没有文件化凭据开关；同一帐号多开窗口不受影响。Linux 上理论上可行，见 [ROADMAP.md](ROADMAP.md) |
| `export` 是迁移而非复制 | refresh token 会被 Google 轮换，两台机器同时使用同一份凭据会互相踢下线。导入新机器后请在源机器 `agys remove` |
| IDE 可能仍显示旧邮箱 | CLI 与 IDE 共享凭据，但 IDE 窗口需执行 `Developer: Reload Window` 才会刷新显示 |
| macOS / Linux 后端未实机验证 | 欢迎反馈与 PR，见 [CONTRIBUTING.md](CONTRIBUTING.md) |

---

## 文档

- [完整命令参考](docs/COMMANDS.md) · [排障指南](docs/TROUBLESHOOTING.md)
- [贡献指南](CONTRIBUTING.md) · [安全政策](SECURITY.md) · [行为准则](CODE_OF_CONDUCT.md)
- [路线图](ROADMAP.md) · [更新日志](CHANGELOG.md)

## 开发

```bash
python -m pip install -e '.[test]'
pytest -q                          # 单元测试（memory 后端，不触碰真实凭据）
bash tests/integration/run_tests.sh # 跨平台集成测试
make test                          # 两者一起跑
```

CI 覆盖 Windows / macOS / Linux × Python 3.9 / 3.11 / 3.13。
所有测试使用 `AGYS_BACKEND=memory`，**绝不读写真实 OS 凭据库**。

## License

[MIT](LICENSE)
