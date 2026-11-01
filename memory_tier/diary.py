"""把聊天记录压成日记 / 画像：只在你主动敲命令时调用模型，平时零开销。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("astrbot")

DEFAULT_DIARY_PROMPT = (
    "把下面这段对话压成日记，最多三行，第一人称，只写发生了什么和情绪变化，"
    "不要复述原句，不要加标题和标点结尾："
)
DEFAULT_PROFILE_PROMPT = (
    "根据下面的日记，提炼这个人的稳定特征，最多 8 行，每行一个短句，"
    "格式为「- 特征」。只写有证据的，不要猜："
)


def collect_text(messages: Any, max_chars: int = 6000) -> str:
    """从 req.contexts 里抽出纯文本对话，图片压成 [图] 占位。"""
    if not messages:
        return ""
    chunks: list[str] = []
    for msg in messages:
        try:
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
            if role in {"system", None}:
                continue
            who = "他" if role == "user" else "我"
            parts: list[str] = []
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    ptype = str(part.get("type", "")).lower()
                    if ptype == "text":
                        parts.append(str(part.get("text", "")))
                    elif ptype in {"image_url", "image"}:
                        parts.append("[图]")
            line = " ".join(" ".join(parts).split())
            if line:
                chunks.append(f"{who}：{line}")
        except Exception:  # 单条坏消息不该拖垮整次整理
            continue
    text = "\n".join(chunks)
    if max_chars > 0 and len(text) > max_chars:
        text = text[-max_chars:]
    return text


def normalize_lines(text: str, max_lines: int = 3, max_chars: int = 300) -> str:
    """清掉模型爱加的列表符号 / 空行，只留前 N 行。"""
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*•").lstrip("0123456789.").strip()
        if not line:
            continue
        out.append(line)
        if len(out) >= max_lines:
            break
    joined = "\n".join(out)
    if max_chars > 0 and len(joined) > max_chars:
        joined = joined[:max_chars].rstrip()
    return joined


async def ask(context: Any, umo: str | None, prompt: str) -> str:
    """用当前会话的模型问一次；失败返回空串。"""
    try:
        provider = context.get_using_provider(umo=umo)
    except Exception:
        provider = None
    if provider is None:
        return ""
    try:
        resp = await provider.text_chat(prompt=prompt, contexts=[], system_prompt=None)
    except Exception as exc:
        logger.warning("[memory_tier] 调用模型失败: %s", exc)
        return ""
    text = getattr(resp, "completion_text", None)
    if text is None:
        text = getattr(resp, "text", None) or ""
    return str(text).strip()
