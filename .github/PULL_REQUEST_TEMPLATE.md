## 这个 PR 做了什么

<!-- 一两句话说明改动与动机；行为变更请说明为什么需要 -->

## 关联

<!-- 关联的 issue，例如 Closes #12；没有可写「无」 -->

## 测试

- [ ] `python -m compileall -q src/agys` 通过
- [ ] `pytest -q` 通过
- [ ] `bash tests/integration/run_tests.sh` 通过
- [ ] 新增 / 修改的命令已补测试
- [ ] 测试使用 `AGYS_BACKEND=memory`，**未触碰真实凭据**

验证平台：<!-- Windows / macOS / Linux，以及 Python 版本 -->

## 文档与兼容性

- [ ] 改动涉及命令集时，已同步 `README.md`、`docs/COMMANDS.md` 与补全脚本命令表
- [ ] 改动涉及行为时，已更新 `CHANGELOG.md`
- [ ] 保持 Python 3.9 兼容、仅使用标准库

## 其它说明

<!-- 需要 reviewer 特别注意的地方；如含破坏性变更请在此标明 -->
