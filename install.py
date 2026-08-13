#!/usr/bin/env python3
"""claude-history-sync 安装脚本。

功能:
  1. 复制 scripts/ 到 ~/scripts/（Claude Code 工具脚本目录）
  2. 复制 hooks/ 到 ~/.claude/hooks/（hook 脚本）
  3. 在 ~/.claude/settings.json 注册 PreToolUse hook（强制迁移先勾选 --only）

用法:
  python install.py          # 安装
  python install.py --uninstall  # 卸载（移除 hook 注册，保留文件）
"""
import json
import os
import shutil
import sys

# Windows 中文控制台默认 GBK，✓ 等 UTF-8 字符 print 会崩溃（UnicodeEncodeError）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

HOME = os.path.expanduser("~")
SCRIPTS_DST = os.path.join(HOME, "scripts")
HOOKS_DST = os.path.join(HOME, ".claude", "hooks")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
SRC = os.path.dirname(os.path.abspath(__file__))

HOOK_COMMAND = f'python {os.path.join(HOOKS_DST, "confirm-history-migration.py").replace(os.sep, "/")}'


def copy_dir(name: str, dst: str) -> None:
    src = os.path.join(SRC, name)
    os.makedirs(dst, exist_ok=True)
    for fn in os.listdir(src):
        shutil.copy2(os.path.join(src, fn), os.path.join(dst, fn))
        print(f"  ✓ {name}/{fn} → {dst}")


def register_hook(settings: dict) -> dict:
    hooks = settings.setdefault("hooks", {})
    pretool = hooks.setdefault("PreToolUse", [])
    for entry in pretool:
        for h in entry.get("hooks", []):
            if "confirm-history-migration" in h.get("command", ""):
                print("  ✓ PreToolUse hook 已存在，跳过")
                return settings
    pretool.append({
        "matcher": "Bash",
        "hooks": [{
            "type": "command",
            "shell": "bash",
            "command": HOOK_COMMAND,
            "timeout": 10,
        }],
    })
    print("  ✓ PreToolUse hook 已注册（迁移命令强制 --only 勾选）")
    return settings


def unregister_hook(settings: dict) -> dict:
    hooks = settings.get("hooks", {})
    pretool = hooks.get("PreToolUse", [])
    kept = []
    for entry in pretool:
        cmds = [h.get("command", "") for h in entry.get("hooks", [])]
        if any("confirm-history-migration" in c for c in cmds):
            print("  ✓ PreToolUse hook 已移除")
            continue
        kept.append(entry)
    if kept:
        hooks["PreToolUse"] = kept
    else:
        hooks.pop("PreToolUse", None)
    return settings


def main():
    uninstall = "--uninstall" in sys.argv

    if uninstall:
        if os.path.isfile(SETTINGS):
            with open(SETTINGS, encoding="utf-8") as f:
                settings = json.load(f)
            settings = unregister_hook(settings)
            with open(SETTINGS, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        print("卸载完成（文件保留，可手动删除 ~/scripts/ 与 ~/.claude/hooks/ 下对应文件）")
        return

    print("=== 安装 claude-history-sync ===")
    copy_dir("scripts", SCRIPTS_DST)
    copy_dir("hooks", HOOKS_DST)

    if os.path.isfile(SETTINGS):
        with open(SETTINGS, encoding="utf-8") as f:
            settings = json.load(f)
    else:
        settings = {}
    settings = register_hook(settings)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
    print("=== 安装完成 ===")
    print("重启 Claude Code（或 /hooks 重载）后生效。")
    print("前置依赖: dsh（npm 全局版: npm i -g @deepseek-ai/dsh）+ DEEPSEEK_API_KEY")


if __name__ == "__main__":
    main()
