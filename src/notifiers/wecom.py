"""企业微信 Webhook 推送.

将报告摘要推送到企业微信群机器人。
企业微信 Webhook 支持 Markdown 格式消息，单条消息最大 4096 字节。
"""

from __future__ import annotations

import logging

import httpx

from src.config import settings
from src.models import ScoredRepo

logger = logging.getLogger(__name__)

# 企业微信 Markdown 消息单条最大字节数
WECOM_MAX_BYTES = 4096


class WeComNotifier:
    """企业微信群机器人推送."""

    def __init__(self, webhook_url: str = "") -> None:
        self.webhook_url = webhook_url or settings.wecom_webhook_url

    def notify(self, repos: list[ScoredRepo], top_n: int = 10) -> bool:
        """推送热点速报到企业微信.

        Args:
            repos: 按分数排序的仓库列表
            top_n: 推送的项目数量（企微消息有长度限制，建议 ≤ 15）

        Returns:
            是否推送成功
        """
        if not self.webhook_url:
            logger.warning("未配置企业微信 Webhook URL，跳过推送")
            return False

        display = repos[:top_n]
        content = self._build_message(display, total=len(repos))

        # 如果超长，逐步减少项目数
        while len(content.encode("utf-8")) > WECOM_MAX_BYTES and top_n > 3:
            top_n -= 1
            display = repos[:top_n]
            content = self._build_message(display, total=len(repos))
            logger.debug("消息过长，缩减至 Top %d", top_n)

        return self._send_markdown(content)

    def _build_message(self, repos: list[ScoredRepo], total: int) -> str:
        """构建企业微信 Markdown 格式消息."""
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines: list[str] = []

        lines.append(f"# 🔥 GitHub 热点速报")
        lines.append(f"> 时间: {today} | 共发现 **{total}** 个热门项目，展示 Top {len(repos)}")
        lines.append("")

        for rank, repo in enumerate(repos, 1):
            # 排名标记
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")

            # 爆发标签
            burst = " ".join(bt.emoji for bt in repo.burst_types) if repo.burst_types else ""

            lines.append(
                f"**{medal} [{repo.full_name}]"
                f"({repo.url})**"
                f" ⭐+{repo.stars_today:,} "
                f"(共{repo.total_stars:,})"
                f" | {repo.category} | {repo.language or 'N/A'}"
                f" | 评分:**{repo.score:.1f}** {burst}"
            )

            if repo.description:
                # 截断过长的描述
                desc = repo.description
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                lines.append(f"> {desc}")

            lines.append("")

        lines.append("---")
        lines.append(f"*由 GitHub Hot Hub 自动生成*")

        return "\n".join(lines)

    def _send_markdown(self, content: str) -> bool:
        """发送 Markdown 格式消息到企业微信."""
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": content,
            },
        }

        try:
            resp = httpx.post(
                self.webhook_url,
                json=payload,
                timeout=settings.request_timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("errcode") == 0:
                logger.info("✅ 企业微信推送成功")
                return True
            else:
                logger.error(
                    "企业微信推送失败: errcode=%s, errmsg=%s",
                    data.get("errcode"),
                    data.get("errmsg"),
                )
                return False

        except httpx.HTTPError as e:
            logger.error("企业微信推送请求失败: %s", e)
            return False

    def send_text(self, text: str) -> bool:
        """发送纯文本消息（备用方法）."""
        if not self.webhook_url:
            logger.warning("未配置企业微信 Webhook URL，跳过推送")
            return False

        payload = {
            "msgtype": "text",
            "text": {
                "content": text,
            },
        }

        try:
            resp = httpx.post(
                self.webhook_url,
                json=payload,
                timeout=settings.request_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("errcode") == 0
        except httpx.HTTPError as e:
            logger.error("企业微信文本推送失败: %s", e)
            return False
