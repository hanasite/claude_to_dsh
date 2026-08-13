#!/usr/bin/env python3
"""Claude Code 历史会话 → 干净对话 markdown
只提取 user 提问与 assistant 纯文本回复，丢弃 tool_use/tool_result/thinking 噪音。
用法:
  python claude-history-dump.py                 # 全量统计（不写文件）
  python claude-history-dump.py --days 30       # 只处理最近 30 天的会话
  python claude-history-dump.py --write         # 写入 ~/claude-history/<项目>/<会话>.md
"""
import argparse, json, os, re, sys
from datetime import datetime, timedelta

CLAUDE_DIR = os.path.expanduser("~/.claude/projects")
OUT_DIR = os.path.expanduser("~/claude-history")
CHAR_PER_TOKEN = 1.6  # 中英混排粗略估算：1 token ≈ 1.6 字符


def extract_text_blocks(content):
    """从 message content（str 或 block 数组）提取纯文本"""
    texts = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                texts.append(b.get("text", ""))
    return "\n".join(t for t in texts if t and t.strip())


def parse_jsonl(path, cutoff):
    """解析会话文件 → [(时间戳, 角色, 文本)]，丢弃工具噪音"""
    msgs = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # 丢弃压缩摘要/自动标题/文件历史等非对话事件
                if ev.get("type") not in ("user", "assistant"):
                    continue
                if "compact" in ev.get("type", "") or ev.get("type") == "summary":
                    continue
                ts = ev.get("timestamp") or ""
                if cutoff and ts and ts < cutoff:
                    continue
                m = ev.get("message") or {}
                # 丢弃 compaction 注入的摘要消息（带 summary 字段）
                if "summary" in m:
                    continue
                role = m.get("role")
                if role == "user":
                    # user 消息里的 tool_result 是工具输出，跳过
                    content = m.get("content")
                    if isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                    ):
                        continue
                    text = extract_text_blocks(content)
                    if text:
                        msgs.append((ts, "你", text))
                elif role == "assistant":
                    content = m.get("content") or ""
                    # 只取 text 块，tool_use 丢弃
                    text = extract_text_blocks(content)
                    if text:
                        msgs.append((ts, "Claude", text))
    except OSError as e:
        print(f"  !! 读取失败 {path}: {e}", file=sys.stderr)
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="只处理最近 N 天的会话")
    ap.add_argument("--write", action="store_true", help="写入 markdown 文件")
    ap.add_argument("--index", action="store_true", help="只生成索引 INDEX.md，不写会话文件")
    ap.add_argument("--project", help="只处理指定项目目录名")
    ap.add_argument("--only", help="只处理指定会话（逗号分隔的会话 ID 前 8 位或完整 UUID）")
    args = ap.parse_args()

    cutoff = ""
    if args.days:
        cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    only = set()
    if args.only:
        only = {s.strip() for s in args.only.split(",") if s.strip()}

    projects = sorted(d for d in os.listdir(CLAUDE_DIR) if os.path.isdir(os.path.join(CLAUDE_DIR, d)))
    if args.project:
        projects = [p for p in projects if args.project in p]
    if not projects:
        print("没有找到项目目录"); return

    total_raw = total_out = total_msgs = 0
    for proj in projects:
        pdir = os.path.join(CLAUDE_DIR, proj)
        files = sorted(f for f in os.listdir(pdir) if f.endswith(".jsonl"))
        if only:
            files = [f for f in files if f[:-6] in only or f[:8] in only]
        if not files:
            continue
        proj_raw = proj_out = 0
        for fn in files:
            path = os.path.join(pdir, fn)
            raw_size = os.path.getsize(path)
            msgs = parse_jsonl(path, cutoff)
            if not msgs:
                continue
            md = []
            for ts, who, text in msgs:
                t = ts[:16].replace("T", " ") if ts else ""
                md.append(f"### [{who}] {t}\n\n{text.strip()}\n")
            body = f"# 会话 {fn}\n\n来源: {proj}\n\n" + "\n".join(md)
            out_size = len(body.encode("utf-8"))
            proj_raw += raw_size; proj_out += out_size
            total_msgs += len(msgs)
            if args.write:
                out = os.path.join(OUT_DIR, proj, fn[:-6] + ".md")
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with open(out, "w", encoding="utf-8") as f:
                    f.write(body)
        if proj_raw:
            ratio = proj_out / proj_raw * 100 if proj_raw else 0
            est_tokens = int(proj_out / CHAR_PER_TOKEN)
            print(f"{proj:50s} 原始 {proj_raw/1e6:6.2f}MB → 对话 {proj_out/1e6:6.2f}MB ({ratio:4.1f}%)  ≈ {est_tokens/1000:.1f}k tokens")
            total_raw += proj_raw; total_out += proj_out

    if total_raw:
        print(f"\n合计: 原始 {total_raw/1e6:.1f}MB → 对话 {total_out/1e6:.2f}MB "
              f"({total_out/total_raw*100:.1f}%) ≈ {int(total_out/CHAR_PER_TOKEN/1000)}k tokens, {total_msgs} 条消息")


def gen_index():
    """生成 INDEX.md：每会话一行（日期、token、消息数、首条用户消息），按日期倒序"""
    cutoff = ""
    entries = []
    for proj in sorted(os.listdir(CLAUDE_DIR)):
        pdir = os.path.join(CLAUDE_DIR, proj)
        if not os.path.isdir(pdir):
            continue
        for fn in sorted(os.listdir(pdir)):
            if not fn.endswith(".jsonl"):
                continue
            msgs = parse_jsonl(os.path.join(pdir, fn), "")
            if not msgs:
                continue
            ts = msgs[0][0] or "?"
            size = sum(len(m[2].encode("utf-8")) for m in msgs)
            first = next((m[2].strip().replace("\n", " ") for m in msgs if m[1] == "你"), "")
            first = re.sub(r"<system-reminder>.*?</system-reminder>", "", first).strip()[:100]
            entries.append((ts, fn[:-6], proj, len(msgs), size, first))
    entries.sort(reverse=True)  # 最新在前
    lines = ["# Claude Code 历史会话索引", "",
             "用法: dsh --profile headless \"先读 claude-history/<项目>/<会话ID>.md ...\"", "",
             f"共 {len(entries)} 个会话（只含 user/assistant 纯文本，已丢弃工具输出与压缩摘要）", ""]
    for ts, sid, proj, n, size, first in entries:
        toks = int(size / CHAR_PER_TOKEN)
        disp = f"{toks/1000:.1f}k" if toks >= 1000 else str(toks)
        summ = os.path.join(OUT_DIR, "summaries", sid + ".md")
        suffix = f" · 摘要: summaries/{sid}.md" if os.path.isfile(summ) else ""
        lines.append(f"- `{ts[:10]}` **{proj}** · {sid[:8]} · {n} 条 · ≈{disp} token{suffix}")
        if first:
            lines.append(f"  - 首问: {first}")
    out = os.path.join(OUT_DIR, "INDEX.md")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"索引已生成: {out} ({len(entries)} 个会话)")


if __name__ == "__main__":
    import sys
    if "--index" in sys.argv:
        gen_index()
    else:
        main()


if __name__ == "__main__":
    main()
