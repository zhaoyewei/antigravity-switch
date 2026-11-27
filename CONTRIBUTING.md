# 贡献指南

感谢你愿意为 `agys` 做贡献。这是一个纯标准库的小工具，贡献门槛很低——
修一个错别字、补一条文档、加一个平台后端都欢迎。

## 开发环境

```bash
git clone https://github.com/zhaoyewei/antigravity-switch.git
cd antigravity-switch
python -m pip install -e '.[test]'
```

要求 Python 3.9+。仓库内的 `agys` / `agys.cmd` 是开发启动器，会把 `src/`
加进 `PYTHONPATH`；也可以直接 `python -m agys ...`。

## 项目结构

| 路径 | 职责 |
|---|---|
| `src/agys/cli.py` | 参数解析、切换主流程、核心命令 |
| `src/agys/extra.py` | 扩展命令（引导、状态、备份、补全、帮助） |
| `src/agys/common.py` | CLI 公共工具（错误、输出、文件锁） |
| `src/agys/config.py` | 路径与环境变量（全部动态解析，便于测试隔离） |
| `src/agys/credentials/` | 凭据后端抽象：`windows` / `macos` / `linux` / `memory` |
| `src/agys/crypto.py` | vault 加密、文件权限、Windows ACL |
| `src/agys/vault.py` | vault 与 profile 读写、v0.1 明文迁移、`resolve()` |
| `src/agys/identity.py` | 从 token 中提取稳定身份 |
| `src/agys/layout.py` | agy 存储布局探测与指纹校验 |
| `src/agys/journal.py` | 加密事务日志与崩溃回滚 |
| `src/agys/process.py` | agy 进程检测、关闭与重开 |
| `src/agys/expimp.py` / `audit.py` / `doctor.py` | 导入导出 / 审计日志 / 自检 |
| `src/agys/agy_install.py` | agy 检测与官方脚本自动安装 |
| `tests/unit/` | pytest 单元测试 |
| `tests/integration/` | 跨平台 shell 集成测试 |

## 测试

```bash
pytest -q                           # 单元测试
bash tests/integration/run_tests.sh  # 集成测试
make test                           # 两者一起跑
```

**重要**：所有测试都设置 `AGYS_BACKEND=memory`、`AGYS_HOME` 指向临时目录，
绝不能读写真实的 OS 凭据库或 `~/.gemini`。新增测试请沿用
`tests/unit/conftest.py` 的 `sandbox` fixture，或集成脚本里的 `memory` 后端。

提交前请确认：

- [ ] `python -m compileall -q src/agys` 通过
- [ ] `pytest -q` 通过
- [ ] `bash tests/integration/run_tests.sh` 全绿
- [ ] 新增命令同时补了单元测试或集成测试断言
- [ ] 若改了命令集，同步更新 `docs/COMMANDS.md`、`README.md` 与补全脚本里的命令表

## 代码约定

- 只用 Python 标准库，保持 `requires-python = ">=3.9"` 兼容（不要用 3.10+ 语法，如 `match`、新式联合类型）。
- 代码中字符串定界符统一用 ASCII 直引号；中文文案用中文标点无妨。
- 路径一律通过 `config.paths()` 获取，不要在模块导入时缓存路径——测试靠环境变量隔离。
- 与 OS 交互的部分尽量放进 `credentials/` 或 `crypto.py`，核心逻辑保持可测试。
- 写凭据必须走 `secure_write()` / `secure_dir()`，保证权限收紧。
- 遵循 `.editorconfig`：Python 4 空格、YAML/TOML 2 空格、Makefile 用 tab。

## 新增一个凭据后端

1. 在 `src/agys/credentials/` 新建模块，实现 `CredentialStore` 的
   `get()` / `set()` / `delete()` / `describe()`。
2. 在 `credentials/__init__.py` 的 `get_store()` 中注册 backend 名。
3. 在 `layout.probe()` 里补上该平台的布局字段。
4. 加单元测试，并确保 `AGYS_BACKEND=memory` 的测试不会误触真实实现。

## 发布（维护者）

1. 版本号同步改 `src/agys/__init__.py` 与 `pyproject.toml`，在 `CHANGELOG.md` 补条目。
2. 本地跑 `make test`（单测 + 集成测试，含免 Python 安装链路），确认全绿。
3. 打 `v*` tag 并推送，`release.yml` 会用 PyInstaller 在 Windows / macOS / Linux 各平台
   构建单文件二进制 + `.sha256`，并连同 sdist/wheel 一起附到 GitHub Release。
4. 产物名必须与 `src/agys/installer.py` 的 `asset_name()` 一致（`agys-<os>-<arch>[.exe]`），
   否则 `install.sh` / `install.ps1` 下载不到；改命名规则时请同时更新该模块与单测。
5. 发布后用 `install.sh` / `install.ps1` 实机验一次「无需 Python」的安装与 `agys update`。

本地想试打包：`python -m pip install pyinstaller && python scripts/build_binary.py`，
产物在 `dist/binaries/`（该目录已被 gitignore）。

## 提交与 Pull Request

- commit message 用简短的祈使句，例如 `fix: unlock file lock on Unix`、`docs: add command reference`。
- 一个 PR 聚焦一件事；涉及行为变更时请说明动机与测试结果。
- PR 会跑三平台 × 三个 Python 版本的 CI，请确保本地测试先过。
- 请在 PR 描述里注明你验证过的平台；macOS / Linux 凭据后端目前缺少实机验证，相关反馈尤其有价值。

## 报告问题

Bug 请用 issue 模板，附上 `agys doctor` 的输出（**注意先删掉其中的路径、邮箱等个人信息**）
和 `agys --json doctor`。安全漏洞**不要开公开 issue**，见 [SECURITY.md](SECURITY.md)。

参与贡献即表示你同意 [行为准则](CODE_OF_CONDUCT.md)。
