# 为什么不是"一键导入"？

**为什么 claude_to_dsh 做成"转换 → 压缩 → 索引 → 工作区 → 按 ID 引用"的管线，而不是像 `claude /resume` 那样的一键导入？**

一句话：**dsh 和 Claude Code 的会话存储架构不互通，且 dsh 明确不承诺兼容**——"一键导入"在现阶段的 dsh 上做不成立。

---

## 原因一：会话存储格式不互通（根本原因）

| | Claude Code | dsh |
|---|---|---|
| 位置 | `~/.claude/projects/**/*.jsonl` | `~/.dsh/sessions/<cwd编码>/session-*/` |
| 格式 | 事件流 NDJSON（user/assistant/tool 消息混排，明文） | 自研 `SessionEvent` schema，**zstd 压缩** |
| 版本承诺 | — | `SESSION_FORMAT_VERSION = 0`，官方明确 **无兼容承诺**（backend 拒绝旧 on-disk 格式） |

两者只有"JSONL"三个字母相同。事件结构完全不同（字段、压缩、事件类型、header），不存在现成的映射通道。要"一键导入"，要么 dsh 提供一个官方 import 工具，要么我们自己逆向 `SessionEvent` schema 并祈祷下个版本不变——后者等于在无兼容承诺的格式上写兼容层，dsh 迭代飞快，随时 break。

## 原因二：会话归属绑定 cwd，导入不只是搬数据

dsh 会话按**工作目录（cwd）**归属工作区：

- 导入历史 = 转换数据 + **重建 workspace 关联**（会话 → 项目目录）
- web 启动时 **header index 只重建一次**（`initialized` 后 `table.size > 0` 才重扫），外部进程（CLI/headless）新建的会话还会被 getter 过滤——手动写 `workspace.json` 的 sessionIds 在下次重启可能被清掉（我们实测踩过这个坑）
- 正确的挂载方式反而是"删掉 workspace.json 重启 web 让 bootstrap 全量重建"——这本身就不是"一键"的语义

## 原因三：dsh 处于 developer preview

dsh 官方定位是快速迭代的开发者预览版，当前优先打 foundation（插件架构、capability seam、会话系统本身），兼容层和导入工具不是现在的主线。`README` 原话："**THERE WILL BE COMPATIBILITY-BREAKING CHANGES.**"——在这样一条线上做"导入"兼容层，维护成本极高。

---

## 所以我们现在怎么做

**文档引用路线**：不动 dsh 内部存储，把历史变成 dsh 能消费的**轻量档案**：

```
Claude Code JSONL（100MB，90%+ 工具噪音）
    ↓ 转换：只留 user/assistant 纯文本（→ 3.9MB，4%）
    ↓ 压缩：并行 subagent 生成结构化摘要（几 KB）
    ↓ 索引：INDEX.md（每会话一行）
    ↓ 工作区：projects/<项目>/ 注册为 dsh 工作区
    ↓ 引用：dsh 任务按会话 ID 读摘要（每次几 KB token）
```

优点：
- **不碰 dsh 内部格式**——dsh 怎么迭代都不影响档案
- **token 极省**——一次转换成本，换长期"按需读几 KB"
- **双向可读**——档案是普通 markdown，Claude Code 也能读

缺点（承认）：不是真正的"对话迁移"——dsh 看不到 Claude Code 里的多轮原始对话，只能看到压缩后的摘要/档案。语义上它是"知识同步"而非"会话导入"。

---

## 期待

希望 dsh 官方（或 cc-switch 的会话管理）后续跟进：

1. **官方导入工具**：`dsh import --from claude-code` 之类的迁移器，读取 Claude Code JSONL 并转换为 dsh 会话格式（需要 dsh 提供会话格式的稳定契约）
2. **互通交换格式**：双方对齐一个中间格式（如标准 JSONL 事件流），允许工具间迁移

到那时，claude_to_dsh 就完成了历史使命——它存在的意义正是"在官方支持之前，让 dsh 也能用上 Claude Code 的历史上下文"。

---

# Why not one-click import?

**Why does claude_to_dsh use a "convert → compact → index → workspace → reference-by-ID" pipeline instead of a one-click import like `claude /resume`?**

Short answer: **dsh and Claude Code session storage are architecturally incompatible, and dsh explicitly promises no compatibility.** A "one-click import" is not feasible against current dsh.

## 1. Incompatible session storage formats (root cause)

| | Claude Code | dsh |
|---|---|---|
| Location | `~/.claude/projects/**/*.jsonl` | `~/.dsh/sessions/<cwd-encoded>/session-*/` |
| Format | Event-stream NDJSON (plaintext, mixed user/assistant/tool) | Proprietary `SessionEvent` schema, **zstd-compressed** |
| Version promise | — | `SESSION_FORMAT_VERSION = 0`, officially **no compatibility promise** |

The two share only the letters "JSONL". Event structures, compression, headers, event types — all different. A one-click import would require either an official dsh import tool or reverse-engineering `SessionEvent` while praying the next release doesn't break it.

## 2. Sessions are bound to cwd — import isn't just moving data

dsh sessions belong to workspaces by **working directory**:

- Importing history = converting data + **rebuilding workspace associations**
- The header index is rebuilt **only once at web startup**; sessions created by external processes (CLI/headless) get filtered by the getter — hand-written `sessionIds` in `workspace.json` can vanish on next restart (we hit this in practice)
- The reliable mounting path is actually "delete workspace.json and let bootstrap rebuild" — which is not "one-click" semantics anyway

## 3. dsh is in developer preview

dsh is iterating fast and prioritizing foundation (plugin architecture, capability seams). Its README literally says "**THERE WILL BE COMPATIBILITY-BREAKING CHANGES.**" Writing an import compatibility layer against that is a maintenance trap.

---

## What we do instead

**Document-referencing route**: never touch dsh's internal storage; turn history into **lightweight archives** dsh can consume:

- Convert: keep only user/assistant plain text (100MB → 3.9MB, 4%)
- Compact: parallel subagents produce structured summaries (a few KB)
- Index: `INDEX.md` (one line per session)
- Workspace: register `projects/<project>/` as dsh workspaces
- Reference: dsh tasks read summaries by session ID (a few KB of tokens each time)

**Trade-off (admitted)**: this is not true conversation migration — dsh sees compacted archives, not the original multi-turn dialogs. It's *knowledge sync*, not *session import*.

## Hope

We'd love dsh (or cc-switch's session management) to ship:

1. **Official import tool**: `dsh import --from claude-code`, backed by a stable session-format contract
2. **Interoperable exchange format**: a shared intermediate format (e.g. standard JSONL event stream) enabling cross-tool migration

Until then, claude_to_dsh exists precisely to bridge the gap — so dsh can use Claude Code history before official support lands.
