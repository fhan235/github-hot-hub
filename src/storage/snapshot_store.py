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
