"""Surface 5 P1 — AgentManager + BaseWorker behavior.

Counterpart to test_regression_guards_agents.py (R9/R10). Covers the manager-
level concurrency, lifecycle, and worker state-machine edges. The agent system
is the ralph-loop substrate; anything that goes dark here ships garbage into
production autonomously.

See tmp/coverage-test-plan.md Surface 5 for the full plan.
"""
import threading
import time

import pytest


# ─── helpers / fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def agent_manager():
    """Fresh AgentManager with max_concurrent=3. Fast-shutdown at teardown.

    Also snapshots + restores the global event_bus replay buffer so each test's
    flood of AGENT_* events doesn't leak into unrelated tests that depend on
    buffer state (test_event_bus relies on absolute counts).
    """
    from core.agents.manager import AgentManager
    from core import event_bus
    bus = event_bus.get_event_bus()
    buffer_snapshot = list(bus._replay_buffer)

    mgr = AgentManager(max_concurrent=3)
    try:
        yield mgr
    finally:
        # Unblock any still-gated workers so the thread joins are cheap
        for w in list(mgr._agents.values()):
            gate = getattr(w, '_gate', None)
            if gate is not None:
                gate.set()
        mgr.shutdown(timeout=1)
        # Restore the replay buffer
        bus._replay_buffer.clear()
        bus._replay_buffer.extend(buffer_snapshot)


@pytest.fixture
def fast_cancel_worker_cls(blocking_worker_cls):
    """blocking_worker_cls + cancel() also unblocks the gate.

    The stock blocking worker's run() sits in gate.wait(5s); cancel() flips
    status but doesn't unblock the gate, so shutdown-style tests would stall
    for 5s per agent. This subclass makes cancel() immediately release the
    thread, letting shutdown's join() return promptly.
    """
    class _FastCancel(blocking_worker_cls):
        def cancel(self):
            super().cancel()
            self._gate.set()
    return _FastCancel


def _register(mgr, worker_cls, type_key='test', names=None):
    def factory(agent_id, name, mission, chat_name='', on_complete=None, **kwargs):
        return worker_cls(
            agent_id=agent_id, name=name, mission=mission,
            chat_name=chat_name, on_complete=on_complete,
        )
    mgr.register_type(
        type_key,
        display_name='Test Agent',
        factory=factory,
        names=names or ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo'],
    )


def _wait_for(cond, timeout=2.0, step=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(step)
    return False


# ─── 5.1 Concurrent spawn respects max_concurrent ────────────────────────────

def test_concurrent_spawn_respects_max_concurrent(agent_manager, blocking_worker_cls):
    """[REGRESSION_GUARD] 10 parallel spawns with max=3 → exactly 3 succeed.

    Without proper locking around _active_count + insert, concurrent spawns
    could race past the cap. The lock in spawn() is the guarantee.
    """
    _register(agent_manager, blocking_worker_cls)
    results = []
    results_lock = threading.Lock()

    def _spawn():
        r = agent_manager.spawn('test', 'm', chat_name='c')
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=_spawn) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    succeeded = [r for r in results if 'id' in r]
    failed = [r for r in results if 'error' in r]
    assert len(succeeded) == 3, f"expected exactly 3 spawns under cap, got {len(succeeded)}"
    assert len(failed) == 7
    for f in failed:
        assert 'limit reached' in f['error'].lower()
    assert len(agent_manager._agents) == 3


# ─── 5.2 Batch fires once when all finish same tick ──────────────────────────

def test_batch_fires_once_when_all_agents_finish(
    agent_manager, blocking_worker_cls, event_bus_capture,
):
    """[REGRESSION_GUARD] 3 agents in same chat finish together → exactly one AGENT_BATCH_COMPLETE."""
    _register(agent_manager, blocking_worker_cls)
    ids = [agent_manager.spawn('test', 'm', chat_name='c')['id'] for _ in range(3)]

    for aid in ids:
        agent_manager._agents[aid].finish_with_result('ok')

    assert _wait_for(lambda: len(agent_manager._agents) == 0), \
        "agents should all be swept after batch fires"

    batch_events = [d for e, d in event_bus_capture.events if e == 'agent_batch_complete']
    assert len(batch_events) == 1, f"expected exactly 1 batch event, got {len(batch_events)}"
    data = batch_events[0]
    assert data['chat_name'] == 'c'
    assert data['agent_count'] == 3
    assert '[AGENT REPORT' in data['report']


# ─── 5.3 Batch fires per chat, not globally ──────────────────────────────────

def test_batch_fires_per_chat_not_globally(
    agent_manager, blocking_worker_cls, event_bus_capture,
):
    """[REGRESSION_GUARD] 2 in chat A + 1 in chat B: A finishing fires A's batch only."""
    _register(agent_manager, blocking_worker_cls)
    a1 = agent_manager.spawn('test', 'm', chat_name='A')['id']
    a2 = agent_manager.spawn('test', 'm', chat_name='A')['id']
    b1 = agent_manager.spawn('test', 'm', chat_name='B')['id']

    agent_manager._agents[a1].finish_with_result('ok')
    agent_manager._agents[a2].finish_with_result('ok')

    assert _wait_for(lambda: a1 not in agent_manager._agents and a2 not in agent_manager._agents)

    batch_events = [d for e, d in event_bus_capture.events if e == 'agent_batch_complete']
    assert len(batch_events) == 1
    assert batch_events[0]['chat_name'] == 'A'
    assert b1 in agent_manager._agents, "chat B's agent should be untouched"


# ─── 5.4 Shutdown kills running + clears registry ────────────────────────────

def test_shutdown_clears_registry(agent_manager, fast_cancel_worker_cls):
    """Shutdown: cancel every running worker + clear registry."""
    _register(agent_manager, fast_cancel_worker_cls)
    r1 = agent_manager.spawn('test', 'm', chat_name='c')
    r2 = agent_manager.spawn('test', 'm', chat_name='c')
    workers = [agent_manager._agents[r1['id']], agent_manager._agents[r2['id']]]
    assert all(w.status == 'running' for w in workers)

    agent_manager.shutdown(timeout=1)
    assert len(agent_manager._agents) == 0
    for w in workers:
        assert w.status == 'cancelled', f"worker {w.name} not cancelled"


# ─── 5.5 Dismiss running: cancel + remove + publish ──────────────────────────

def test_dismiss_during_running_cancels_removes_publishes(
    agent_manager, fast_cancel_worker_cls, event_bus_capture,
):
    """[REGRESSION_GUARD] dismiss() on running agent: cancel(), remove from registry, AGENT_DISMISSED."""
    _register(agent_manager, fast_cancel_worker_cls)
    r = agent_manager.spawn('test', 'm', chat_name='c')
    agent_id = r['id']
    worker = agent_manager._agents[agent_id]
    assert worker.status == 'running'

    res = agent_manager.dismiss(agent_id)
    assert res['status'] == 'dismissed'
    assert res['name'] == worker.name
    assert agent_id not in agent_manager._agents
    assert worker.status == 'cancelled'
    assert worker.result is None

    dismiss_events = [d for e, d in event_bus_capture.events if e == 'agent_dismissed']
    assert any(d.get('id') == agent_id for d in dismiss_events), \
        f"expected dismiss event for {agent_id}, saw: {dismiss_events}"


# ─── 5.6 Recall running returns 'still running' (no stale leak) ──────────────

def test_recall_running_returns_still_running_not_stale_result(
    agent_manager, blocking_worker_cls,
):
    """[DATA_INTEGRITY] recall on a running agent must never leak partial .result output."""
    _register(agent_manager, blocking_worker_cls)
    r = agent_manager.spawn('test', 'm', chat_name='c')
    worker = agent_manager._agents[r['id']]
    worker.result = 'I would leak if recall returned .result blindly'

    out = agent_manager.recall(r['id'])
    assert out['status'] == 'running'
    assert 'still running' in out['result'].lower()
    assert 'leak' not in out['result']


# ─── 5.7 Cancel during run voids result ──────────────────────────────────────

def test_cancel_during_run_voids_result(blocking_worker_cls):
    """[REGRESSION_GUARD] cancel() must null .result — even if run() already wrote output.

    Before the fix, a worker could finish producing partial output between the
    cancel signal firing and run()'s check; that stale .result would then be
    served by recall().
    """
    w = blocking_worker_cls(agent_id='x', name='t', mission='m')
    w.start()
    w.result = 'pre-cancel value'
    w.cancel()
    assert w.status == 'cancelled'
    assert w.result is None


# ─── 5.8 Status setter blocks cancelled/failed → done regression ─────────────

def test_status_setter_blocks_cancelled_to_done_regression(blocking_worker_cls):
    """[REGRESSION_GUARD] Terminal states must not regress to 'done'."""
    w1 = blocking_worker_cls(agent_id='x', name='t', mission='m')
    w1._status = 'cancelled'
    w1.status = 'done'
    assert w1.status == 'cancelled', "cancelled must not regress to done"

    w2 = blocking_worker_cls(agent_id='y', name='t', mission='m')
    w2._status = 'failed'
    w2.status = 'done'
    assert w2.status == 'failed', "failed must not regress to done"


# ─── 5.9 on_complete exception doesn't kill thread ───────────────────────────

def test_run_wrapper_on_complete_exception_doesnt_kill_thread(blocking_worker_cls):
    """[REGRESSION_GUARD] If on_complete raises, the thread must still land clean.

    Swallowing on_complete exceptions is the only thing keeping a single bad
    callback from freezing the agent in 'running' forever.
    """
    def bad_on_complete(agent_id, chat_name):
        raise RuntimeError('boom')

    w = blocking_worker_cls(
        agent_id='x', name='t', mission='m',
        on_complete=bad_on_complete,
    )
    w.start()
    w.finish_with_result('ok')
    w._thread.join(timeout=2)
    assert not w._thread.is_alive(), "thread leaked after on_complete raised"
    assert w.status == 'done'
    assert w.result == 'ok'


# ─── 5.19 Unique ids + distinct names on concurrent spawn ────────────────────

def test_concurrent_spawn_produces_unique_ids_and_distinct_names(
    agent_manager, blocking_worker_cls,
):
    """[PROACTIVE] With names=['Alpha','Bravo','Charlie'] and 3 concurrent spawns:
    all 3 ids unique, all 3 names distinct."""
    _register(agent_manager, blocking_worker_cls, names=['Alpha', 'Bravo', 'Charlie'])
    results = []
    results_lock = threading.Lock()

    def _spawn():
        r = agent_manager.spawn('test', 'm', chat_name='c')
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=_spawn) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    succeeded = [r for r in results if 'id' in r]
    assert len(succeeded) == 3
    ids = [r['id'] for r in succeeded]
    names = [r['name'] for r in succeeded]
    assert len(set(ids)) == 3, f"ids not unique: {ids}"
    assert len(set(names)) == 3, f"names not distinct: {names}"


# ─── 5.20 Name counter resets when no running of same type ───────────────────

def test_next_name_resets_counter_when_no_running(
    agent_manager, blocking_worker_cls, event_bus_capture,
):
    """After all agents of a type finish + batch sweep, next spawn starts from names[0]."""
    _register(agent_manager, blocking_worker_cls, names=['Alpha', 'Bravo'])
    r1 = agent_manager.spawn('test', 'm', chat_name='c')
    assert r1['name'] == 'Alpha'
    agent_manager._agents[r1['id']].finish_with_result('ok')

    assert _wait_for(lambda: not agent_manager._agents), \
        "agent should be swept by batch after finishing"

    r2 = agent_manager.spawn('test', 'm', chat_name='c')
    assert r2['name'] == 'Alpha', f"expected counter reset to Alpha, got {r2['name']}"


# ─── 5.21 Unknown agent type errors cleanly ──────────────────────────────────

def test_spawn_unknown_agent_type_error(agent_manager):
    """Unknown type returns {error:...}, does not crash or partially register."""
    r = agent_manager.spawn('nonexistent', 'm', chat_name='c')
    assert 'error' in r
    assert "'nonexistent'" in r['error']
    assert len(agent_manager._agents) == 0


# ─── 5.23 Recall unknown returns error ───────────────────────────────────────

def test_recall_unknown_returns_error(agent_manager):
    out = agent_manager.recall('deadbeef')
    assert 'error' in out
    assert 'not found' in out['error'].lower()


# ─── 5.23b Dismiss unknown returns error ─────────────────────────────────────

def test_dismiss_unknown_returns_error(agent_manager):
    out = agent_manager.dismiss('deadbeef')
    assert 'error' in out


# ─── 5.24 check_batch_complete noops if no agents in chat ────────────────────

def test_check_batch_complete_noops_if_no_agents_in_chat(
    agent_manager, event_bus_capture,
):
    """Calling _check_batch_complete with a chat that has zero agents must not fire a batch.

    This is the guard that keeps the 'already popped' race from double-firing
    a batch report for the same chat.
    """
    agent_manager._check_batch_complete('phantom-id', 'phantom-chat')
    batch_events = [e for e, _ in event_bus_capture.events if e == 'agent_batch_complete']
    assert batch_events == []


# ─── 5.25 Elapsed zero pre-start, frozen post-end ────────────────────────────

def test_elapsed_zero_pre_start_frozen_post_end(blocking_worker_cls):
    """elapsed is 0 before start(), frozen to a fixed value after termination."""
    w = blocking_worker_cls(agent_id='x', name='t', mission='m')
    assert w.elapsed == 0

    w.start()
    w.finish_with_result('ok')
    w._thread.join(timeout=2)
    assert not w._thread.is_alive()

    snapshot1 = w.elapsed
    time.sleep(0.1)
    snapshot2 = w.elapsed
    assert snapshot1 == snapshot2, \
        f"elapsed must freeze after end, got {snapshot1} → {snapshot2}"


# ─── 5.26 to_dict.has_result reflects result presence ────────────────────────

def test_to_dict_has_result_reflects_result_presence(blocking_worker_cls):
    """to_dict() must expose has_result as truthy iff .result is not None."""
    w = blocking_worker_cls(agent_id='x', name='t', mission='m')
    assert w.to_dict()['has_result'] is False
    w.result = 'something'
    assert w.to_dict()['has_result'] is True
    w.result = None
    assert w.to_dict()['has_result'] is False


# ─── Extras: register_type + get_types ───────────────────────────────────────

def test_register_type_and_get_types(agent_manager, blocking_worker_cls):
    """register_type populates the registry; get_types returns public metadata only."""
    _register(agent_manager, blocking_worker_cls, type_key='a')
    _register(agent_manager, blocking_worker_cls, type_key='b')
    types = agent_manager.get_types()
    assert 'a' in types and 'b' in types
    assert types['a']['display_name'] == 'Test Agent'
    assert 'factory' not in types['a'], "get_types must not leak the factory callable"


def test_unregister_type_removes_from_registry(agent_manager, blocking_worker_cls):
    """unregister_type pops type from registry; subsequent spawns fail cleanly."""
    _register(agent_manager, blocking_worker_cls, type_key='rm')
    assert 'rm' in agent_manager.get_types()
    agent_manager.unregister_type('rm')
    assert 'rm' not in agent_manager.get_types()
    r = agent_manager.spawn('rm', 'm', chat_name='c')
    assert 'error' in r


def test_check_all_filters_by_chat(agent_manager, blocking_worker_cls):
    """check_all(chat_name=X) must return only agents whose chat_name matches."""
    _register(agent_manager, blocking_worker_cls)
    agent_manager.spawn('test', 'm', chat_name='A')
    agent_manager.spawn('test', 'm', chat_name='A')
    agent_manager.spawn('test', 'm', chat_name='B')

    assert len(agent_manager.check_all()) == 3
    assert len(agent_manager.check_all(chat_name='A')) == 2
    assert len(agent_manager.check_all(chat_name='B')) == 1
    assert len(agent_manager.check_all(chat_name='nonexistent')) == 0
