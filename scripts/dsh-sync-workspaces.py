#!/usr/bin/env python3
"""迁移后同步：把 claude-history/projects/ 下的项目文件夹注册为 dsh 工作区。

用法:
  python dsh-sync-workspaces.py                    # 注册所有缺失的工作区（幂等）
  python dsh-sync-workspaces.py --only <IDs>       # 只注册勾选会话所属的项目
  python dsh-sync-workspaces.py --only <IDs> --read  # 注册后主动让 dsh 读勾选项目的 INDEX+摘要
  python dsh-sync-workspaces.py --attach           # 把项目目录下所有会话挂载到对应工作区（改 workspace.json，需重启 web 生效）
"""
import argparse
import json
import os
import subprocess
import urllib.request

PROJECTS = os.path.expanduser("~/claude-history/projects")
API = "http://127.0.0.1:3080/api/workspace.create"
# 用全局 dsh（npm 版）以便在项目目录运行，会话按 cwd 归属对应工作区（pnpm 版固定在仓库目录会进"未分组"）
DSH_CMD = "dsh"


def create_workspace(path: str) -> str:
    """通过 dsh web JSON-RPC 注册工作区，返回结果描述。"""
    req = urllib.request.Request(
        API,
        data=json.dumps({
            "type": "client-request",
            "rpcId": "sync",
            "method": "workspace.create",
            "payload": {"path": path},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        ok = resp["result"].get("ok")
        if ok:
            return f"OK: {path}"
        err = resp["result"].get("error", {})
        if err.get("code") == "workspace-invalid-path":
            return f"路径无效: {path}（{err.get('message', '')[:80]}）"
        return f"失败: {err.get('message', '?')[:80]}"
    except Exception as e:
        return f"API 异常（dsh web 在跑吗？）: {e}"


def dsh_read(project: str) -> None:
    """在项目文件夹里用全局 dsh 跑 headless，读该项目 INDEX + 摘要。
    cwd=项目目录，会话按 cwd 归属对应工作区（否则进"未分组"）。"""
    proj_dir = os.path.join(PROJECTS, project)
    index = os.path.join(proj_dir, "INDEX.md")
    if not os.path.isfile(index):
        return
    prompt = (
        f"读 INDEX.md，找到最新一个会话，读它的摘要文件 "
        f"summaries/对应ID.md（见 INDEX 里·摘要: 路径），"
        f"用一句话总结该会话主题"
    )
    try:
        r = subprocess.run(
            f'{DSH_CMD} --profile headless "{prompt}"',
            cwd=proj_dir, capture_output=True, text=True, timeout=300,
            shell=True, encoding="utf-8", errors="replace",
        )
        last = (r.stdout or r.stderr).strip().splitlines()
        tail = last[-1] if last else "(无输出)"
        print(f"  dsh 读「{project}」: {tail[:100]}")
    except Exception as e:
        print(f"  dsh 读「{project}」异常: {e}")


def projects_for(only: set) -> list:
    """根据会话 ID 子集找出归属的项目文件夹（搜索 projects/*/summaries/<ID>.md）。"""
    found = set()
    if not os.path.isdir(PROJECTS):
        return []
    for proj in os.listdir(PROJECTS):
        summ = os.path.join(PROJECTS, proj, "summaries")
        if not os.path.isdir(summ):
            continue
        for fn in os.listdir(summ):
            sid = fn[:-3]
            if sid in only or sid[:8] in only:
                found.add(proj)
                break
    return sorted(found)



def rpc(method: str) -> dict:
    """调用 dsh web JSON-RPC API（session.list / workspace.list）。"""
    req = urllib.request.Request(
        "http://127.0.0.1:3080/api/" + method,
        data=json.dumps({
            "type": "client-request",
            "rpcId": "attach",
            "method": method,
            "payload": {},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["result"]["value"]


def attach_sessions():
    """把 cwd 匹配项目路径的所有会话挂到对应工作区。
    从 session.list API 拿 (id, cwd) 与 workspace.list 的 path 匹配，写入 workspace.json。
    教训：项目目录下常有多个会话（多批次 dsh_read），漏挂的会显示在"未分组"；
    手动写 sessionIds 在 web 重启时可能被 header index 过滤——更可靠的是删除
    workspace.json 重启 web 让 bootstrap 全量重建。"""
    ws_path = os.path.expanduser("~/.dsh/storages/workspace.json")
    try:
        sessions = rpc("session.list")["items"]
        workspaces = rpc("workspace.list")["items"]
    except Exception as e:
        print(f"dsh web API 不可用（dsh web 在跑吗？）: {e}")
        return
    with open(ws_path, encoding="utf-8") as f:
        d = json.load(f)
    ws = d["tables"]["workspaces"]
    by_path = {w["path"].replace("\\", "/").lower(): w for w in workspaces}
    changed = 0
    for rec in ws.values():
        path = rec["path"].replace("\\", "/").lower()
        matched = sorted(
            s["sessionId"] for s in sessions
            if (s.get("cwd") or "").replace("\\", "/").lower() == path
        )
        if matched and set(matched) != set(rec.get("sessionIds") or []):
            rec["sessionIds"] = matched
            changed += 1
            print(f"  挂载 {rec['title']}: {len(matched)} 个会话")
    if changed:
        with open(ws_path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        print(f"=== 已更新 {changed} 个工作区（workspace.json），需重启 dsh web 生效 ===")
    else:
        print("无变更；更可靠的做法：删除 workspace.json 重启 dsh web 走 bootstrap 全量重建")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--read", action="store_true", help="注册后主动让 dsh 读各项目")
    ap.add_argument("--only", help="只处理勾选会话（逗号分隔的会话 ID 前 8 位或完整 UUID）所属的项目")
    ap.add_argument("--attach", action="store_true", help="挂载项目目录下所有会话到工作区")
    args = ap.parse_args()

    if args.attach:
        attach_sessions()
        return

    if not os.path.isdir(PROJECTS):
        print("claude-history/projects 不存在，先跑 claude-history-dump.py 迁移"); return

    if args.only:
        only = {s.strip() for s in args.only.split(",") if s.strip()}
        projects = projects_for(only)
        if not projects:
            print("勾选的会话没有对应项目文件夹（先跑 claude-history-dump.py --only ... --write 迁移）"); return
    else:
        projects = sorted(d for d in os.listdir(PROJECTS)
                          if os.path.isdir(os.path.join(PROJECTS, d))
                          and os.path.isfile(os.path.join(PROJECTS, d, "INDEX.md")))
    if not projects:
        print("没有可同步的项目文件夹"); return

    print(f"=== 注册 {len(projects)} 个项目工作区（幂等）:")
    for p in projects:
        print(" ", create_workspace(os.path.join(PROJECTS, p)))

    if args.read:
        print("=== 主动让 dsh 读各项目档案:")
        for p in projects:
            dsh_read(p)


if __name__ == "__main__":
    main()
