"""把三层记忆拼成一段可注入的系统提示词片段。

预算策略：画像最优先（它最稳定、最短），摘要次之，日记最后。
超出 max_chars 时，从最不重要的部分开始整块丢弃，不切断句子。
"""

from __future__ import annotations

from .store import MemoryStore, tail_lines

HEADER = "# 长期记忆"
HINT = "（这是你自己长期记下的笔记，不是你和他刚刚说的话。自然使用，不要复述、不要提「记忆文件」）"


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if limit <= 0:
        return ""
    return text if len(text) <= limit else text[:limit].rstrip()


def build(
    store: MemoryStore,
    umo: str,
    *,
    max_chars: int = 700,
    include_profile: bool = True,
    profile_max_lines: int = 12,
    summary_enabled: bool = True,
    diary_days: int = 1,
) -> str:
    """返回需要注入的文本；没有任何记忆时返回空串。"""
    if max_chars <= 0:
        return ""

    budget = max_chars

    profile = ""
    if include_profile:
        profile = tail_lines(store.profile(umo), profile_max_lines)

    summary = store.summary(umo) if summary_enabled else ""
    diaries = store.recent_diaries(umo, diary_days)

    # 先扣掉固定开销，再按优先级分配；预算紧张时先牺牲那句提示
    hint = HINT
    budget -= len(HEADER) + len(hint) + 8
    if budget < 120:
        hint = ""
        budget = max_chars - len(HEADER) - 8
    if budget <= 20:
        return ""

    blocks: list[str] = []

    if profile:
        section = f"## 关于他\n{_clip(profile, budget)}"
        blocks.append(section)
        budget -= len(section)
        if budget <= 80:
            budget = 0

    if summary and budget > 120:
        section = f"## 最近\n{_clip(summary, min(budget - 40, 260))}"
        blocks.append(section)
        budget -= len(section)

    if diaries and budget > 80:
        parts = []
        for label, text in diaries:
            if budget <= 80:
                break
            piece = f"## {label}\n{_clip(text, max(60, budget - 20))}"
            parts.append(piece)
            budget -= len(piece)
        if parts:
            blocks.append("\n".join(parts))

    if not blocks:
        return ""

    parts = [HEADER]
    if hint:
        parts.append(hint)
    parts.extend(blocks)
    return "\n\n".join(parts)


def join_prompt(system_prompt: str, injection: str, position: str = "before") -> str:
    """把注入片段拼到系统提示词前/后。空片段原样返回。"""
    if not injection:
        return system_prompt or ""
    base = system_prompt or ""
    if not base.strip():
        return injection
    if position == "after":
        return f"{base}\n\n{injection}"
    return f"{injection}\n\n{base}"
