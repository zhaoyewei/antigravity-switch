# Changelog

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
