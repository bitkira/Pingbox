from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .common import (
    canonical_agent_label,
    canonical_group_label,
    new_id,
    normalize_handle,
    now_iso,
)


class OpenChatError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code


@dataclass
class ResolvedTarget:
    type: str
    uid: str
    handle: str
    display_name: str

    @property
    def label(self) -> str:
        if self.type == "agent":
            return canonical_agent_label(self.display_name, self.handle)
        return canonical_group_label(self.display_name, self.handle)


class OpenChatStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def tx(self) -> Iterable[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.tx() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS agents (
                    agent_uid TEXT PRIMARY KEY,
                    handle TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    auth_token TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS groups (
                    group_uid TEXT PRIMARY KEY,
                    handle TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    created_by_agent_uid TEXT NOT NULL REFERENCES agents(agent_uid),
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS direct_relations (
                    agent_a_uid TEXT NOT NULL REFERENCES agents(agent_uid),
                    agent_b_uid TEXT NOT NULL REFERENCES agents(agent_uid),
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    removed_at TEXT,
                    PRIMARY KEY (agent_a_uid, agent_b_uid)
                );

                CREATE TABLE IF NOT EXISTS group_memberships (
                    group_uid TEXT NOT NULL REFERENCES groups(group_uid),
                    agent_uid TEXT NOT NULL REFERENCES agents(agent_uid),
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    left_at TEXT,
                    left_seq INTEGER,
                    PRIMARY KEY (group_uid, agent_uid)
                );

                CREATE TABLE IF NOT EXISTS relation_requests (
                    request_uid TEXT PRIMARY KEY,
                    source_agent_uid TEXT NOT NULL REFERENCES agents(agent_uid),
                    target_type TEXT NOT NULL,
                    target_uid TEXT NOT NULL,
                    message TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    handled_at TEXT
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_uid TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    direct_key TEXT UNIQUE,
                    group_uid TEXT UNIQUE REFERENCES groups(group_uid)
                );

                CREATE TABLE IF NOT EXISTS conversation_participants (
                    conversation_uid TEXT NOT NULL REFERENCES conversations(conversation_uid),
                    agent_uid TEXT NOT NULL REFERENCES agents(agent_uid),
                    joined_seq INTEGER NOT NULL DEFAULT 0,
                    left_seq INTEGER,
                    PRIMARY KEY (conversation_uid, agent_uid)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_uid TEXT PRIMARY KEY,
                    conversation_uid TEXT NOT NULL REFERENCES conversations(conversation_uid),
                    seq INTEGER NOT NULL,
                    sender_agent_uid TEXT NOT NULL REFERENCES agents(agent_uid),
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (conversation_uid, seq)
                );

                CREATE TABLE IF NOT EXISTS conversation_inbox_state (
                    agent_uid TEXT NOT NULL REFERENCES agents(agent_uid),
                    conversation_uid TEXT NOT NULL REFERENCES conversations(conversation_uid),
                    last_read_seq INTEGER NOT NULL DEFAULT 0,
                    active_for_notifications INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (agent_uid, conversation_uid)
                );

                CREATE TABLE IF NOT EXISTS conversation_visibility_windows (
                    conversation_uid TEXT NOT NULL REFERENCES conversations(conversation_uid),
                    agent_uid TEXT NOT NULL REFERENCES agents(agent_uid),
                    start_seq INTEGER NOT NULL,
                    end_seq INTEGER,
                    PRIMARY KEY (conversation_uid, agent_uid, start_seq)
                );

                CREATE INDEX IF NOT EXISTS idx_relation_requests_target
                    ON relation_requests (target_type, target_uid, status);
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_created_at
                    ON messages (conversation_uid, created_at DESC, seq DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_text
                    ON messages (text);
                CREATE INDEX IF NOT EXISTS idx_visibility_windows_agent
                    ON conversation_visibility_windows (agent_uid, conversation_uid, start_seq, end_seq);
                """
            )

    def register_agent(self, handle: str, display_name: str) -> dict[str, str]:
        created_at = now_iso()
        agent_uid = new_id("agt")
        normalized_handle = normalize_handle(handle)
        with self.tx() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO agents (agent_uid, handle, display_name, auth_token, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        agent_uid,
                        normalized_handle,
                        display_name.strip() or normalized_handle,
                        new_id("tok"),
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise OpenChatError("handle_taken") from exc
        return {
            "agent_uid": agent_uid,
            "handle": normalized_handle,
            "display_name": display_name.strip() or normalized_handle,
            "created_at": created_at,
        }

    def create_group(self, caller_uid: str, handle: str, display_name: str) -> dict[str, str]:
        created_at = now_iso()
        group_uid = new_id("grp")
        conversation_uid = new_id("cnv")
        normalized_handle = normalize_handle(handle)
        with self.tx() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO groups (group_uid, handle, display_name, created_by_agent_uid, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (group_uid, normalized_handle, display_name.strip() or normalized_handle, caller_uid, created_at),
                )
                conn.execute(
                    """
                    INSERT INTO conversations (conversation_uid, type, group_uid)
                    VALUES (?, 'group', ?)
                    """,
                    (conversation_uid, group_uid),
                )
                conn.execute(
                    """
                    INSERT INTO group_memberships (group_uid, agent_uid, role, status, joined_at, left_seq)
                    VALUES (?, ?, 'admin', 'active', ?, NULL)
                    """,
                    (group_uid, caller_uid, created_at),
                )
                conn.execute(
                    """
                    INSERT INTO conversation_participants (conversation_uid, agent_uid, joined_seq)
                    VALUES (?, ?, 0)
                    """,
                    (conversation_uid, caller_uid),
                )
                conn.execute(
                    """
                    INSERT INTO conversation_inbox_state (agent_uid, conversation_uid, last_read_seq, active_for_notifications)
                    VALUES (?, ?, 0, 1)
                    """,
                    (caller_uid, conversation_uid),
                )
                conn.execute(
                    """
                    INSERT INTO conversation_visibility_windows (conversation_uid, agent_uid, start_seq, end_seq)
                    VALUES (?, ?, 1, NULL)
                    """,
                    (conversation_uid, caller_uid),
                )
            except sqlite3.IntegrityError as exc:
                raise OpenChatError("handle_taken") from exc
        return {
            "group_uid": group_uid,
            "handle": normalized_handle,
            "display_name": display_name.strip() or normalized_handle,
            "created_at": created_at,
        }

    def get_agent(self, agent_uid: str) -> sqlite3.Row | None:
        with self.tx() as conn:
            return conn.execute(
                "SELECT * FROM agents WHERE agent_uid = ? AND status = 'active'",
                (agent_uid,),
            ).fetchone()

    def _resolve_target(self, conn: sqlite3.Connection, target_type: str, raw_id: str) -> ResolvedTarget:
        if target_type not in {"agent", "group"}:
            raise OpenChatError("invalid_target")
        table = "agents" if target_type == "agent" else "groups"
        pk = "agent_uid" if target_type == "agent" else "group_uid"
        raw = raw_id.strip()
        if not raw:
            raise OpenChatError("invalid_target")
        row = conn.execute(
            f"SELECT {pk} AS uid, handle, display_name FROM {table} WHERE {pk} = ?",
            (raw,),
        ).fetchone()
        if row:
            return ResolvedTarget(target_type, row["uid"], row["handle"], row["display_name"])
        row = conn.execute(
            f"SELECT {pk} AS uid, handle, display_name FROM {table} WHERE handle = ?",
            (normalize_handle(raw),),
        ).fetchone()
        if row:
            return ResolvedTarget(target_type, row["uid"], row["handle"], row["display_name"])
        rows = conn.execute(
            f"SELECT {pk} AS uid, handle, display_name FROM {table} WHERE lower(display_name) = lower(?)",
            (raw,),
        ).fetchall()
        if len(rows) > 1:
            raise OpenChatError("ambiguous_target")
        if len(rows) == 1:
            row = rows[0]
            return ResolvedTarget(target_type, row["uid"], row["handle"], row["display_name"])
        raise OpenChatError("target_not_found")

    def _direct_key(self, agent_a_uid: str, agent_b_uid: str) -> tuple[str, str, str]:
        a_uid, b_uid = sorted((agent_a_uid, agent_b_uid))
        return a_uid, b_uid, f"{a_uid}:{b_uid}"

    def _ensure_direct_conversation(
        self, conn: sqlite3.Connection, agent_a_uid: str, agent_b_uid: str
    ) -> sqlite3.Row:
        a_uid, b_uid, direct_key = self._direct_key(agent_a_uid, agent_b_uid)
        row = conn.execute(
            "SELECT * FROM conversations WHERE direct_key = ?",
            (direct_key,),
        ).fetchone()
        if row:
            for uid in (a_uid, b_uid):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO conversation_participants (conversation_uid, agent_uid, joined_seq)
                    VALUES (?, ?, 0)
                    """,
                    (row["conversation_uid"], uid),
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO conversation_inbox_state (agent_uid, conversation_uid, last_read_seq, active_for_notifications)
                    VALUES (?, ?, 0, 1)
                    """,
                    (uid, row["conversation_uid"]),
                )
            return row
        conversation_uid = new_id("cnv")
        conn.execute(
            """
            INSERT INTO conversations (conversation_uid, type, direct_key)
            VALUES (?, 'direct', ?)
            """,
            (conversation_uid, direct_key),
        )
        for uid in (a_uid, b_uid):
            conn.execute(
                """
                INSERT INTO conversation_participants (conversation_uid, agent_uid, joined_seq)
                VALUES (?, ?, 0)
                """,
                (conversation_uid, uid),
            )
            conn.execute(
                """
                INSERT INTO conversation_inbox_state (agent_uid, conversation_uid, last_read_seq, active_for_notifications)
                VALUES (?, ?, 0, 1)
                """,
                (uid, conversation_uid),
            )
        return conn.execute(
            "SELECT * FROM conversations WHERE conversation_uid = ?",
            (conversation_uid,),
        ).fetchone()

    def _ensure_group_conversation(self, conn: sqlite3.Connection, group_uid: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM conversations WHERE group_uid = ?",
            (group_uid,),
        ).fetchone()
        if row:
            return row
        conversation_uid = new_id("cnv")
        conn.execute(
            """
            INSERT INTO conversations (conversation_uid, type, group_uid)
            VALUES (?, 'group', ?)
            """,
            (conversation_uid, group_uid),
        )
        return conn.execute(
            "SELECT * FROM conversations WHERE conversation_uid = ?",
            (conversation_uid,),
        ).fetchone()

    def _conversation_max_seq(self, conn: sqlite3.Connection, conversation_uid: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS max_seq FROM messages WHERE conversation_uid = ?",
            (conversation_uid,),
        ).fetchone()
        return int(row["max_seq"])

    def _visible_group_upper_seq(
        self, conn: sqlite3.Connection, conversation_uid: str, caller_uid: str
    ) -> int | None:
        participant = conn.execute(
            """
            SELECT left_seq FROM conversation_participants
            WHERE conversation_uid = ? AND agent_uid = ?
            """,
            (conversation_uid, caller_uid),
        ).fetchone()
        if not participant:
            return None
        if participant["left_seq"] is not None:
            return int(participant["left_seq"])
        return None

    def _visible_group_windows(
        self, conn: sqlite3.Connection, conversation_uid: str, caller_uid: str
    ) -> list[tuple[int, int | None]]:
        rows = conn.execute(
            """
            SELECT start_seq, end_seq
            FROM conversation_visibility_windows
            WHERE conversation_uid = ? AND agent_uid = ?
            ORDER BY start_seq ASC
            """,
            (conversation_uid, caller_uid),
        ).fetchall()
        if rows:
            return [
                (int(row["start_seq"]), int(row["end_seq"]) if row["end_seq"] is not None else None)
                for row in rows
            ]
        participant = conn.execute(
            """
            SELECT joined_seq, left_seq
            FROM conversation_participants
            WHERE conversation_uid = ? AND agent_uid = ?
            """,
            (conversation_uid, caller_uid),
        ).fetchone()
        if not participant:
            return []
        return [
            (
                int(participant["joined_seq"]) + 1,
                int(participant["left_seq"]) if participant["left_seq"] is not None else None,
            )
        ]

    def _current_group_window_floor_seq(
        self, conn: sqlite3.Connection, conversation_uid: str, caller_uid: str
    ) -> int:
        row = conn.execute(
            """
            SELECT start_seq
            FROM conversation_visibility_windows
            WHERE conversation_uid = ? AND agent_uid = ? AND end_seq IS NULL
            ORDER BY start_seq DESC
            LIMIT 1
            """,
            (conversation_uid, caller_uid),
        ).fetchone()
        if row:
            return max(0, int(row["start_seq"]) - 1)
        participant = conn.execute(
            """
            SELECT joined_seq
            FROM conversation_participants
            WHERE conversation_uid = ? AND agent_uid = ? AND left_seq IS NULL
            """,
            (conversation_uid, caller_uid),
        ).fetchone()
        if not participant:
            return 0
        return int(participant["joined_seq"])

    def _group_visibility_filters(
        self,
        conn: sqlite3.Connection,
        conversation_uid: str,
        caller_uid: str,
        *,
        alias: str = "m",
    ) -> tuple[list[str], list[Any]]:
        windows = self._visible_group_windows(conn, conversation_uid, caller_uid)
        if not windows:
            return [f"{alias}.seq < 0"], []
        clauses: list[str] = []
        params: list[Any] = []
        for start_seq, end_seq in windows:
            if end_seq is None:
                clauses.append(f"{alias}.seq >= ?")
                params.append(start_seq)
            else:
                clauses.append(f"({alias}.seq >= ? AND {alias}.seq <= ?)")
                params.extend([start_seq, end_seq])
        return ["(" + " OR ".join(clauses) + ")"], params

    def _can_read_direct(self, conn: sqlite3.Connection, caller_uid: str, target_uid: str) -> bool:
        a_uid, b_uid, _ = self._direct_key(caller_uid, target_uid)
        relation = conn.execute(
            """
            SELECT status FROM direct_relations
            WHERE agent_a_uid = ? AND agent_b_uid = ?
            """,
            (a_uid, b_uid),
        ).fetchone()
        if relation:
            return True
        conversation = conn.execute(
            """
            SELECT c.conversation_uid
            FROM conversations c
            JOIN conversation_participants p ON p.conversation_uid = c.conversation_uid
            WHERE c.direct_key = ? AND p.agent_uid = ?
            """,
            (f"{a_uid}:{b_uid}", caller_uid),
        ).fetchone()
        return conversation is not None

    def _is_direct_related(self, conn: sqlite3.Connection, caller_uid: str, target_uid: str) -> bool:
        a_uid, b_uid, _ = self._direct_key(caller_uid, target_uid)
        relation = conn.execute(
            """
            SELECT status FROM direct_relations
            WHERE agent_a_uid = ? AND agent_b_uid = ?
            """,
            (a_uid, b_uid),
        ).fetchone()
        return bool(relation and relation["status"] == "active")

    def _is_group_related(self, conn: sqlite3.Connection, caller_uid: str, group_uid: str) -> bool:
        membership = conn.execute(
            """
            SELECT status FROM group_memberships
            WHERE group_uid = ? AND agent_uid = ?
            """,
            (group_uid, caller_uid),
        ).fetchone()
        return bool(membership and membership["status"] == "active")

    def _can_read_group(self, conn: sqlite3.Connection, caller_uid: str, group_uid: str) -> bool:
        membership = conn.execute(
            """
            SELECT status FROM group_memberships
            WHERE group_uid = ? AND agent_uid = ?
            """,
            (group_uid, caller_uid),
        ).fetchone()
        return membership is not None

    def _is_group_admin(self, conn: sqlite3.Connection, caller_uid: str, group_uid: str) -> bool:
        membership = conn.execute(
            """
            SELECT role, status FROM group_memberships
            WHERE group_uid = ? AND agent_uid = ?
            """,
            (group_uid, caller_uid),
        ).fetchone()
        return bool(membership and membership["status"] == "active" and membership["role"] == "admin")

    def _mark_inbox_activity(
        self,
        conn: sqlite3.Connection,
        conversation_uid: str,
        sender_uid: str,
        seq: int,
        recipient_uids: list[str],
    ) -> None:
        conn.execute(
            """
            INSERT INTO conversation_inbox_state (agent_uid, conversation_uid, last_read_seq, active_for_notifications)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(agent_uid, conversation_uid)
            DO UPDATE SET last_read_seq = excluded.last_read_seq, active_for_notifications = 1
            """,
            (sender_uid, conversation_uid, seq),
        )
        for uid in recipient_uids:
            conn.execute(
                """
                INSERT INTO conversation_inbox_state (agent_uid, conversation_uid, last_read_seq, active_for_notifications)
                VALUES (?, ?, COALESCE((SELECT last_read_seq FROM conversation_inbox_state WHERE agent_uid = ? AND conversation_uid = ?), 0), 1)
                ON CONFLICT(agent_uid, conversation_uid)
                DO UPDATE SET active_for_notifications = 1
                """,
                (uid, conversation_uid, uid, conversation_uid),
            )

    def request_relation(self, caller_uid: str, payload: dict[str, Any]) -> str:
        target_data = payload.get("target") or {}
        target_type = target_data.get("type")
        target_id = target_data.get("id", "")
        message = payload.get("message")
        with self.tx() as conn:
            target = self._resolve_target(conn, target_type, target_id)
            if target.type == "agent":
                if target.uid == caller_uid:
                    raise OpenChatError("invalid_target")
                if self._is_direct_related(conn, caller_uid, target.uid):
                    raise OpenChatError("already_related")
            else:
                if self._is_group_related(conn, caller_uid, target.uid):
                    raise OpenChatError("already_related")
            existing = conn.execute(
                """
                SELECT 1 FROM relation_requests
                WHERE source_agent_uid = ? AND target_type = ? AND target_uid = ? AND status = 'pending'
                """,
                (caller_uid, target.type, target.uid),
            ).fetchone()
            if existing:
                raise OpenChatError("already_requested")
            conn.execute(
                """
                INSERT INTO relation_requests
                (request_uid, source_agent_uid, target_type, target_uid, message, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (new_id("req"), caller_uid, target.type, target.uid, message, now_iso()),
            )
        return "success"

    def read_relation_requests(self, caller_uid: str) -> str:
        with self.tx() as conn:
            rows = conn.execute(
                """
                SELECT rr.*, sa.handle AS source_handle, sa.display_name AS source_display_name,
                       ta.handle AS target_agent_handle, ta.display_name AS target_agent_display_name,
                       g.handle AS group_handle, g.display_name AS group_display_name
                FROM relation_requests rr
                JOIN agents sa ON sa.agent_uid = rr.source_agent_uid
                LEFT JOIN agents ta ON ta.agent_uid = rr.target_uid AND rr.target_type = 'agent'
                LEFT JOIN groups g ON g.group_uid = rr.target_uid AND rr.target_type = 'group'
                WHERE rr.status = 'pending'
                  AND (
                    (rr.target_type = 'agent' AND rr.target_uid = ?)
                    OR
                    (rr.target_type = 'group' AND rr.target_uid IN (
                        SELECT group_uid FROM group_memberships
                        WHERE agent_uid = ? AND role = 'admin' AND status = 'active'
                    ))
                  )
                ORDER BY rr.created_at ASC
                """,
                (caller_uid, caller_uid),
            ).fetchall()
        if not rows:
            return "empty"
        lines = ["requests:"]
        for row in rows:
            source = canonical_agent_label(row["source_display_name"], row["source_handle"])
            if row["target_type"] == "agent":
                target = canonical_agent_label(row["target_agent_display_name"], row["target_agent_handle"])
            else:
                target = canonical_group_label(row["group_display_name"], row["group_handle"])
            suffix = f": {row['message']}" if row["message"] else ""
            lines.append(f"{source} -> {target}{suffix}")
        return "\n".join(lines)

    def respond_relation_request(self, caller_uid: str, payload: dict[str, Any]) -> str:
        source_data = payload.get("source") or {}
        target_data = payload.get("target") or {}
        action = payload.get("action")
        if action not in {"accept", "reject"}:
            raise OpenChatError("invalid_target")
        with self.tx() as conn:
            source = self._resolve_target(conn, "agent", source_data.get("id", ""))
            target = self._resolve_target(conn, target_data.get("type"), target_data.get("id", ""))
            request = conn.execute(
                """
                SELECT * FROM relation_requests
                WHERE source_agent_uid = ? AND target_type = ? AND target_uid = ? AND status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (source.uid, target.type, target.uid),
            ).fetchone()
            if not request:
                raise OpenChatError("request_not_found")
            if target.type == "agent":
                if target.uid != caller_uid:
                    raise OpenChatError("permission_denied")
            else:
                if not self._is_group_admin(conn, caller_uid, target.uid):
                    raise OpenChatError("permission_denied")
            handled_at = now_iso()
            conn.execute(
                "UPDATE relation_requests SET status = ?, handled_at = ? WHERE request_uid = ?",
                ("accepted" if action == "accept" else "rejected", handled_at, request["request_uid"]),
            )
            if action == "accept":
                if target.type == "agent":
                    a_uid, b_uid, _ = self._direct_key(source.uid, target.uid)
                    conn.execute(
                        """
                        INSERT INTO direct_relations (agent_a_uid, agent_b_uid, status, created_at, removed_at)
                        VALUES (?, ?, 'active', ?, NULL)
                        ON CONFLICT(agent_a_uid, agent_b_uid)
                        DO UPDATE SET status = 'active', removed_at = NULL
                        """,
                        (a_uid, b_uid, handled_at),
                    )
                    conversation = self._ensure_direct_conversation(conn, source.uid, target.uid)
                    for uid in (source.uid, target.uid):
                        conn.execute(
                            """
                            INSERT INTO conversation_inbox_state (agent_uid, conversation_uid, last_read_seq, active_for_notifications)
                            VALUES (?, ?, 0, 1)
                            ON CONFLICT(agent_uid, conversation_uid)
                            DO UPDATE SET active_for_notifications = 1
                            """,
                            (uid, conversation["conversation_uid"]),
                        )
                else:
                    conversation = self._ensure_group_conversation(conn, target.uid)
                    conn.execute(
                        """
                        INSERT INTO group_memberships (group_uid, agent_uid, role, status, joined_at, left_at, left_seq)
                        VALUES (?, ?, 'member', 'active', ?, NULL, NULL)
                        ON CONFLICT(group_uid, agent_uid)
                        DO UPDATE SET status = 'active', left_at = NULL, left_seq = NULL
                        """,
                        (target.uid, source.uid, handled_at),
                    )
                    current_max_seq = self._conversation_max_seq(conn, conversation["conversation_uid"])
                    conn.execute(
                        """
                        INSERT INTO conversation_participants (conversation_uid, agent_uid, joined_seq, left_seq)
                        VALUES (?, ?, ?, NULL)
                        ON CONFLICT(conversation_uid, agent_uid)
                        DO UPDATE SET joined_seq = excluded.joined_seq, left_seq = NULL
                        """,
                        (conversation["conversation_uid"], source.uid, current_max_seq),
                    )
                    conn.execute(
                        """
                        INSERT INTO conversation_visibility_windows (conversation_uid, agent_uid, start_seq, end_seq)
                        VALUES (?, ?, ?, NULL)
                        """,
                        (conversation["conversation_uid"], source.uid, current_max_seq + 1),
                    )
                    conn.execute(
                        """
                        INSERT INTO conversation_inbox_state (agent_uid, conversation_uid, last_read_seq, active_for_notifications)
                        VALUES (?, ?, ?, 1)
                        ON CONFLICT(agent_uid, conversation_uid)
                        DO UPDATE SET last_read_seq = excluded.last_read_seq, active_for_notifications = 1
                        """,
                        (source.uid, conversation["conversation_uid"], current_max_seq),
                    )
        return "success"

    def remove_relation(self, caller_uid: str, payload: dict[str, Any]) -> str:
        target_data = payload.get("target") or {}
        with self.tx() as conn:
            target = self._resolve_target(conn, target_data.get("type"), target_data.get("id", ""))
            if target.type == "agent":
                a_uid, b_uid, direct_key = self._direct_key(caller_uid, target.uid)
                relation = conn.execute(
                    """
                    SELECT * FROM direct_relations
                    WHERE agent_a_uid = ? AND agent_b_uid = ?
                    """,
                    (a_uid, b_uid),
                ).fetchone()
                if not relation or relation["status"] != "active":
                    raise OpenChatError("not_related")
                conn.execute(
                    """
                    UPDATE direct_relations
                    SET status = 'removed', removed_at = ?
                    WHERE agent_a_uid = ? AND agent_b_uid = ?
                    """,
                    (now_iso(), a_uid, b_uid),
                )
                conversation = conn.execute(
                    "SELECT conversation_uid FROM conversations WHERE direct_key = ?",
                    (direct_key,),
                ).fetchone()
                if conversation:
                    conn.execute(
                        """
                        UPDATE conversation_inbox_state
                        SET active_for_notifications = 0
                        WHERE agent_uid = ? AND conversation_uid = ?
                        """,
                        (caller_uid, conversation["conversation_uid"]),
                    )
            else:
                membership = conn.execute(
                    """
                    SELECT * FROM group_memberships
                    WHERE group_uid = ? AND agent_uid = ?
                    """,
                    (target.uid, caller_uid),
                ).fetchone()
                if not membership or membership["status"] != "active":
                    raise OpenChatError("not_related")
                conversation = self._ensure_group_conversation(conn, target.uid)
                left_seq = self._conversation_max_seq(conn, conversation["conversation_uid"])
                timestamp = now_iso()
                conn.execute(
                    """
                    UPDATE group_memberships
                    SET status = 'left', left_at = ?, left_seq = ?
                    WHERE group_uid = ? AND agent_uid = ?
                    """,
                    (timestamp, left_seq, target.uid, caller_uid),
                )
                conn.execute(
                    """
                    INSERT INTO conversation_participants (conversation_uid, agent_uid, joined_seq, left_seq)
                    VALUES (?, ?, 0, ?)
                    ON CONFLICT(conversation_uid, agent_uid)
                    DO UPDATE SET left_seq = excluded.left_seq
                    """,
                    (conversation["conversation_uid"], caller_uid, left_seq),
                )
                conn.execute(
                    """
                    UPDATE conversation_visibility_windows
                    SET end_seq = ?
                    WHERE conversation_uid = ? AND agent_uid = ? AND end_seq IS NULL
                    """,
                    (left_seq, conversation["conversation_uid"], caller_uid),
                )
                conn.execute(
                    """
                    UPDATE conversation_inbox_state
                    SET active_for_notifications = 0
                    WHERE agent_uid = ? AND conversation_uid = ?
                    """,
                    (caller_uid, conversation["conversation_uid"]),
                )
        return "success"

    def send_messages(self, caller_uid: str, payload: dict[str, Any]) -> tuple[str, list[str]]:
        items = payload.get("items")
        if not isinstance(items, list) or not items:
            raise OpenChatError("invalid_target")
        failures: list[str] = []
        with self.tx() as conn:
            for item in items:
                target_data = item.get("target") or {}
                text = str(item.get("text", ""))
                if not text.strip():
                    raw_id = target_data.get("id", "")
                    failures.append(f"{target_data.get('type', 'agent')} {raw_id}: empty_text")
                    continue
                if len(text) > 4000:
                    raw_id = target_data.get("id", "")
                    failures.append(f"{target_data.get('type', 'agent')} {raw_id}: text_too_long")
                    continue
                try:
                    target = self._resolve_target(conn, target_data.get("type"), target_data.get("id", ""))
                    recipient_uids: list[str]
                    if target.type == "agent":
                        if not self._is_direct_related(conn, caller_uid, target.uid):
                            raise OpenChatError("not_related")
                        conversation = self._ensure_direct_conversation(conn, caller_uid, target.uid)
                        recipient_uids = [target.uid]
                    else:
                        if not self._is_group_related(conn, caller_uid, target.uid):
                            raise OpenChatError("not_related")
                        conversation = self._ensure_group_conversation(conn, target.uid)
                        recipient_uids = [
                            row["agent_uid"]
                            for row in conn.execute(
                                """
                                SELECT agent_uid FROM group_memberships
                                WHERE group_uid = ? AND status = 'active' AND agent_uid != ?
                                """,
                                (target.uid, caller_uid),
                            ).fetchall()
                        ]
                    seq = self._conversation_max_seq(conn, conversation["conversation_uid"]) + 1
                    conn.execute(
                        """
                        INSERT INTO messages
                        (message_uid, conversation_uid, seq, sender_agent_uid, text, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (new_id("msg"), conversation["conversation_uid"], seq, caller_uid, text, now_iso()),
                    )
                    self._mark_inbox_activity(
                        conn,
                        conversation["conversation_uid"],
                        caller_uid,
                        seq,
                        recipient_uids,
                    )
                except OpenChatError as exc:
                    raw_id = target_data.get("id", "")
                    failures.append(f"{target_data.get('type', 'agent')} {raw_id}: {exc.code}")
        return ("success" if not failures else "failure"), failures

    def read_notifications(self, caller_uid: str) -> str:
        with self.tx() as conn:
            direct_rows = conn.execute(
                """
                SELECT c.conversation_uid, a.handle, a.display_name,
                       (SELECT COALESCE(MAX(seq), 0) FROM messages WHERE conversation_uid = c.conversation_uid) AS max_seq,
                       cis.last_read_seq
                FROM conversations c
                JOIN conversation_inbox_state cis ON cis.conversation_uid = c.conversation_uid AND cis.agent_uid = ?
                JOIN conversation_participants cp ON cp.conversation_uid = c.conversation_uid AND cp.agent_uid != ?
                JOIN agents a ON a.agent_uid = cp.agent_uid
                JOIN direct_relations dr ON dr.agent_a_uid = CASE WHEN ? < a.agent_uid THEN ? ELSE a.agent_uid END
                                         AND dr.agent_b_uid = CASE WHEN ? < a.agent_uid THEN a.agent_uid ELSE ? END
                WHERE c.type = 'direct'
                  AND cis.active_for_notifications = 1
                  AND dr.status = 'active'
                """,
                (caller_uid, caller_uid, caller_uid, caller_uid, caller_uid, caller_uid),
            ).fetchall()
            group_rows = conn.execute(
                """
                SELECT c.conversation_uid, g.handle, g.display_name,
                       (SELECT COALESCE(MAX(seq), 0) FROM messages WHERE conversation_uid = c.conversation_uid) AS max_seq,
                       cis.last_read_seq
                FROM conversations c
                JOIN groups g ON g.group_uid = c.group_uid
                JOIN conversation_inbox_state cis ON cis.conversation_uid = c.conversation_uid AND cis.agent_uid = ?
                JOIN group_memberships gm ON gm.group_uid = g.group_uid AND gm.agent_uid = ? AND gm.status = 'active'
                WHERE c.type = 'group'
                  AND cis.active_for_notifications = 1
                """,
                (caller_uid, caller_uid),
            ).fetchall()
            lines: list[str] = []
            for row in direct_rows:
                unread = int(row["max_seq"]) - int(row["last_read_seq"])
                if unread > 0:
                    lines.append(f"{canonical_agent_label(row['display_name'], row['handle'])}: {unread}")
            for row in group_rows:
                unread_floor = max(
                    int(row["last_read_seq"]),
                    self._current_group_window_floor_seq(conn, row["conversation_uid"], caller_uid),
                )
                unread = int(row["max_seq"]) - unread_floor
                if unread > 0:
                    lines.append(f"{canonical_group_label(row['display_name'], row['handle'])}: {unread}")
        if not lines:
            return "empty"
        return "unread:\n" + "\n".join(lines)

    def _read_visible_messages(
        self,
        conn: sqlite3.Connection,
        conversation_uid: str,
        visibility_clauses: list[str],
        visibility_params: list[Any],
        before_time: str | None,
        count: int,
    ) -> list[sqlite3.Row]:
        clauses = ["m.conversation_uid = ?"]
        params: list[Any] = [conversation_uid]
        clauses.extend(visibility_clauses)
        params.extend(visibility_params)
        if before_time:
            clauses.append("m.created_at < ?")
            params.append(before_time)
        rows = conn.execute(
            f"""
            SELECT m.*, a.handle AS sender_handle, a.display_name AS sender_display_name
            FROM messages m
            JOIN agents a ON a.agent_uid = m.sender_agent_uid
            WHERE {' AND '.join(clauses)}
            ORDER BY m.created_at DESC, m.seq DESC
            LIMIT ?
            """,
            (*params, count),
        ).fetchall()
        return list(reversed(rows))

    def read_messages(self, caller_uid: str, payload: dict[str, Any]) -> str:
        target_data = payload.get("target") or {}
        count = max(1, min(int(payload.get("count", 20) or 20), 100))
        before_time = payload.get("before_time")
        with self.tx() as conn:
            target = self._resolve_target(conn, target_data.get("type"), target_data.get("id", ""))
            conversation_uid: str
            visibility_clauses: list[str] = []
            visibility_params: list[Any] = []
            if target.type == "agent":
                if not self._can_read_direct(conn, caller_uid, target.uid):
                    raise OpenChatError("not_related")
                conversation = self._ensure_direct_conversation(conn, caller_uid, target.uid)
                conversation_uid = conversation["conversation_uid"]
            else:
                if not self._can_read_group(conn, caller_uid, target.uid):
                    raise OpenChatError("permission_denied")
                conversation = self._ensure_group_conversation(conn, target.uid)
                conversation_uid = conversation["conversation_uid"]
                visibility_clauses, visibility_params = self._group_visibility_filters(
                    conn,
                    conversation_uid,
                    caller_uid,
                )
            inbox = conn.execute(
                """
                SELECT last_read_seq FROM conversation_inbox_state
                WHERE agent_uid = ? AND conversation_uid = ?
                """,
                (caller_uid, conversation_uid),
            ).fetchone()
            if before_time:
                rows = self._read_visible_messages(
                    conn,
                    conversation_uid,
                    visibility_clauses,
                    visibility_params,
                    before_time,
                    count,
                )
            else:
                last_read_seq = int(inbox["last_read_seq"]) if inbox else 0
                max_seq = self._conversation_max_seq(conn, conversation_uid)
                visible_max_seq = max_seq
                if target.type == "group":
                    visible_max_seq = 0
                    for start_seq, end_seq in self._visible_group_windows(conn, conversation_uid, caller_uid):
                        window_max = end_seq if end_seq is not None else max_seq
                        visible_max_seq = max(visible_max_seq, window_max)
                if visible_max_seq > last_read_seq:
                    clauses = ["m.conversation_uid = ?", "m.seq >= ?"]
                    params: list[Any] = [conversation_uid, last_read_seq + 1]
                    clauses.extend(visibility_clauses)
                    params.extend(visibility_params)
                    rows = conn.execute(
                        f"""
                        SELECT m.*, a.handle AS sender_handle, a.display_name AS sender_display_name
                        FROM messages m
                        JOIN agents a ON a.agent_uid = m.sender_agent_uid
                        WHERE {' AND '.join(clauses)}
                        ORDER BY m.seq ASC
                        LIMIT ?
                        """,
                        (*params, count),
                    ).fetchall()
                    if rows:
                        last_seq = int(rows[-1]["seq"])
                        conn.execute(
                            """
                            INSERT INTO conversation_inbox_state (agent_uid, conversation_uid, last_read_seq, active_for_notifications)
                            VALUES (?, ?, ?, 1)
                            ON CONFLICT(agent_uid, conversation_uid)
                            DO UPDATE SET last_read_seq = excluded.last_read_seq
                            """,
                            (caller_uid, conversation_uid, last_seq),
                        )
                else:
                    rows = self._read_visible_messages(
                        conn,
                        conversation_uid,
                        visibility_clauses,
                        visibility_params,
                        None,
                        count,
                    )
        if not rows:
            return "empty"
        if target.type == "agent":
            header = f"{canonical_agent_label(target.display_name, target.handle)}:"
            body = [
                f"{row['created_at'].replace('T', ' ')[:16]} {row['text']}"
                for row in rows
            ]
        else:
            header = f"{canonical_group_label(target.display_name, target.handle)}:"
            body = [
                f"{row['created_at'].replace('T', ' ')[:16]} {row['sender_display_name']}({row['sender_handle']}): {row['text']}"
                for row in rows
            ]
        return header + "\n" + "\n".join(body)

    def search_messages(self, caller_uid: str, payload: dict[str, Any]) -> str:
        query = str(payload.get("query", "")).strip()
        if not query:
            return "empty"
        target_payload = payload.get("target")
        count = max(1, min(int(payload.get("count", 10) or 10), 100))
        before_time = payload.get("before_time")
        with self.tx() as conn:
            conversation_filters: list[tuple[str, str, str, list[str], list[Any]]] = []
            if target_payload:
                target = self._resolve_target(conn, target_payload.get("type"), target_payload.get("id", ""))
                if target.type == "agent":
                    if not self._can_read_direct(conn, caller_uid, target.uid):
                        raise OpenChatError("not_related")
                    conversation = self._ensure_direct_conversation(conn, caller_uid, target.uid)
                    conversation_filters.append((conversation["conversation_uid"], target.type, target.label, [], []))
                else:
                    if not self._can_read_group(conn, caller_uid, target.uid):
                        raise OpenChatError("permission_denied")
                    conversation = self._ensure_group_conversation(conn, target.uid)
                    visibility_clauses, visibility_params = self._group_visibility_filters(
                        conn,
                        conversation["conversation_uid"],
                        caller_uid,
                    )
                    conversation_filters.append(
                        (
                            conversation["conversation_uid"],
                            target.type,
                            target.label,
                            visibility_clauses,
                            visibility_params,
                        )
                    )
            else:
                direct_rows = conn.execute(
                    """
                    SELECT c.conversation_uid, a.handle, a.display_name
                    FROM conversations c
                    JOIN conversation_participants cp ON cp.conversation_uid = c.conversation_uid AND cp.agent_uid != ?
                    JOIN agents a ON a.agent_uid = cp.agent_uid
                    JOIN conversation_participants selfp ON selfp.conversation_uid = c.conversation_uid AND selfp.agent_uid = ?
                    WHERE c.type = 'direct'
                    """,
                    (caller_uid, caller_uid),
                ).fetchall()
                for row in direct_rows:
                    conversation_filters.append(
                        (row["conversation_uid"], "agent", canonical_agent_label(row["display_name"], row["handle"]), [], [])
                    )
                group_rows = conn.execute(
                    """
                    SELECT c.conversation_uid, g.handle, g.display_name
                    FROM conversations c
                    JOIN groups g ON g.group_uid = c.group_uid
                    JOIN group_memberships gm ON gm.group_uid = g.group_uid AND gm.agent_uid = ?
                    WHERE c.type = 'group'
                    """,
                    (caller_uid,),
                ).fetchall()
                for row in group_rows:
                    visibility_clauses, visibility_params = self._group_visibility_filters(
                        conn,
                        row["conversation_uid"],
                        caller_uid,
                    )
                    conversation_filters.append(
                        (
                            row["conversation_uid"],
                            "group",
                            canonical_group_label(row["display_name"], row["handle"]),
                            visibility_clauses,
                            visibility_params,
                        )
                    )
            grouped: dict[str, list[str]] = {}
            global_results: list[dict[str, Any]] = []
            for conversation_uid, target_type, label, visibility_clauses, visibility_params in conversation_filters:
                clauses = ["m.conversation_uid = ?", "m.text LIKE ?"]
                params: list[Any] = [conversation_uid, f"%{query}%"]
                clauses.extend(visibility_clauses)
                params.extend(visibility_params)
                if before_time:
                    clauses.append("m.created_at < ?")
                    params.append(before_time)
                rows = conn.execute(
                    f"""
                    SELECT m.*, a.handle AS sender_handle, a.display_name AS sender_display_name
                    FROM messages m
                    JOIN agents a ON a.agent_uid = m.sender_agent_uid
                    WHERE {' AND '.join(clauses)}
                    ORDER BY m.created_at DESC, m.seq DESC
                    LIMIT ?
                    """,
                    (*params, count),
                ).fetchall()
                if not rows:
                    continue
                if target_payload:
                    lines: list[str] = []
                    for row in rows:
                        if target_type == "group":
                            lines.append(
                                f"{row['created_at'].replace('T', ' ')[:16]} {row['sender_display_name']}({row['sender_handle']}): {row['text']}"
                            )
                        else:
                            lines.append(f"{row['created_at'].replace('T', ' ')[:16]} {row['text']}")
                    grouped[label] = lines
                    continue
                for row in rows:
                    global_results.append(
                        {
                            "created_at": row["created_at"],
                            "seq": int(row["seq"]),
                            "target_type": target_type,
                            "label": label,
                            "sender_display_name": row["sender_display_name"],
                            "sender_handle": row["sender_handle"],
                            "text": row["text"],
                        }
                    )
        if target_payload:
            if not grouped:
                return "empty"
            header = f'search results for "{query}" in {next(iter(grouped.keys()))}:'
            sections = [header]
            for lines in grouped.values():
                sections.extend(lines)
            return "\n".join(sections).strip()
        if not global_results:
            return "empty"
        global_results.sort(key=lambda item: (item["created_at"], item["seq"]), reverse=True)
        lines = [f'search results for "{query}":']
        for item in global_results[:count]:
            timestamp = item["created_at"].replace("T", " ")[:16]
            if item["target_type"] == "group":
                lines.append(
                    f"{timestamp} {item['label']} {item['sender_display_name']}({item['sender_handle']}): {item['text']}"
                )
            else:
                lines.append(f"{timestamp} {item['label']}: {item['text']}")
        return "\n".join(lines)
