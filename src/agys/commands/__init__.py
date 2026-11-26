"""命令实现包。

按「用户想干什么」分组，而不是按代码相似度分组：

    accounts   加号 / 列号 / 改名 / 别名 / 详情
    switching  切换、交互选号、以某帐号启动 agy、auto 选号
    migrate    导出、导入、备份、恢复
    diag       自检、布局、日志、版本、升级
    hist       会话历史
    misc       引导、状态、脚本友好输出、补全、帮助
    net        代理配置

`cli.py` 只负责把这些函数挂到 argparse 上。
"""
from .accounts import (
    cmd_add, cmd_alias, cmd_current, cmd_default, cmd_ids, cmd_info, cmd_list,
    cmd_remove, cmd_rename,
)
from .diag import cmd_check, cmd_doctor, cmd_layout, cmd_log, cmd_update, cmd_version
from .hist import cmd_history
from .migrate import cmd_backup, cmd_export, cmd_import, cmd_restore
from .misc import cmd_completion, cmd_help, cmd_init, cmd_logout, cmd_status, cmd_whoami
from .net import cmd_proxy
from .switching import cmd_as, cmd_auto, cmd_tui, cmd_use

__all__ = [
    "cmd_add", "cmd_alias", "cmd_current", "cmd_default", "cmd_ids", "cmd_info",
    "cmd_list", "cmd_remove", "cmd_rename",
    "cmd_as", "cmd_auto", "cmd_tui", "cmd_use",
    "cmd_backup", "cmd_export", "cmd_import", "cmd_restore",
    "cmd_check", "cmd_doctor", "cmd_layout", "cmd_log", "cmd_update", "cmd_version",
    "cmd_history",
    "cmd_completion", "cmd_help", "cmd_init", "cmd_logout", "cmd_status", "cmd_whoami",
    "cmd_proxy",
]
