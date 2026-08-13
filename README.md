# claude_to_dsh

把 Claude Code 历史会话（`~/.claude/projects/**/*.jsonl`）转成 token 极省的 markdown 档案，供 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（`dsh`）按会话 ID 引用。

**核心思路**：Claude Code 的原始会话 JSONL 里 90%+ 是工具调用噪音（实测 100MB → 3.9MB 纯对话，压缩到 4%）。转换后 dsh 每次只需读几 KB 的索引/摘要，而不是全量历史——**用一次转换成本换长期的低 token 引用**。

## 工作流

```
① 勾选确认（hook 强制）→ ② 只迁移勾选的（--only）→ ③ 可选 Compact 摘要
→ ④ 刷新索引 → ⑤ 注册 dsh 工作区 + 主动让 dsh 读 → ⑥ dsh 按 ID 引用
```

## 依赖

| 依赖 | 版本/安装 | 用途 |
|------|-----------|------|
| Claude Code | ≥ 2.x | skill 宿主（勾选、转换、编排） |
| Python | ≥ 3.10 | 转换脚本 |
| **dsh**（DeepSeek Harness） | `npm i -g @deepseek-ai/dsh` | 档案消费端（headless 任务 / web UI） |
| **DEEPSEEK_API_KEY** | 写入 dsh 运行目录 `.env` | dsh 发起 LLM 任务 |
| dsh web 服务（可选） | `dsh web`（http://127.0.0.1:3080） | 工作区注册与 UI 浏览（无它则跳过注册步骤） |

> ⚠️ dsh 目前是 developer preview，命令/行为可能变化。会话存储格式（`SESSION_FORMAT_VERSION=0`）与 Claude Code 不互通——本 skill 走**文档引用**而非会话迁移。

## 安装

```bash
git clone https://github.com/hanasite/claude_to_dsh.git
cd claude_to_dsh
python install.py          # 复制脚本到 ~/scripts/ + 注册 hook 到 ~/.claude/settings.json
```

然后把 skill 放入 `~/.claude/skills/claude_to_dsh/`（或通过 skillhub/clawhub 安装）。

**重启 Claude Code**（或 `/hooks` 重载）后生效。

## 使用

触发词：*"迁移历史会话"* / *"compact 历史"* / *"把 claude 会话同步过来"* / *"恢复上次讨论"*

流程由 skill 驱动，核心环节：

```bash
# 勾选确认后只迁移勾选的（hook 强制：不带 --only 会被拒绝）
python ~/scripts/claude-history-dump.py --only <会话ID列表> --write

# 刷新索引
python ~/scripts/claude-history-dump.py --index

# 收尾：注册工作区 + 主动让 dsh 读
python ~/scripts/dsh-sync-workspaces.py --only <会话ID列表> --read

# 最可靠的工作区挂载：删除注册表让 dsh 自己 bootstrap 重建
# （备份后）删除 ~/.dsh/storages/workspace.json 并重启 dsh web
```

## 产物结构

```
~/claude-history/
├── INDEX.md                    ← 索引：每会话一行（日期/项目/ID/token量/首问/摘要路径）
├── <项目>/<会话ID>.md          ← 纯对话档案（只留 user/assistant 文本）
├── summaries/<会话ID>.md       ← 结构化摘要（Claude compact 式提炼）
└── projects/<项目>/            ← 按主题归类的项目文件夹（含各自 INDEX + summaries）
```

## 机制说明

- **勾选强制**：PreToolUse hook（`hooks/confirm-history-migration.py`）拦截迁移命令——不带 `--only` 一律 deny。注意 `permissionDecision: "ask"` 在 Claude Code 的 acceptEdits 权限模式下会被自动吞掉不弹窗，所以实现用 `deny` 强制
- **会话归属**：dsh 会话按 cwd 归属工作区——headless 任务必须在项目目录跑（全局 `dsh` + `cwd=项目目录`），用 `pnpm dsh`（cwd 固定仓库目录）会进"未分组"
- **工作区挂载**：**不要手动改 `~/.dsh/storages/workspace.json` 的 sessionIds**（header index 只在 web 启动时重建一次，手动写入会被 getter 过滤掉）。正确做法：删除 workspace.json 重启 `dsh web`，bootstrap 会扫描所有会话按 cwd 自动建工作区
- **摘要 agent 并行**：Compact 步骤按会话大小分组并行派发 subagent（≤100k token 全文读；更大的读首尾 + grep 关键段）

## 常见问题

| 现象 | 处理 |
|------|------|
| 迁移命令被 deny | 正常——先勾选，再带 `--only` |
| 会话在"未分组" | cwd 不在任何工作区；确认 headless 在项目目录跑，然后 bootstrap 重建 |
| 工作区注册 API 中文路径 ENOENT | 用 Python 发请求（Git Bash curl 会破坏 UTF-8） |
| dsh 找不到档案文件 | 给绝对路径（工作区 cwd 可能不在项目文件夹） |

## License

MIT
