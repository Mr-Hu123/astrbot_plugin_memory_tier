"""分层记忆插件（astrbot_plugin_memory_tier）。

设计目标：让「长期记忆」不占用每轮上下文。
    L1 浅层   最近若干轮原文   —— 交给 AstrBot 自带的上下文压缩
    L2 中层   滚动摘要 summary —— 由 /总结 维护，注入约 200 字
    L3 深层   画像 + 每日日记  —— 常驻注入，按天累积

平时只做一件事：把 profile + summary + 最近日记拼成一小段文字塞进系统提示词。
写记忆全部是显式命令，不偷偷调模型，token 花在哪儿一眼能看见。
"""

from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools

from .memory_tier import diary as diary_mod
from .memory_tier import inject as inject_mod
from .memory_tier.store import MemoryStore

PLUGIN_NAME = "astrbot_plugin_memory_tier"


class MemoryTierPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config: dict = config or {}

        try:
            data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        except Exception:
            data_dir = Path("data") / "plugin_data" / PLUGIN_NAME
        self.store = MemoryStore(Path(data_dir), str(self._cfg("storage.scope", "per_user")))

        cache_size = int(self._cfg("storage.recent_cache", 40) or 0)
        self._cache_size = max(0, cache_size)
        self._recent: dict[str, deque] = {}
        self._announced: set[str] = set()

    # ---------- 配置读取 ----------

    def _cfg(self, key: str, default: Any = None) -> Any:
        node: Any = self.config
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return default if node is None else node

    def _enabled(self) -> bool:
        return bool(self._cfg("enabled", True))

    # ---------- 近期消息缓存（只存内存，供 /总结 使用） ----------

    def _cache(self, umo: str, req: ProviderRequest) -> None:
        if self._cache_size <= 0:
            return
        buf = self._recent.get(umo)
        if buf is None:
            buf = deque(maxlen=self._cache_size)
            self._recent[umo] = buf
        for msg in (getattr(req, "contexts", None) or [])[-4:]:
            if isinstance(msg, dict):
                buf.append(msg)

    # ---------- 注入 ----------

    @filter.on_llm_request()
    async def inject_memory(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
        if not self._enabled():
            return
        umo = getattr(event, "unified_msg_origin", "default")
        try:
            self._cache(umo, req)
        except Exception:
            pass
        if not self._cfg("inject.enabled", True):
            return
        try:
            text = inject_mod.build(
                self.store,
                umo,
                max_chars=int(self._cfg("inject.max_chars", 700)),
                include_profile=bool(self._cfg("inject.include_profile", True)),
                profile_max_lines=int(self._cfg("inject.profile_max_lines", 12)),
                summary_enabled=bool(self._cfg("inject.summary_enabled", True)),
                diary_days=int(self._cfg("inject.diary_days", 1)),
            )
            if text:
                req.system_prompt = inject_mod.join_prompt(
                    req.system_prompt or "", text, str(self._cfg("inject.position", "before"))
                )
                if umo not in self._announced:
                    self._announced.add(umo)
                    logger.info("[memory_tier] 注入长期记忆 %s 字（%s）", len(text), umo)
                else:
                    logger.debug("[memory_tier] 注入 %s 字", len(text))
        except Exception as exc:  # 注入失败绝不能让本轮对话崩掉
            logger.warning("[memory_tier] 注入失败: %s", exc)

    # ---------- 命令 ----------

    def _args(self, event: AstrMessageEvent, command: str) -> str:
        text = (getattr(event, "message_str", "") or "").strip()
        for prefix in ("/", "／"):
            if text.startswith(prefix):
                text = text[len(prefix) :].lstrip()
                break
        if text.startswith(command):
            text = text[len(command) :]
        return text.strip()

    def _denied(self, event: AstrMessageEvent) -> bool:
        if not self._cfg("commands.enabled", True):
            return True
        if not self._cfg("commands.admin_only", False):
            return False
        try:
            admins = self.context.get_config().get("admins_id", []) or []
            return getattr(event, "get_sender_id", lambda: "")() not in admins
        except Exception:
            return False

    @filter.command("记忆")
    async def cmd_status(self, event: AstrMessageEvent) -> None:
        if self._denied(event):
            return
        umo = event.unified_msg_origin
        st = self.store.stats(umo)
        preview = inject_mod.build(
            self.store,
            umo,
            max_chars=int(self._cfg("inject.max_chars", 700)),
            include_profile=bool(self._cfg("inject.include_profile", True)),
            profile_max_lines=int(self._cfg("inject.profile_max_lines", 12)),
            summary_enabled=bool(self._cfg("inject.summary_enabled", True)),
            diary_days=int(self._cfg("inject.diary_days", 1)),
        )
        lines = [
            "记忆状态",
            f"画像 {st['profile_chars']} 字 / 摘要 {st['summary_chars']} 字 / 日记 {st['diary_files']} 天",
            f"注入 {len(preview)} 字（上限 {self._cfg('inject.max_chars', 700)}）",
            f"目录 {st['dir']}",
        ]
        if preview:
            lines += ["", "— 当前注入 —", preview]
        yield event.plain_result("\n".join(lines))

    @filter.command("记住")
    async def cmd_remember(self, event: AstrMessageEvent) -> None:
        if self._denied(event):
            return
        text = self._args(event, "记住")
        if not text:
            yield event.plain_result("用法：/记住 他喜欢喝冰美式，不加糖")
            return
        self.store.remember(event.unified_msg_origin, text)
        yield event.plain_result(f"记住了：{text}")

    @filter.command("忘掉")
    async def cmd_forget(self, event: AstrMessageEvent) -> None:
        if self._denied(event):
            return
        if not self._cfg("commands.allow_delete", True):
            yield event.plain_result("删除已关闭（commands.allow_delete=false）")
            return
        keyword = self._args(event, "忘掉")
        if not keyword:
            yield event.plain_result("用法：/忘掉 关键词")
            return
        removed = self.store.forget(event.unified_msg_origin, keyword)
        yield event.plain_result(f"删掉了 {removed} 条包含「{keyword}」的记忆" if removed else f"没找到包含「{keyword}」的记忆")

    @filter.command("记下")
    async def cmd_note(self, event: AstrMessageEvent) -> None:
        if self._denied(event):
            return
        text = self._args(event, "记下")
        if not text:
            yield event.plain_result("用法：/记下 今天他加班到十点")
            return
        self.store.append_diary(event.unified_msg_origin, f"- {text}")
        yield event.plain_result(f"记到今天的日记了：{text}")

    @filter.command("日记")
    async def cmd_diary(self, event: AstrMessageEvent) -> None:
        if self._denied(event):
            return
        arg = self._args(event, "日记").strip()
        umo = event.unified_msg_origin
        if arg:
            try:
                day = datetime.strptime(arg, "%Y-%m-%d").date()
            except ValueError:
                yield event.plain_result("日期格式要 2026-11-01 这样")
                return
            text = self.store.diary(umo, day)
            yield event.plain_result(f"{day.isoformat()}\n{text}" if text else f"{day.isoformat()} 没有日记")
            return
        parts: list[str] = []
        today = date.today()
        for offset in range(2):
            day = today - timedelta(days=offset)
            text = self.store.diary(umo, day)
            if text:
                parts.append(f"{day.isoformat()}\n{text}")
        yield event.plain_result("\n\n".join(parts) if parts else "还没有日记，试试 /总结 或 /记下")

    @filter.command("总结")
    async def cmd_summarize(self, event: AstrMessageEvent) -> None:
        if self._denied(event):
            return
        umo = event.unified_msg_origin
        if not self._cfg("summarize.enabled", True):
            yield event.plain_result("自动整理已关闭（summarize.enabled=false）")
            return
        buf = list(self._recent.get(umo, []))
        body = diary_mod.collect_text(buf, max_chars=6000)
        if not body:
            yield event.plain_result("还没攒够对话，先聊几句再 /总结")
            return
        prompt = str(self._cfg("summarize.diary_prompt", "") or diary_mod.DEFAULT_DIARY_PROMPT)
        raw = await diary_mod.ask(self.context, umo, f"{prompt}\n\n{body}")
        if not raw:
            yield event.plain_result("模型没回话，稍后再试")
            return
        text = diary_mod.normalize_lines(
            raw, max_lines=3, max_chars=int(self._cfg("summarize.max_output_chars", 300))
        )
        if not text:
            yield event.plain_result("整理结果为空，什么也没写")
            return
        self.store.write_diary(umo, text)
        yield event.plain_result(f"今天的日记写好了：\n{text}")

    @filter.command("画像")
    async def cmd_profile(self, event: AstrMessageEvent) -> None:
        if self._denied(event):
            return
        umo = event.unified_msg_origin
        if not self._cfg("summarize.enabled", True):
            yield event.plain_result("自动整理已关闭（summarize.enabled=false）")
            return
        body = self.store.all_diaries_text(umo, days=14)
        if not body:
            yield event.plain_result("还没有日记，先 /总结 几次再来")
            return
        prompt = str(self._cfg("summarize.profile_prompt", "") or diary_mod.DEFAULT_PROFILE_PROMPT)
        raw = await diary_mod.ask(self.context, umo, f"{prompt}\n\n{body}")
        if not raw:
            yield event.plain_result("模型没回话，稍后再试")
            return
        text = diary_mod.normalize_lines(
            raw, max_lines=8, max_chars=int(self._cfg("summarize.max_output_chars", 300))
        )
        if not text:
            yield event.plain_result("整理结果为空，什么也没写")
            return
        self.store.write_profile(umo, text)
        yield event.plain_result(f"画像更新了：\n{text}")
