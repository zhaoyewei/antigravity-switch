# antigravity-switch (agys)

一条命令在多个 Google 帐号之间切换 Antigravity CLI（`agy`），不用反复登出登录。
纯 Python 标准库实现，零第三方依赖。

## 安装

**一键安装**（macOS / Linux，以及 Windows 上的 Git Bash）：

```bash
curl -fsSL https://raw.githubusercontent.com/zhaoyewei/antigravity-switch/main/install.sh | bash
```

安装到 `~/.agys/bin/` 并自动处理 PATH。也可以 clone 本仓库后离线安装：

```bash
git clone https://github.com/zhaoyewei/antigravity-switch.git
cd antigravity-switch && bash install.sh
```

要求：Python 3.9+（仅标准库）+ 已安装并登录过 [Antigravity CLI](https://antigravity.google.com)。

## 使用

```
agys add [名字]      添加帐号（先保存当前登录，再走 agy 浏览器登录，完成后直接生效）
agys list            列出所有帐号（* = 当前）
agys current         查看当前帐号与活跃凭据状态
agys use <帐号>      切换到指定帐号（id / 邮箱 / 别名 / 唯一前缀）
agys as <帐号> [参数…]  切换到指定帐号并以它启动 agy，后续参数透传给 agy
agys remove <帐号>   删除帐号（删除当前帐号会同时登出）
agys export [路径]   导出所有帐号（迁移用途，明文凭据）
agys import <文件>   导入导出文件（不自动切换）
agys doctor          环境自检
```

首次使用直接 `agys add`——你当前已登录的帐号会被自动保存为第一个帐号，
然后进入 agy 浏览器登录流程添加新帐号。

## 工作原理

Antigravity 的登录态由两处构成（Windows 实测，agy 1.1.4）：

| 位置 | 内容 |
|---|---|
| OS 凭据库（Windows Credential Manager 条目 `gemini:antigravity`） | OAuth token（JSON blob） |
| `~/.gemini/google_accounts.json` | 活跃邮箱（UI 显示状态） |

`agys` 把每个帐号的这两样东西快照到 `~/.agy-accounts/profiles/<id>/`，
切换时**原子替换**（临时文件 + rename、写前回收、失败自动回滚），并把切换前
活跃帐号可能被后台刷新过的 token 回写进它的 profile——避免旧 token 作废。

切换前会检测运行中的 agy / Antigravity 进程并拒绝执行：残留进程会在 token
刷新时把旧帐号凭据写回磁盘，静默回退你的切换。同一帐号多开 agy 窗口不受影响
（`agys as` 遇到当前帐号时跳过切换直接启动）。可用 `--no-guard` 强制切换（风险自负）。

## 跨平台支持

| 平台 | 凭据读写 | 状态 |
|---|---|---|
| Windows | Credential Manager（ctypes 直调 CredRead/CredWrite，不经 PowerShell/cmdkey） | ✅ 完整实测 |
| macOS | Keychain（`security` CLI，service=gemini account=antigravity） | ⚠️ 最佳努力，未经实机验证 |
| Linux | 文件式 token（`~/.gemini/antigravity-cli/antigravity-oauth-token`） | ⚠️ 最佳努力，未经实机验证 |

## 已知限制

- **Windows 上无法同时使用多个帐号**：凭据是 OS 级全局唯一条目，且本版 agy
  没有文件化凭据的开关；并发多帐号只能靠独立 OS 用户（不做）。
  Linux 上理论可行（HOME 重定向 + 文件凭据），留作后续版本。
- `export` 是**迁移**用途而非复制：refresh token 会被 Google 轮换，
  两台机器同时用同一份凭据会互相踢。导入新机器后请在源机器 `agys remove`。
- `~/.agy-accounts/profiles/` 内是**明文**登录凭据，切勿放进网盘同步目录
  或共享位置（这是用"随时可切换"换来的设计取舍，按需自行加固）。
- Antigravity 升级若改变存储位置，`agys doctor` 会帮你定位问题；路径探测
  留待后续版本做成自动适配。

## 开发

```bash
cd tests && bash run_tests.sh   # 沙箱测试（不触碰真实凭据）
```

高级 / 测试用环境变量：`AGYS_HOME`、`AGYS_GEMINI_HOME`、`AGYS_CRED_TARGET`、
`AGYS_CRED_USER`、`AGYS_AGY_BIN`、`AGYS_PROCESS_NAMES`。

## License

MIT
