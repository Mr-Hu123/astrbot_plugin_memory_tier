# astrbot_plugin_memory_tier · 分层记忆

给 AstrBot 的长期记忆插件。**把记忆拆成三层，只把摘要塞进每轮上下文**，避免「聊天越久、每轮越贵」。

> 适配 AstrBot `v4.29.x`（Star API，`@filter.on_llm_request` + `@filter.command`）。纯标准库，无第三方依赖。

## 它解决什么问题

长对话里，上下文会无限膨胀：聊到第 100 轮时，每发一句话都要把前面 100 轮重新读一遍。
常见做法是「全都记住」，结果是 token 账单指数上涨；另一种是「定期清空」，结果她把你忘了。

这个插件走第三条路：

| 层 | 内容 | 存放 | 每轮占用 |
|---|---|---|---|
| **L1 浅层** | 最近几轮原文 | AstrBot 自带上下文（配合 `compression.max_turns`） | 由 AstrBot 控制 |
| **L2 中层** | 滚动摘要 `summary.md` | 插件数据目录 | ≈ 200 字 |
| **L3 深层** | 画像 `profile.md` + 每日日记 `diary/*.md` | 插件数据目录 | ≈ 150–400 字 |

效果：**每轮固定只注入 400–700 字**，不管聊了多久、聊了几天。历史正文交给 AstrBot 的轮数压缩，写记忆由你显式触发。

## 工作方式

```text
你发一句话
   ↓
插件把 [画像 + 摘要 + 最近日记] 拼成一小段文字
   ↓
插到 system_prompt 前面（位置可配）
   ↓
模型正常回复 —— 它「记得」你，但没读 100 轮原文
```

**平时零额外调用**：注入只是拼字符串，不调用模型。
只有你敲 `/总结`、`/画像` 时才会调用一次模型（约 200 token）。

## 安装

### 方式一：插件市场

AstrBot 面板 → 插件 → 搜索 `astrbot_plugin_memory_tier` → 安装。

### 方式二：手动

```bash
cd AstrBot/data/plugins
git clone https://github.com/your-name/astrbot_plugin_memory_tier.git
```

或在面板「插件 → 从 GitHub 安装」里填仓库地址。
安装后在面板里启用插件，配置项会自动出现。

### 方式三：本地 zip

把整个目录压缩成 zip，面板 → 插件 → 从文件安装。

## 命令

需要命令前缀（默认 `/`）。

| 命令 | 作用 | 是否会调用模型 |
|---|---|---|
| `/记忆` | 看当前注入了什么、存了多少 | 否 |
| `/记住 他喜欢冰美式不加糖` | 往画像追加一行 | 否 |
| `/忘掉 冰美式` | 删掉画像里含关键词的行 | 否 |
| `/记下 今天他加班到十点` | 往今天的日记追加一行 | 否 |
| `/日记` | 看今天 + 昨天的日记 | 否 |
| `/日记 2026-11-01` | 看指定日期 | 否 |
| `/总结` | 把最近对话压成 3 行日记 | **是**（1 次） |
| `/画像` | 从最近 14 天日记提炼画像 | **是**（1 次） |

推荐的日常节奏：

- 每天睡前 `/总结` 一次 → 今天的事变成 3 行
- 周末 `/画像` 一次 → 三行日记沉淀成稳定特征
- 发现她记错了 → `/忘掉 关键词` 直接改

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | `true` | 总开关 |
| `inject.enabled` | `true` | 是否每轮注入 |
| `inject.position` | `before` | 插在人格之前 / 之后 |
| `inject.max_chars` | `700` | 注入总字数上限（≈ 430 token） |
| `inject.profile_max_lines` | `12` | 画像最多注入几行 |
| `inject.summary_enabled` | `true` | 是否注入摘要 |
| `inject.diary_days` | `1` | 注入最近几天的日记 |
| `storage.scope` | `per_user` | `per_user` 每人一份 / `global` 共用 |
| `storage.recent_cache` | `40` | 内存里缓存多少条消息给 `/总结` 用 |
| `commands.admin_only` | `false` | 只允许管理员使用命令 |
| `commands.allow_delete` | `true` | 允许 `/忘掉` |
| `summarize.enabled` | `true` | 允许 `/总结`、`/画像` |
| `summarize.diary_prompt` | 内置 | 写日记的提示词 |
| `summarize.profile_prompt` | 内置 | 写画像的提示词 |
| `summarize.max_output_chars` | `300` | 整理结果字数上限 |

### 和 AstrBot 自带压缩的分工

只管记忆、不碰上下文。要真正省钱，**同时**把 AstrBot 的轮数压缩打开：

```
配置文件 → AI → 高级 → 上下文压缩
  最大轮数 / max_turns        = 20
  保留轮数 / trim_turns       = 1
  溢出策略 / overflow_strategy = llm_compress
```

改完效果：L1 被压到 20 轮内，L2/L3 由本插件补上 —— 既不会忘事，也不会越聊越贵。

## 数据在哪

```
AstrBot/data/plugin_data/astrbot_plugin_memory_tier/
└── snowluma-FriendMessage-123456789/
    ├── profile.md           画像
    ├── summary.md           摘要
    └── diary/
        ├── 2026-10-31.md
        └── 2026-11-01.md
```

全是纯文本，可以直接用编辑器改、用 git 备份、换机器时整体拷走。

想看某个人存了哪份：`/记忆` 会打印目录路径。

## 设计取舍

- **不做向量检索**：检索要调用 embedding 模型，DeepSeek 没有 embedding 接口，还要额外配一个模型。日常陪伴场景，画像 + 最近日记已经够用。
- **不自动写日记**：自动写要定时调模型，账单一不注意就上去了。改成你敲 `/总结`，一次 200 token，花在明处。
- **不接管上下文**：AstrBot 自带的 `compressor.py` 已经做得不错，重复造轮子只会互相打架。
- **文件而非数据库**：能直接看、直接改、直接 diff。坏了删掉重来，不会把 AstrBot 搞崩。

## 常见问题

**注入没生效？**
`/记忆` 看「注入 N 字」，如果是 0，说明画像/摘要/日记都还是空的 —— 先 `/记住` 或 `/总结`。

**她把我说的记错了？**
`/忘掉 关键词` 先删掉错的，再 `/记住` 正确的。别指望模型自己纠正。

**`/总结` 说没攒够对话？**
`storage.recent_cache` 为 0，或重启后还没聊过。缓存只在内存里，重启会清空。

**能不能一个 QQ 群共用一个记忆？**
`storage.scope` 设 `global`。

## License

MIT
