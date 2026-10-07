"""A1 (2026-10-07): a request has a lifetime, the kernel can withdraw it, a call can refuse to wait for a holder,
the boxes are listable, and events that fell off a box's log are reported."""
import asyncio, time
from ggblab.host.relay import Mailbox, mount_key


def run(coro):
    return asyncio.run(coro)


def test_an_expired_request_is_never_handed_to_a_holder():
    async def main():
        mb = Mailbox()
        rid = mb.submit("doc:nb", {"kind": "eval", "commands": ["A = (1, 2)"]}, timeout=0.02)
        await asyncio.sleep(0.05)                                                              # nobody held the box meanwhile
        got = await mb.take_requests("doc:nb", wait=0, client="tab1", lease=40)
        assert got["requests"] == [] and rid not in mb.pending                                 # dropped, not run late
        assert await mb.wait_reply(rid, wait=0) == ("unknown", None)
    run(main())


def test_a_request_within_its_lifetime_is_handed_over():
    async def main():
        mb = Mailbox()
        rid = mb.submit("doc:nb", {"kind": "eval", "commands": ["A = (1, 2)"]}, timeout=5)
        got = await mb.take_requests("doc:nb", wait=0, client="tab1", lease=40)
        assert [r["req_id"] for r in got["requests"]] == [rid]
    run(main())


def test_cancel_withdraws_a_queued_request():
    async def main():
        mb = Mailbox()
        rid = mb.submit("doc:nb", {"kind": "eval", "commands": ["A = (1, 2)"]})
        waiter = asyncio.create_task(mb.wait_reply(rid, wait=5))
        await asyncio.sleep(0.01)
        assert mb.cancel(rid) == {"cancelled": True, "queued": True}
        assert await waiter == ("ok", {"error": "cancelled"})                                  # the waiter learns, not a silent drop
        got = await mb.take_requests("doc:nb", wait=0, client="tab1", lease=40)
        assert got["requests"] == []
        assert mb.cancel(rid) == {"cancelled": False, "queued": False}                         # idempotent
    run(main())


def test_no_holder_is_known_at_once_and_a_holder_is_noticed():
    async def main():
        mb = Mailbox()
        t0 = time.time()
        assert await mb.wait_holder("doc:nb", timeout=0.1) is False                            # nobody polls: back within the grace
        assert time.time() - t0 < 1.0
        assert mb.has_live_holder("doc:nb") is False
        waiter = asyncio.create_task(mb.wait_holder("doc:nb", timeout=2.0))
        await asyncio.sleep(0.01)
        await mb.take_requests("doc:nb", wait=0, client="tab1", lease=40)                     # the browser arrives
        assert await asyncio.wait_for(waiter, 1.0) is True                                     # the parked call proceeds at once
        assert mb.has_live_holder("doc:nb") is True
    run(main())


def test_the_snapshot_request_survives_draining():
    async def main():
        mb = Mailbox()
        await mb.take_requests("doc:nb", wait=0, client="tab1", lease=40)
        rid = mb.submit("doc:nb", {"kind": "eval", "commands": ["A = (1, 2)"]})
        await mb.take_requests("doc:nb", wait=0, client="tab1", lease=40)
        mb.resolve(rid, [["A"]])                                                               # triggers the server's own xml_out
        got = await mb.take_requests("doc:nb", wait=0, client="tab1", lease=40)
        assert [r["kind"] for r in got["requests"]] == ["xml_out"]                             # the snapshot is handed over
    run(main())


def test_boxes_summary_lists_holders_and_queues():
    async def main():
        mb = Mailbox()
        await mb.take_requests("doc:a", wait=0, client="tab1", lease=40)
        mb.submit("doc:b", {"kind": "xml_out"})
        rows = {r["mount"]: r for r in mb.summary()}
        assert rows["doc:a"]["holder"] is True and rows["doc:a"]["queued"] == 0
        assert rows["doc:b"]["holder"] is False and rows["doc:b"]["queued"] == 1 and rows["doc:b"]["pending"] == 1
    run(main())


def test_events_that_fell_off_the_log_are_reported():
    async def main():
        mb = Mailbox(ev_max=3)
        for i in range(5):
            mb.push_event("doc:nb", {"type": "update", "label": f"A{i}"})
        evs, nxt, dropped = await mb.pull_events("doc:nb", since=0, wait=0)
        assert [e["seq"] for e in evs] == [3, 4, 5] and nxt == 5 and dropped == 2             # 1 and 2 are gone, and we are told
        evs, nxt, dropped = await mb.pull_events("doc:nb", since=5, wait=0)
        assert evs == [] and dropped == 0
    run(main())
