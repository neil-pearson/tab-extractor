"""
Supabase database interface.
Handles all reads and writes for the TAB racing overlay hunter.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from supabase import create_client, Client

logger = logging.getLogger(__name__)


class DB:
    def __init__(self, url: str, key: str):
        self.client: Client = create_client(url, key)

    # ------------------------------------------------------------------
    # Meetings
    # ------------------------------------------------------------------

    def upsert_meeting(self, meeting: dict) -> Optional[dict]:
        try:
            res = self.client.table("meetings").upsert(meeting).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            logger.error(f"upsert_meeting error: {e}")
            return None

    # ------------------------------------------------------------------
    # Races
    # ------------------------------------------------------------------

    def upsert_race(self, race: dict) -> Optional[dict]:
        try:
            res = self.client.table("races").upsert(race).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            logger.error(f"upsert_race error: {e}")
            return None

    def get_upcoming_races(self, within_seconds: int = 60) -> list[dict]:
        """
        Get races jumping within the next N seconds.
        Used by the scheduler to know what to snapshot.
        """
        try:
            now = datetime.now(timezone.utc)
            from_time = now.isoformat()
            to_time = (now + timedelta(seconds=within_seconds)).isoformat()
            res = (
                self.client.table("races")
                .select("*")
                .eq("status", "upcoming")
                .gte("jump_time", from_time)
                .lte("jump_time", to_time)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.error(f"get_upcoming_races error: {e}")
            return []

    def get_races_needing_results(self) -> list[dict]:
        """
        Get races that have run but don't have a result yet.
        Status = 'closed', no matching result row.
        """
        try:
            res = (
                self.client.table("races")
                .select("*, results(id)")
                .eq("status", "closed")
                .is_("results.id", "null")
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.error(f"get_races_needing_results error: {e}")
            return []

    def update_race_status(self, race_id: str, status: str):
        try:
            self.client.table("races").update({"status": status}).eq("id", race_id).execute()
        except Exception as e:
            logger.error(f"update_race_status error: {e}")

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def insert_snapshot(self, snapshot: dict) -> Optional[dict]:
        import json
        # Supabase Python client needs jsonb columns passed as JSON strings
        jsonb_cols = [
            "win_odds", "quinella_approx", "exacta_approx", "trifecta_approx",
            "quinella_fair", "exacta_fair", "trifecta_fair",
            "quinella_edge", "exacta_edge", "trifecta_edge",
            "quinella_top3", "exacta_top3", "trifecta_top3",
        ]
        cleaned = {}
        for k, v in snapshot.items():
            if k in jsonb_cols and isinstance(v, (dict, list)):
                cleaned[k] = json.dumps(v)
            else:
                cleaned[k] = v
        try:
            res = self.client.table("snapshots").insert(cleaned).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            logger.error(f"insert_snapshot error: {e}")
            return None

    def snapshot_exists(self, race_id: str) -> bool:
        """Check if we've already snapshotted this race."""
        try:
            res = (
                self.client.table("snapshots")
                .select("id")
                .eq("race_id", race_id)
                .limit(1)
                .execute()
            )
            return len(res.data) > 0
        except Exception as e:
            logger.error(f"snapshot_exists error: {e}")
            return False

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def insert_result(self, result: dict) -> Optional[dict]:
        try:
            res = self.client.table("results").upsert(result).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            logger.error(f"insert_result error: {e}")
            return None

    def result_exists(self, race_id: str) -> bool:
        try:
            res = (
                self.client.table("results")
                .select("id")
                .eq("race_id", race_id)
                .limit(1)
                .execute()
            )
            return len(res.data) > 0
        except Exception as e:
            logger.error(f"result_exists error: {e}")
            return False
