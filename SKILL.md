---
name: claude-history-sync
description: Use when the user wants to recover context from past Claude Code conversations for dsh (deepseek-harness) or other tools — "历史对话", "compact 历史", "把 claude 会话同步过来", "恢复上次讨论", "历史上下文". Converts Claude Code JSONL history to a token-lean markdown archive, optionally compacts each session into a structured summary, and references it by session ID.
---

# Claude History Sync

把 Claude Code 历史会话（`~/.claude/projects/**/*.jsonl`）转成 token 极省的 markdown 档案，供 dsh（`deepseek-harness`）按会话 ID 引用。档案在 `~/claude-history/`，一次性转换后按需读取，避免每次全量喂 token。

## 架构

```
~/claude-history/
├── INDEX.md                    ← 索引：每会话一行（日期/项目/ID/token量/首问/摘要路径）
├── <项目>/<会话ID>.md          ← 纯对话档案（只留 user/assistant 文本，约原始 4%）
└── summaries/<会话ID>.md       ← 结构化摘要（可选，Claude compact 式提炼）
```

## 工作流

### 0. 勾选确认（必须先做，hook 强制）

PreToolUse hook（`~/.claude/hooks/confirm-history-migration.py`，settings.json 已注册）**强制拦截**迁移命令：不带 `--only` 的 `claude-history-dump` 调用一律 deny（提示先勾选）。所以流程是：

1. 用 AskUserQuestion（multiSelect）列出候选会话（从 INDEX.md 取），让用户勾选
2. 只跑勾选的：`python ~/scripts/claude-history-dump.py --only <会话ID前8位或完整UUID,逗号分隔> --write`

不勾选直接全量 `--write` 会被 hook 拒绝（deny）。无 summary 的会话也要先问。
注意：hook 的 `permissionDecision: "ask"` 在 acceptEdits 权限模式下会被自动吞掉不弹窗，所以实现用 `deny` 强制（verified 2026-08-13）。

### 1. 转换（JSONL → 纯对话）

> ⚠️ 此步必须带 `--only`（勾选白名单），见步骤 0

```bash
python ~/scripts/claude-history-dump.py --write    # 全量（需先勾选确认）
python ~/scripts/claude-history-dump.py --days 30  # 只转最近 N 天
python ~/scripts/claude-history-dump.py --only <ids> --write  # 只转勾选的
```

脚本已丢弃：工具调用（tool_use/tool_result）、压缩摘要（summary/compact 事件、带 summary 字段的消息）、ai-title、文件历史等噪音。

### 2. Compact 总结（可选，推荐）

并行派发 subagent，每个处理 ≤150k token 的会话组，输出结构化摘要：

```markdown
# 会话摘要 <日期>
- **主题**: 一句话
- **背景/需求**: 用户想解决什么
- **关键决策/成果**: 要点（含文件名/数字）
- **遗留问题/待办**: 未完成事项
- **关键文件/路径**: 项目路径
```

分组规则（先按文件大小排序）：
- **≤100k token**：agent 全文读
- **>100k token**：agent 读开头 300 行 + 末尾 300 行，Grep `结论|决定|待办|问题|注意|TODO|FIXME` 抓要点，Grep `### [你]` 找主线
- 每组提示词必须含：输出路径（只写 summaries/）、约束（不碰其他文件）、返回一行主题

### 3. 刷新索引

```bash
python ~/scripts/claude-history-dump.py --index
```

索引每行带摘要路径（存在时），是"按 ID 引用"的入口。

### 3.5 迁移后收尾（必须）：注册工作区 + 主动让 dsh 读

**只处理用户勾选的项目**（与迁移的 `--only` 同一组 ID）：

```bash
python ~/scripts/dsh-sync-workspaces.py --only <与迁移相同的会话ID列表> --read
```

然后**重启 dsh web**（或直接删 `~/.dsh/storages/workspace.json` 重启，触发首次 bootstrap 全量重建）：

```bash
# 最可靠：删 workspace.json 让 dsh 自己扫描会话按 cwd 重建工作区（含未分组的旧会话归位）
# 备份后删除，重启 web 即可——产品原生路径，胜过手动维护注册表
```

流程（均已验证 2026-08-13）：
1. **注册工作区**：JSON-RPC `workspace.create` 注册勾选项目（幂等），Web UI 侧边栏可见
2. **主动让 dsh 读**：对每个勾选项目调 `dsh --profile headless`（**必须全局 `dsh` + cwd=项目目录**，pnpm 版 cwd 固定仓库会让会话进"未分组"）读 INDEX + 摘要（每项目 30-60s，可后台）
3. **⚠️ 会话挂载交给 dsh 自己**：**不要手动改 workspace.json 的 sessionIds**——web 启动时 header index 只重建一次（`initialized` 后 `table.size>0` 才重扫），手动写入的会话在后续重启会被 getter 过滤掉（实测：文件有、API 无）。**正确做法：删除 workspace.json 重启 web，bootstrap 会扫描所有会话按 cwd 自动分组建工作区并挂载**（未分组的旧会话也会归位）

不传 `--only` 时注册全部项目（收尾兜底）。

### 4. dsh 按 ID 引用

```cmd
dsh --profile headless "读 claude-history/INDEX.md 找到 <关键词> 会话，读它的摘要 claude-history/summaries/<ID>.md，然后..."
```

大会话（>150k token）摘要优先；需要细节时才读全文档案 `claude-history/<项目>/<ID>.md`。

## dsh 侧（接收方）配置

迁移过去之后，dsh 要能消费这些档案，需具备：

- **API Key**：`DEEPSEEK_API_KEY` 写进 dsh 运行目录的 `.env`（源码版 = 仓库根；全局版 `dsh` 用 `~/.dsh/` 下配置），无 key 无法发起任务
- **全局指令**：`~/.dsh/AGENTS.md`（dsh 的用户级指令文件）——从 `~/.claude/CLAUDE.md` 复制/同步，改全局指令时两边都要更
- **项目指令**：dsh 自动扫描项目根到 cwd 的 CLAUDE.md/AGENTS.md（同 Claude Code 行为，内容重复自动去重），项目档案放 `~/claude-history/` 后即可被 dsh 任务按路径引用
- **会话历史不互通**：`~/.dsh/sessions/` 是 dsh 专有格式（SESSION_FORMAT_VERSION=0 无兼容承诺），Claude Code 的 JSONL 无法直接导入，只走文档引用
- **验证**：`dsh --profile headless "读 claude-history/INDEX.md 找到 <会话>，读它的摘要 ..."`，能正确回答即链路通
- **⚠️ 工作区 cwd 陷阱**：dsh 工作区/新会话的 cwd 可能不在项目文件夹（web UI 里提示"当前工作目录没有找到"）。引用档案时**一律给绝对路径**（`~/claude-history/projects/<项目>/INDEX.md`），不要依赖相对路径
- **工作区注册**：`~/claude-history/projects/<项目>/` 已是 dsh 工作区（web UI 侧边栏可见）。新增项目文件夹后注册：`POST http://127.0.0.1:3080/api/workspace.create`，body `{"type":"client-request","rpcId":"x","method":"workspace.create","payload":{"path":"<绝对路径>"}}`，Content-Type JSON；**中文路径必须用 Python/UTF-8 发送**（Git Bash curl 会破坏中文导致 ENOENT）

## 坑位提醒

- **原始 JSONL 90%+ 是工具噪音**：转换必须丢，否则 token 爆（实测 100MB → 3.9MB）
- **dsh 会话格式与 Claude 不兼容**（SESSION_FORMAT_VERSION=0 无兼容承诺）：不要 hack 进 `~/.dsh/sessions/`，走文档引用
- **摘要 agent 必须给输出路径和约束**，否则会乱写或互踩
- **中文 token 估算**：`大小字节 / 1.6` 粗略换算，索引里仅供定位
- **只读摘要 vs 全文**：恢复上下文用摘要（几 KB）；追细节才读全文
- **⚠️ hook 的 ask 弹窗在 acceptEdits 权限模式会被吞**：用 `deny` 强制（已验证）；hook 命令里含 `claude-history-dump` 字样的任何命令都会被拦（含审计命令，注意绕行）
- **⚠️ 会话归属 = cwd 匹配**：headless 任务必须在项目目录跑（全局 `dsh` + `cwd=项目目录`）才会归到工作区；漏挂/错 cwd 的会话显示在"未分组"（deepseek-harness 仓库目录的旧会话同理，属正常）
- **⚠️ workspace.json 手工改动不可靠（已踩坑）**：header index 在 web 启动时只重建一次，手动写 sessionIds 可能被 getter 过滤掉（文件有、API/UI 无）。**一律走"删 workspace.json 重启 web"的 bootstrap 路径**（备份在 `workspace.json.manual-backup`）
- **⚠️ 会话归属 = cwd 匹配**：headless 任务必须在项目目录跑（全局 `dsh` + `cwd=项目目录`）；bootstrap 后未分组的旧会话（如 deepseek-harness 目录的 pnpm 版遗留）会自动生成对应工作区，无需手动处理
