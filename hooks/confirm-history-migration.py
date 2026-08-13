#!/usr/bin/env python3
"""PreToolUse hook: 强制历史会话迁移必须先勾选（--only 白名单）。

- 迁移命令（含 claude-history-dump）且带 --only → 放行（用户已勾选确认）
- 只读/索引操作（--index/--days，不转换会话）→ 放行
- 迁移命令不带 --only → deny，提示先勾选（模型应停下用 AskUserQuestion 让用户勾选）
- 其他命令 → allow，交给权限系统
"""
import json
import sys

data = json.load(sys.stdin)
cmd = (data.get("tool_input") or {}).get("command") or ""

if "claude-history-dump" in cmd:
    if "--only" in cmd:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "已带 --only（用户已勾选会话），放行",
            }
        }
    elif "--index" in cmd or "--days" in cmd:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "只读操作（--index/--days），放行",
            }
        }
    else:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "历史会话迁移必须先用 AskUserQuestion 让用户勾选要迁移的会话，再带 --only <会话ID列表> 重跑（见 skill claude-history-sync 工作流步骤 0）",
            }
        }
else:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
print(json.dumps(out))
