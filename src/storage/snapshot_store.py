"""本地数据存储.

使用 JSON 文件存储每日快照，用于历史对比和增速计算。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from src.config import settings
from src.models import DailySnapshot

logger = logging.getLogger(__name__)


class SnapshotStore:
    """每日快照存储管理."""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or settings.data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _snapshot_path(self, date: str) -> Path:
        return self.data_dir / f"snapshot_{date}.json"

    def save_snapshot(self, snapshot: DailySnapshot) -> None:
        """保存每日快照."""
        path = self._snapshot_path(snapshot.date)
        data = snapshot.model_dump(mode="json")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("快照已保存: %s (%d 个仓库)", path.name, len(snapshot.repos))

    def load_snapshot(self, date: str) -> DailySnapshot | None:
        """加载指定日期的快照."""
        path = self._snapshot_path(date)
        if not path.exists():
            logger.debug("快照不存在: %s", date)
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return DailySnapshot.model_validate(data)
        except Exception as e:
            logger.error("加载快照失败 (%s): %s", date, e)
            return None

    def get_yesterday_stars(self) -> dict[str, int]:
        """获取昨日的 star 数据，用于计算增速加速度.

        Returns:
            字典 {full_name: star_count}
        """
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        snapshot = self.load_snapshot(yesterday)
        if snapshot:
            logger.info("已加载昨日快照 (%s): %d 个仓库", yesterday, len(snapshot.repos))
            return snapshot.repos
        logger.info("昨日快照不存在，增速加速度将使用默认值")
        return {}

    def save_today(self, repos: dict[str, int]) -> None:
        """保存今日数据为快照.

        Args:
            repos: {full_name: total_star_count}
        """
        today = datetime.now().strftime("%Y-%m-%d")
        snapshot = DailySnapshot(date=today, repos=repos)
        self.save_snapshot(snapshot)

    def list_snapshots(self) -> list[str]:
        """列出所有已保存的快照日期."""
        dates = []
        for path in sorted(self.data_dir.glob("snapshot_*.json")):
            date = path.stem.replace("snapshot_", "")
            dates.append(date)
        return dates

    # ---- 推送去重记录 ----

    @property
    def _notified_path(self) -> Path:
        return self.data_dir / "notified_repos.json"

    def load_notified_repos(self) -> dict[str, dict]:
        """加载推送记录.

        Returns:
            {full_name: {"last_notified": "2026-04-06", "score": 85.0, "count": 2}}
        """
        path = self._notified_path
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data
        except Exception as e:
            logger.error("加载推送记录失败: %s", e)
            return {}

    def save_notified_repos(self, records: dict[str, dict]) -> None:
        """保存推送记录."""
        path = self._notified_path
        path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("推送记录已保存: %d 条", len(records))

    def update_notified(
        self,
        full_names: list[str],
        scores: dict[str, float] | None = None,
    ) -> None:
        """更新推送记录（推送成功后调用）.

        Args:
            full_names: 本次推送的仓库列表
            scores: {full_name: score}，可选
        """
        scores = scores or {}
        today = datetime.now().strftime("%Y-%m-%d")
        records = self.load_notified_repos()

        for name in full_names:
            if name in records:
                records[name]["last_notified"] = today
                records[name]["count"] = records[name].get("count", 0) + 1
                records[name]["score"] = scores.get(name, records[name].get("score", 0))
            else:
                records[name] = {
                    "first_notified": today,
                    "last_notified": today,
                    "count": 1,
                    "score": scores.get(name, 0),
                }

        self.save_notified_repos(records)
        logger.info("推送记录已更新: 本次 %d 个项目", len(full_names))

    def get_recently_notified(self, cooldown_days: int = 3) -> dict[str, float]:
        """获取冷却期内已推送的项目.

        Args:
            cooldown_days: 冷却天数

        Returns:
            {full_name: last_score} 冷却期内已推送的项目及上次得分
        """
        records = self.load_notified_repos()
        cutoff = (datetime.now() - timedelta(days=cooldown_days)).strftime("%Y-%m-%d")
        result = {}

        for name, info in records.items():
            if info.get("last_notified", "") >= cutoff:
                result[name] = info.get("score", 0)

        return result

    def cleanup_old_notified(self, keep_days: int = 30) -> int:
        """清理超过指定天数的推送记录.

        Returns:
            清理的记录数
        """
        records = self.load_notified_repos()
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        to_remove = [
            name for name, info in records.items()
            if info.get("last_notified", "") < cutoff
        ]
        for name in to_remove:
            del records[name]
        if to_remove:
            self.save_notified_repos(records)
            logger.info("已清理 %d 条过期推送记录", len(to_remove))
        return len(to_remove)

    def cleanup_old_snapshots(self, keep_days: int = 30) -> int:
        """清理超过指定天数的旧快照.

        Returns:
            删除的快照数量
        """
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        deleted = 0
        for path in self.data_dir.glob("snapshot_*.json"):
            date = path.stem.replace("snapshot_", "")
            if date < cutoff:
                path.unlink()
                deleted += 1
                logger.debug("已删除旧快照: %s", date)
        if deleted:
            logger.info("已清理 %d 个旧快照 (保留 %d 天)", deleted, keep_days)
        return deleted
