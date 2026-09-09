"""RPC mailbox (09-09, ruling (i)): the kernel's call is parked until the browser replies; events are pulled."""
import asyncio
from ggblab.host.relay import Mailbox


def run(coro):
    return asyncio.run(coro)


def test_call_is_parked_until_the_browser_replies():
    async def main():
        mb = Mailbox()
        rid = mb.submit("doc:nb.ipynb", {"kind": "eval", "commands": ["A = (1, 2)"]})
        got = await mb.take_requests("doc:nb.ipynb", wait=0, client="tab1", lease=40)       # the browser's poll
        assert [r["req_id"] for r in got["requests"]] == [rid] and got["held"] is False
        waiter = asyncio.create_task(mb.wait_reply(rid, wait=5))                           # the kernel's parked call
        await asyncio.sleep(0.01)
        assert mb.resolve(rid, [["A"]]) is True                                            # the browser's reply
        assert await waiter == ("ok", [["A"]])
        assert rid not in mb.pending
    run(main())


def test_pending_slice_then_await_then_late_reply():
    async def main():
        mb = Mailbox()
        rid = mb.submit("doc:nb.ipynb", {"kind": "xml_out"})
        assert await mb.wait_reply(rid, wait=0.05) == ("pending", None)                    # a proxy-sized slice elapsed
        mb.resolve(rid, "<xml/>")
        assert await mb.wait_reply(rid, wait=0.05) == ("ok", "<xml/>")                     # the next slice gets it
        assert await mb.wait_reply("nope", wait=0) == ("unknown", None)
        assert mb.resolve("late", 1) is False and mb.results["late"][0] == 1               # kept for a later await
        assert await mb.wait_reply("late", wait=0) == ("ok", 1)
    run(main())


def test_lease_one_live_poller_per_box():
    async def main():
        mb = Mailbox()
        a = await mb.take_requests("doc:nb", wait=0, client="A", lease=1)
        b = await mb.take_requests("doc:nb", wait=0, client="B", lease=1)
        assert a["held"] is False and b["held"] is True
        mb.boxes["doc:nb"]["holder_t"] -= 2                                                # A's lease lapses
        b2 = await mb.take_requests("doc:nb", wait=0, client="B", lease=1)
        assert b2["held"] is False and mb.boxes["doc:nb"]["holder"] == "B"
    run(main())


def test_events_are_pulled_not_pushed():
    async def main():
        mb = Mailbox()
        s1 = mb.push_event("doc:nb", {"type": "add", "label": "A"})
        s2 = mb.push_event("doc:nb", {"type": "update", "label": "A"})
        evs, nxt = await mb.pull_events("doc:nb", since=0, wait=0)
        assert [e["data"]["label"] for e in evs] == ["A", "A"] and (s1, s2, nxt) == (1, 2, 2)
        evs, nxt = await mb.pull_events("doc:nb", since=nxt, wait=0)
        assert evs == [] and nxt == 2
        evs, nxt = await mb.pull_events("doc:nb", since="latest", wait=0)                  # a new object starts from now
        assert evs == [] and nxt == 2
    run(main())


def test_nothing_in_the_host_package_opens_a_comm():
    import pathlib, re
    pkg = pathlib.Path(__file__).resolve().parents[1] / "ggblab"
    src = "\n".join(p.read_text(encoding="utf-8") for p in pkg.rglob("*.py"))
    assert not re.search(r"register_comm_target|control_handlers\[|Comm\(target_name", src)
