PY ?= python3

.PHONY: help install dev test unit integration compile lint clean build dist verify

help:
	@echo "antigravity-switch (agys) — 常用目标"
	@echo "  make install      安装为可编辑包 (pip install -e '.[test]')"
	@echo "  make test         单元测试 + 集成测试"
	@echo "  make unit         仅 pytest 单元测试"
	@echo "  make integration  仅 shell 集成测试 (memory 后端)"
	@echo "  make compile      编译检查 src/agys"
	@echo "  make lint         编译检查 + 单元测试"
	@echo "  make build        构建 sdist / wheel (需要 build)"
	@echo "  make clean        清理本地构建与缓存产物"
	@echo "  make verify       compile + test + CLI 冒烟"

install:
	$(PY) -m pip install -e '.[test]'

dev: install

unit:
	$(PY) -m pytest -q

integration:
	bash tests/integration/run_tests.sh

test: unit integration

compile:
	$(PY) -m compileall -q src/agys

lint: compile unit

build:
	$(PY) -m pip install --upgrade build
	$(PY) -m build

dist: build

verify: compile test
	$(PY) -m agys version
	$(PY) -m agys --json doctor > /dev/null
	$(PY) -m agys help commands > /dev/null
	@echo "verify OK"

clean:
	-$(PY) -c "import pathlib, shutil; [shutil.rmtree(p, ignore_errors=True) for p in pathlib.Path('.').rglob('__pycache__')]; [shutil.rmtree(p, ignore_errors=True) for p in ('.pytest_cache','build','dist') if pathlib.Path(p).exists()]"
	@echo "clean OK"
