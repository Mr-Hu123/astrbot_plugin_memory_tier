"""分层记忆的落盘层：纯文本文件，可读、可手改、可用 git 备份。

目录结构：
    <data>/plugin_data/astrbot_plugin_memory_tier/
        <scope_key>/
            profile.md          画像：稳定特征，常驻注入
            summary.md          滚动摘要：最近在忙什么
            diary/2026-11-01.md 日记：当天发生了什么，每天一个文件
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

_SAFE = re.compile(r"[^0-9A-Za-z_\u4e00-\u9fff.-]+")

PROFILE_FILE = "profile.md"
SUMMARY_FILE = "summary.md"
DIARY_DIR = "diary"


def safe_key(raw: str) -> str:
    """把 unified_msg_origin 变成安全的目录名。

    `snowluma:FriendMessage:123456789` -> `snowluma-FriendMessage-123456789`
    """
    key = _SAFE.sub("-", (raw or "default").strip())
    key = key.strip("-.")
    return key or "default"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


def write_text(path: Path, content: str) -> None:
    """原子写：先写 .tmp 再替换，避免半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    tmp.replace(path)


def append_line(path: Path, line: str, max_lines: int = 400) -> None:
    line = " ".join((line or "").split())
    if not line:
        return
    lines = [ln for ln in read_text(path).splitlines() if ln.strip()]
    if line in lines:
        return
    lines.append(line)
    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]
    write_text(path, "\n".join(lines) + "\n")


def remove_lines(path: Path, keyword: str) -> int:
    keyword = (keyword or "").strip()
    if not keyword:
        return 0
    lines = read_text(path).splitlines()
    kept = [ln for ln in lines if keyword not in ln]
    removed = len(lines) - len(kept)
    if removed:
        write_text(path, "\n".join(kept).rstrip() + ("\n" if kept else ""))
    return removed


def tail_lines(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-limit:])


class MemoryStore:
    """一个 scope 对应一个目录。scope=global 时所有会话共用。"""

    def __init__(self, root: Path, scope: str = "per_user") -> None:
        self.root = Path(root)
        self.scope = scope if scope in {"per_user", "global"} else "per_user"
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- 路径 ----

    def base_dir(self, umo: str) -> Path:
        key = "global" if self.scope == "global" else safe_key(umo)
        return self.root / key

    def profile_path(self, umo: str) -> Path:
        return self.base_dir(umo) / PROFILE_FILE

    def summary_path(self, umo: str) -> Path:
        return self.base_dir(umo) / SUMMARY_FILE

    def diary_path(self, umo: str, day: date | None = None) -> Path:
        day = day or date.today()
        return self.base_dir(umo) / DIARY_DIR / f"{day.isoformat()}.md"

    # ---- 读 ----

    def profile(self, umo: str) -> str:
        return read_text(self.profile_path(umo)).strip()

    def summary(self, umo: str) -> str:
        return read_text(self.summary_path(umo)).strip()

    def diary(self, umo: str, day: date) -> str:
        return read_text(self.diary_path(umo, day)).strip()

    def recent_diaries(self, umo: str, days: int) -> list[tuple[str, str]]:
        """返回 [(日期, 内容)]，新的在前；跳过空文件。"""
        out: list[tuple[str, str]] = []
        if days <= 0:
            return out
        today = date.today()
        for offset in range(days):
            day = today - timedelta(days=offset)
            text = self.diary(umo, day)
            if text:
                label = "今天" if offset == 0 else ("昨天" if offset == 1 else day.isoformat())
                out.append((label, text))
        return out

    def all_diaries_text(self, umo: str, days: int = 14) -> str:
        chunks: list[str] = []
        today = date.today()
        for offset in range(days, 0, -1):
            day = today - timedelta(days=offset)
            text = self.diary(umo, day)
            if text:
                chunks.append(f"## {day.isoformat()}\n{text}")
        return "\n\n".join(chunks)

    # ---- 写 ----

    def remember(self, umo: str, line: str, max_lines: int = 400) -> None:
        append_line(self.profile_path(umo), line, max_lines=max_lines)

    def forget(self, umo: str, keyword: str) -> int:
        return remove_lines(self.profile_path(umo), keyword)

    def write_summary(self, umo: str, text: str) -> None:
        write_text(self.summary_path(umo), (text or "").strip() + "\n")

    def append_diary(self, umo: str, line: str, day: date | None = None) -> None:
        append_line(self.diary_path(umo, day), line, max_lines=20)

    def write_diary(self, umo: str, text: str, day: date | None = None) -> None:
        write_text(self.diary_path(umo, day), (text or "").strip() + "\n")

    def write_profile(self, umo: str, text: str) -> None:
        write_text(self.profile_path(umo), (text or "").strip() + "\n")

    def stats(self, umo: str) -> dict:
        base = self.base_dir(umo)
        diaries = sorted((base / DIARY_DIR).glob("*.md")) if (base / DIARY_DIR).exists() else []
        return {
            "dir": str(base),
            "profile_chars": len(self.profile(umo)),
            "summary_chars": len(self.summary(umo)),
            "diary_files": len(diaries),
            "updated": datetime.fromtimestamp(base.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            if base.exists()
            else "-",
        }
