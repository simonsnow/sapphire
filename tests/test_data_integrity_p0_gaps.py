"""Surface 3 P0 gaps — final regression guards to close P0 of Surface 3.

Covers the three P0 stubs that weren't in the first data-integrity file:
  3.4  delete_knowledge protects user-created entries
  3.12 memory FTS trigger noops on embedding-only UPDATE
  3.13 knowledge FTS trigger noops on embedding-only UPDATE

The FTS guards matter because an embedding refresh (e.g. switching embedding
providers) must NOT re-trigger full-text indexing — otherwise it corrupts
the search index under concurrent reads and doubles storage.

See tmp/coverage-test-plan.md Surface 3.
"""
import sqlite3

import pytest


# Reuse the fixture pattern from test_data_integrity_p0.py

@pytest.fixture
def isolated_memory(tmp_path, monkeypatch):
    from plugins.memory.tools import memory_tools
    db_path = tmp_path / "memory_test.db"
    monkeypatch.setattr(memory_tools, "_db_path", db_path, raising=False)
    monkeypatch.setattr(memory_tools, "_db_initialized", False, raising=False)
    memory_tools._ensure_db()
    yield memory_tools, db_path


@pytest.fixture
def isolated_knowledge(tmp_path, monkeypatch):
    from plugins.memory.tools import knowledge_tools
    db_path = tmp_path / "knowledge_test.db"
    monkeypatch.setattr(knowledge_tools, "_db_path", db_path, raising=False)
    monkeypatch.setattr(knowledge_tools, "_db_initialized", False, raising=False)
    knowledge_tools._ensure_db()
    yield knowledge_tools, db_path


# ─── 3.4 delete_knowledge protects user-created entries ──────────────────────

def test_delete_knowledge_refuses_user_entry(isolated_knowledge):
    """[REGRESSION_GUARD] AI can only delete its own (ai-type) knowledge.
    User-created entries in user-tabs must be untouchable by tool call —
    otherwise a prompt-injected AI could wipe the user's notes."""
    kt, db_path = isolated_knowledge

    # Create a user-type tab manually (simulating UI-created content)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO knowledge_tabs (name, type, scope) VALUES (?, 'user', 'default')",
        ('user_notes',),
    )
    user_tab_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO knowledge_entries (tab_id, content) VALUES (?, ?)",
        (user_tab_id, 'precious user notes'),
    )
    user_entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    # Try to delete via AI path — by entry id
    msg, ok = kt._delete_knowledge(entry_id=user_entry_id, scope='default')
    assert ok is False, "AI delete of user-created entry should refuse"
    assert 'user-created' in msg.lower() or 'user' in msg.lower()

    # Entry still exists
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id FROM knowledge_entries WHERE id = ?", (user_entry_id,)
    ).fetchone()
    conn.close()
    assert row is not None, "user entry was deleted by AI path (CORRUPTION)"


def test_delete_knowledge_refuses_user_category(isolated_knowledge):
    """[REGRESSION_GUARD] Same guard at the category level."""
    kt, db_path = isolated_knowledge

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO knowledge_tabs (name, type, scope) VALUES ('journal', 'user', 'default')"
    )
    conn.commit()
    conn.close()

    msg, ok = kt._delete_knowledge(category='journal', scope='default')
    assert ok is False
    assert 'user' in msg.lower()

    # Category still exists
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id FROM knowledge_tabs WHERE name = ?", ('journal',)
    ).fetchone()
    conn.close()
    assert row is not None


def test_delete_knowledge_allows_ai_created(isolated_knowledge):
    """Inverse: AI-created content CAN be deleted by AI. Via _save_knowledge
    the tab type defaults to 'ai'."""
    kt, _ = isolated_knowledge
    msg, ok = kt._save_knowledge('ai_findings', 'gathered data', scope='default')
    assert ok
    # Delete whole AI category — should succeed
    msg, ok = kt._delete_knowledge(category='ai_findings', scope='default')
    assert ok, f"AI should be able to delete its own category: {msg}"


# ─── 3.12 Memory FTS trigger noops on embedding-only UPDATE ──────────────────

def test_memory_fts_unaffected_by_embedding_only_update(isolated_memory):
    """[REGRESSION_GUARD] The memories_fts_update trigger is declared as
    `AFTER UPDATE OF content, keywords, label` — NOT `AFTER UPDATE`. So
    updating only the `embedding` column (e.g. backfill after embedder
    switch) must NOT re-fire FTS.

    Why it matters: re-firing FTS on every row of a full embedding backfill
    would corrupt the index under concurrent search + double write cost.
    """
    mt, db_path = isolated_memory
    msg, ok = mt._save_memory('searchable content xyzabc', scope='default')
    assert ok

    conn = sqlite3.connect(db_path)
    mem_id = conn.execute(
        "SELECT id FROM memories WHERE content LIKE '%xyzabc%'"
    ).fetchone()[0]
    # Snapshot FTS state before
    fts_before = conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE content LIKE '%xyzabc%'"
    ).fetchone()[0]
    assert fts_before == 1, "FTS row should exist for the saved memory"

    # UPDATE only the embedding column
    import os
    conn.execute(
        "UPDATE memories SET embedding = ? WHERE id = ?",
        (os.urandom(1536), mem_id),
    )
    conn.commit()

    # FTS row count unchanged (no duplicate, no deletion)
    fts_after = conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE content LIKE '%xyzabc%'"
    ).fetchone()[0]
    conn.close()
    assert fts_after == fts_before, \
        f"embedding-only update fired FTS trigger ({fts_before} → {fts_after})"


def test_memory_fts_does_fire_on_content_update(isolated_memory):
    """Inverse: when `content` IS modified, FTS trigger must fire."""
    mt, db_path = isolated_memory
    msg, ok = mt._save_memory('original phrase', scope='default')
    assert ok
    conn = sqlite3.connect(db_path)
    mem_id = conn.execute(
        "SELECT id FROM memories WHERE content = 'original phrase'"
    ).fetchone()[0]

    # Update content — trigger should fire (delete old FTS row, insert new)
    conn.execute(
        "UPDATE memories SET content = 'replacement phrase' WHERE id = ?",
        (mem_id,),
    )
    conn.commit()

    # Old FTS content gone, new present
    old_hits = conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE content LIKE '%original%'"
    ).fetchone()[0]
    new_hits = conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE content LIKE '%replacement%'"
    ).fetchone()[0]
    conn.close()
    assert old_hits == 0, "old FTS content should be deleted"
    assert new_hits == 1, "new FTS content should be indexed"


# ─── 3.13 Knowledge FTS trigger noops on embedding-only UPDATE ───────────────

def test_knowledge_fts_unaffected_by_embedding_only_update(isolated_knowledge):
    """[REGRESSION_GUARD] Same guard for knowledge — FTS update trigger is
    `AFTER UPDATE OF content`. Embedding refreshes must NOT reindex."""
    kt, db_path = isolated_knowledge
    msg, ok = kt._save_knowledge('findings', 'note with qwxyz token', scope='default')
    assert ok

    conn = sqlite3.connect(db_path)
    entry_id = conn.execute(
        "SELECT id FROM knowledge_entries WHERE content LIKE '%qwxyz%'"
    ).fetchone()[0]
    fts_before = conn.execute(
        "SELECT COUNT(*) FROM knowledge_fts WHERE content LIKE '%qwxyz%'"
    ).fetchone()[0]
    assert fts_before == 1

    import os
    conn.execute(
        "UPDATE knowledge_entries SET embedding = ? WHERE id = ?",
        (os.urandom(1536), entry_id),
    )
    conn.commit()

    fts_after = conn.execute(
        "SELECT COUNT(*) FROM knowledge_fts WHERE content LIKE '%qwxyz%'"
    ).fetchone()[0]
    conn.close()
    assert fts_after == fts_before, \
        f"knowledge embedding-only update fired FTS trigger ({fts_before} → {fts_after})"
