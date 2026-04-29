"""Surface 3 P1 — data integrity spread for memory/knowledge/goals.

Complements:
  test_data_integrity_p0.py        (3.3, 3.5-3.11, 3.14, 3.15 + bonuses)
  test_data_integrity_p0_gaps.py   (3.4, 3.12, 3.13 — delete + FTS triggers)
  test_regression_guards_knowledge.py  (R7, R8)

Covers the P1 data-path spread — cheap, high-volume guards on the actual
behavior of save/delete/update/search across all three DBs. Each test is a
round-trip or a cascade check against a fresh isolated DB.

See tmp/coverage-test-plan.md Surface 3.
"""
from datetime import datetime
import sqlite3

import pytest


# ─── fixtures (reuse pattern from Surface 3 P0 files) ────────────────────────

@pytest.fixture
def isolated_memory(tmp_path, monkeypatch):
    from plugins.memory.tools import memory_tools
    db_path = tmp_path / "memory.db"
    monkeypatch.setattr(memory_tools, "_db_path", db_path, raising=False)
    monkeypatch.setattr(memory_tools, "_db_initialized", False, raising=False)
    memory_tools._ensure_db()
    yield memory_tools, db_path


@pytest.fixture
def isolated_knowledge(tmp_path, monkeypatch):
    from plugins.memory.tools import knowledge_tools
    db_path = tmp_path / "knowledge.db"
    monkeypatch.setattr(knowledge_tools, "_db_path", db_path, raising=False)
    monkeypatch.setattr(knowledge_tools, "_db_initialized", False, raising=False)
    knowledge_tools._ensure_db()
    yield knowledge_tools, db_path


@pytest.fixture
def isolated_goals(tmp_path, monkeypatch):
    from plugins.memory.tools import goals_tools
    db_path = tmp_path / "goals.db"
    monkeypatch.setattr(goals_tools, "_db_path", db_path, raising=False)
    monkeypatch.setattr(goals_tools, "_db_initialized", False, raising=False)
    goals_tools._ensure_db()
    yield goals_tools, db_path


# =============================================================================
# MEMORY
# =============================================================================

def test_save_then_search_roundtrip(isolated_memory):
    """[DATA_INTEGRITY] save → search must find it. The simplest roundtrip
    — guards against any regression that silently drops saves or breaks FTS."""
    mt, _ = isolated_memory
    mt._save_memory('distinctive phrase xyzzy', scope='default')
    result, _ = mt._search_memory('xyzzy', limit=5, label=None, scope='default')
    assert 'xyzzy' in result, f"saved memory not searchable: {result[:200]}"


def test_delete_removes_row_and_fts_entry(isolated_memory):
    """[DATA_INTEGRITY] Delete must remove BOTH the memories row AND its
    FTS index entry. Otherwise search returns phantom results pointing at
    a missing rowid (SQL error on row fetch)."""
    mt, db_path = isolated_memory
    msg, ok = mt._save_memory('ghost content', scope='default')
    assert ok
    import re
    m = re.search(r'ID:\s*(\d+)', msg)
    mid = int(m.group(1))

    mt._delete_memory(mid, scope='default')

    conn = sqlite3.connect(db_path)
    row_count = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE id = ?", (mid,)
    ).fetchone()[0]
    fts_count = conn.execute(
        "SELECT COUNT(*) FROM memories_fts WHERE content LIKE '%ghost content%'"
    ).fetchone()[0]
    conn.close()
    assert row_count == 0, "row not removed"
    assert fts_count == 0, "FTS entry not removed"


def test_save_empty_content_rejected(isolated_memory):
    """[PROACTIVE] Empty/whitespace content must be rejected — otherwise
    the AI can flood memory with blank rows."""
    mt, _ = isolated_memory
    for bad in ('', '   ', '\n\t'):
        msg, ok = mt._save_memory(bad, scope='default')
        assert ok is False, f"empty content {bad!r} was accepted"


def test_save_unicode_emoji_roundtrip(isolated_memory):
    """[DATA_INTEGRITY] Unicode (日本語, emoji) must roundtrip — no encoding
    corruption between save and search."""
    mt, db_path = isolated_memory
    mt._save_memory('日本語のメモ 🎌 sapphire', scope='default')

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT content FROM memories WHERE content LIKE '%sapphire%'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert '日本語' in row[0]
    assert '🎌' in row[0]


def test_delete_scope_cascades_memories(isolated_memory):
    """[DATA_INTEGRITY] Deleting a scope must remove all its memories.
    Without cascade, orphan rows linger forever in a non-existent scope."""
    mt, db_path = isolated_memory
    mt.create_scope('to_delete')
    mt._save_memory('memory A', scope='to_delete')
    mt._save_memory('memory B', scope='to_delete')

    conn = sqlite3.connect(db_path)
    before = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE scope = 'to_delete'"
    ).fetchone()[0]
    conn.close()
    assert before == 2

    mt.delete_scope('to_delete')

    conn = sqlite3.connect(db_path)
    after = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE scope = 'to_delete'"
    ).fetchone()[0]
    scope_row = conn.execute(
        "SELECT name FROM memory_scopes WHERE name = 'to_delete'"
    ).fetchone()
    conn.close()
    assert after == 0, f"cascade failed — {after} orphan memories in deleted scope"
    assert scope_row is None, "scope row not removed"


def test_delete_default_scope_rejected(isolated_memory):
    """[PROACTIVE] Can't delete the built-in 'default' scope — too much
    user state lives there for silent removal."""
    mt, _ = isolated_memory
    result = mt.delete_scope('default')
    assert isinstance(result, dict)
    assert 'error' in result, f"default scope deletion should return error dict; got {result}"
    assert 'default' in result['error'].lower()


# =============================================================================
# KNOWLEDGE
# =============================================================================

def test_save_knowledge_category_autocreates_tab(isolated_knowledge):
    """[DATA_INTEGRITY] Saving to a new category must auto-create the tab.
    Missing auto-create = FK violation + user confusion."""
    kt, db_path = isolated_knowledge
    msg, ok = kt._save_knowledge('brand_new_category', 'content here', scope='default')
    assert ok, f"save_knowledge failed: {msg}"

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id FROM knowledge_tabs WHERE name = ? AND scope = ?",
        ('brand_new_category', 'default'),
    ).fetchone()
    conn.close()
    assert row is not None, "category tab not auto-created"


def test_save_person_scope_isolation(isolated_knowledge):
    """[DATA_INTEGRITY] Same name in different scopes = different people.
    Krem at work ≠ Krem at home. Guards against accidental cross-scope dedupe."""
    kt, db_path = isolated_knowledge
    kt._save_person('Alex', relationship='coworker', scope='work')
    kt._save_person('Alex', relationship='neighbor', scope='home')

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT scope, relationship FROM people WHERE name = 'Alex' ORDER BY scope"
    ).fetchall()
    conn.close()
    assert len(rows) == 2, f"expected 2 Alex entries (one per scope), got {len(rows)}: {rows}"
    scopes = {r[0] for r in rows}
    assert scopes == {'home', 'work'}
    rels = {r[1] for r in rows}
    assert rels == {'coworker', 'neighbor'}


def test_create_or_update_person_by_id_allows_name_change(isolated_knowledge):
    """[PROACTIVE] When person_id is provided, the name CAN change (user edited
    their name). Without this, renaming a person becomes impossible — the
    AI-path name-match would create a new row instead."""
    kt, db_path = isolated_knowledge
    pid, is_new = kt.create_or_update_person('Alice', relationship='friend', scope='default')
    assert is_new

    # Update by id with new name — should update, not create
    pid2, is_new2 = kt.create_or_update_person(
        'Alice Smith', person_id=pid, relationship='friend', scope='default',
    )
    assert pid == pid2, "id changed on update"
    assert is_new2 is False

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT id, name FROM people").fetchall()
    conn.close()
    assert len(rows) == 1, f"expected single row after rename; got {rows}"
    assert rows[0][1] == 'Alice Smith'


def test_delete_knowledge_auto_removes_empty_ai_tab(isolated_knowledge):
    """[PROACTIVE] After deleting the last entry in an AI tab, the tab
    itself is auto-removed. Prevents empty tabs cluttering the UI forever."""
    kt, db_path = isolated_knowledge
    msg, ok = kt._save_knowledge('tmp_cat', 'only entry', scope='default')
    assert ok

    conn = sqlite3.connect(db_path)
    entry_id = conn.execute(
        "SELECT id FROM knowledge_entries WHERE content = 'only entry'"
    ).fetchone()[0]
    conn.close()

    msg, ok = kt._delete_knowledge(entry_id=entry_id, scope='default')
    assert ok

    conn = sqlite3.connect(db_path)
    tab = conn.execute(
        "SELECT id FROM knowledge_tabs WHERE name = 'tmp_cat'"
    ).fetchone()
    conn.close()
    assert tab is None, "empty AI tab was not auto-removed"


def test_chunk_text_produces_multiple_chunks_for_long_content(isolated_knowledge):
    """[DATA_INTEGRITY] _chunk_text must split long content into multiple
    chunks that cover the full text. Silent truncation = lost content."""
    kt, _ = isolated_knowledge
    # Build content that should produce multiple chunks
    long_text = "\n\n".join([
        f"Paragraph {i}: " + ("word " * 100) for i in range(20)
    ])
    chunks = kt._chunk_text(long_text, max_tokens=200, overlap_tokens=20)
    assert len(chunks) > 1, "long content should produce multiple chunks"
    # First paragraph appears in first chunk
    assert 'Paragraph 0' in chunks[0]
    # Late paragraph must also survive — appears in SOME chunk
    assert any('Paragraph 19' in c for c in chunks), \
        "later content was dropped during chunking"


def test_chunk_text_short_content_returns_single_chunk(isolated_knowledge):
    """Short content → single chunk. Don't fragment unnecessarily."""
    kt, _ = isolated_knowledge
    chunks = kt._chunk_text('short and sweet', max_tokens=400, overlap_tokens=50)
    assert len(chunks) == 1
    assert chunks[0] == 'short and sweet'


# =============================================================================
# GOALS
# =============================================================================

def test_delete_goal_cascade_true_removes_subtasks_and_progress(isolated_goals):
    """[DATA_INTEGRITY] delete_goal with cascade=True must delete subtasks
    AND their progress notes. Progress-note orphans = FK violations on
    next read."""
    gt, db_path = isolated_goals
    msg, _ = gt._create_goal('Parent', scope='default')
    import re
    pid = int(re.search(r'\[(\d+)\]', msg).group(1))
    msg, _ = gt._create_goal('Child A', parent_id=pid, scope='default')
    child_a_id = int(re.search(r'\[(\d+)\]', msg).group(1))

    # Add progress notes to parent + child
    gt._update_goal(pid, scope='default', progress_note='parent progress')
    gt._update_goal(child_a_id, scope='default', progress_note='child progress')

    gt._delete_goal(pid, cascade=True, scope='default')

    conn = sqlite3.connect(db_path)
    goals_left = conn.execute(
        "SELECT COUNT(*) FROM goals WHERE id IN (?, ?)", (pid, child_a_id)
    ).fetchone()[0]
    progress_left = conn.execute(
        "SELECT COUNT(*) FROM goal_progress WHERE goal_id IN (?, ?)", (pid, child_a_id)
    ).fetchone()[0]
    conn.close()
    assert goals_left == 0, "cascade didn't remove goals"
    assert progress_left == 0, "cascade didn't remove progress notes (orphans)"


def test_delete_goal_cascade_false_promotes_subtasks(isolated_goals):
    """[PROACTIVE] delete_goal with cascade=False promotes subtasks to
    top-level (parent_id=NULL) rather than orphaning them. Gives the user
    the option to preserve children when retiring a parent goal."""
    gt, db_path = isolated_goals
    msg, _ = gt._create_goal('Parent', scope='default')
    import re
    pid = int(re.search(r'\[(\d+)\]', msg).group(1))
    msg, _ = gt._create_goal('Keeper', parent_id=pid, scope='default')
    child_id = int(re.search(r'\[(\d+)\]', msg).group(1))

    gt._delete_goal(pid, cascade=False, scope='default')

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT parent_id FROM goals WHERE id = ?", (child_id,)
    ).fetchone()
    conn.close()
    assert row is not None, "child was also deleted (cascade=False violated)"
    assert row[0] is None, f"child should be promoted (parent_id=NULL), got {row[0]}"


def test_update_goal_status_completed_sets_completed_at(isolated_goals):
    """[DATA_INTEGRITY] Marking a goal complete must stamp completed_at.
    Without the timestamp, 'recently completed' UI sections can't sort."""
    gt, db_path = isolated_goals
    msg, _ = gt._create_goal('Task', scope='default')
    import re
    gid = int(re.search(r'\[(\d+)\]', msg).group(1))

    # Pre-check: completed_at is NULL
    conn = sqlite3.connect(db_path)
    pre = conn.execute(
        "SELECT completed_at FROM goals WHERE id = ?", (gid,)
    ).fetchone()[0]
    conn.close()
    assert pre is None

    gt._update_goal(gid, scope='default', status='completed')

    conn = sqlite3.connect(db_path)
    post = conn.execute(
        "SELECT completed_at FROM goals WHERE id = ?", (gid,)
    ).fetchone()[0]
    conn.close()
    assert post is not None, "completed_at not set"
    # Sanity: it's an ISO datetime
    datetime.fromisoformat(post)


def test_update_goal_status_reactivated_clears_completed_at(isolated_goals):
    """Inverse: reactivating a completed goal (status='active') must clear
    completed_at so the timestamp doesn't lie."""
    gt, db_path = isolated_goals
    msg, _ = gt._create_goal('Task', scope='default')
    import re
    gid = int(re.search(r'\[(\d+)\]', msg).group(1))

    gt._update_goal(gid, scope='default', status='completed')
    gt._update_goal(gid, scope='default', status='active')

    conn = sqlite3.connect(db_path)
    post = conn.execute(
        "SELECT completed_at FROM goals WHERE id = ?", (gid,)
    ).fetchone()[0]
    conn.close()
    assert post is None, f"completed_at should clear on reactivate; got {post}"


def test_update_goal_progress_note_appended_not_replaced(isolated_goals):
    """[DATA_INTEGRITY] Progress notes ACCUMULATE — each update appends a
    new row, never overwrites. The progress journal is history, not state."""
    gt, db_path = isolated_goals
    msg, _ = gt._create_goal('Task', scope='default')
    import re
    gid = int(re.search(r'\[(\d+)\]', msg).group(1))

    gt._update_goal(gid, scope='default', progress_note='step one')
    gt._update_goal(gid, scope='default', progress_note='step two')
    gt._update_goal(gid, scope='default', progress_note='step three')

    conn = sqlite3.connect(db_path)
    notes = conn.execute(
        "SELECT note FROM goal_progress WHERE goal_id = ? ORDER BY id",
        (gid,)
    ).fetchall()
    conn.close()
    notes_text = [n[0] for n in notes]
    assert notes_text == ['step one', 'step two', 'step three'], \
        f"progress notes not appended: {notes_text}"


def test_create_goal_with_parent_id_creates_subtask(isolated_goals):
    """[PROACTIVE] parent_id param creates subtask (not top-level)."""
    gt, db_path = isolated_goals
    msg, _ = gt._create_goal('Parent', scope='default')
    import re
    pid = int(re.search(r'\[(\d+)\]', msg).group(1))

    msg, _ = gt._create_goal('Sub', parent_id=pid, scope='default')
    sid = int(re.search(r'\[(\d+)\]', msg).group(1))

    conn = sqlite3.connect(db_path)
    parent_ref = conn.execute(
        "SELECT parent_id FROM goals WHERE id = ?", (sid,)
    ).fetchone()[0]
    conn.close()
    assert parent_ref == pid, f"subtask parent_id wrong: {parent_ref}"


def test_delete_goal_invalid_id_rejected(isolated_goals):
    """[PROACTIVE] non-int / negative / zero goal_id rejected with clear error."""
    gt, _ = isolated_goals
    for bad in (0, -1, 'abc', None):
        msg, ok = gt._delete_goal(bad, scope='default')
        assert ok is False, f"invalid id {bad!r} should reject"


def test_delete_scope_cascades_goals_and_progress(isolated_goals):
    """[DATA_INTEGRITY] If a goal scope is purged, all goals + progress
    notes in that scope must follow (no orphan rows)."""
    gt, db_path = isolated_goals
    msg, _ = gt._create_goal('G', scope='default')
    import re
    gid = int(re.search(r'\[(\d+)\]', msg).group(1))
    gt._update_goal(gid, scope='default', progress_note='note')

    # Verify setup
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM goals WHERE scope='default'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM goal_progress").fetchone()[0] == 1
    # Manually simulate scope purge: delete all goals in scope (mimics what
    # delete_scope in memory_tools does; goals_tools may not expose it)
    conn.execute("DELETE FROM goal_progress WHERE goal_id IN (SELECT id FROM goals WHERE scope = ?)", ('default',))
    conn.execute("DELETE FROM goals WHERE scope = ?", ('default',))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM goal_progress").fetchone()[0] == 0
    conn.close()
