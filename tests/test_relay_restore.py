"""B6 (10-05): the relay keeps each box's own copy of the state — the latest XML, asked of the holder after every
state-changing request, and the log of those requests — and hands the XML to a NEW holder on its first poll."""
import asyncio
from ggblab.host.relay import Mailbox, STATE_KINDS, SNAP_PREFIX


def run(coro):
    return asyncio.run(coro)


async def _poll(mb, mount, client):
    return await mb.take_requests(mount, wait=0, client=client, lease=40)


def test_a_change_is_logged_then_the_holder_is_asked_for_the_xml():
    async def main():
        mb = Mailbox()
        rid = mb.submit("doc:a", {"kind": "eval", "commands": ["A = (1, 2)"]})
        got = await _poll(mb, "doc:a", "tab1")
        assert [r["req_id"] for r in got["requests"]] == [rid] and "restore" not in got
        mb.resolve(rid, [["A"]])                                                      # the holder answered the change
        got2 = await _poll(mb, "doc:a", "tab1")                                        # ... and is now asked for the XML
        assert [r["kind"] for r in got2["requests"]] == ["xml_out"] and got2["requests"][0]["req_id"].startswith(SNAP_PREFIX)
        mb.resolve(got2["requests"][0]["req_id"], "<xml>A</xml>")
        b = mb.box("doc:a")
        assert b["xml"] == "<xml>A</xml>" and b["xml_seq"] == 1 and b["xml_by"] == "tab1" and b["snap"] is None
        assert [e["request"] for e in b["log"]] == [{"kind": "eval", "commands": ["A = (1, 2)"]}]
        assert "restore" not in await _poll(mb, "doc:a", "tab1")                      # the holder that produced it is not told to restore
        assert mb.state("doc:a")["xml"] == "<xml>A</xml>" and mb.state("doc:a")["log_seq"] == 1
    run(main())


def test_a_new_holder_gets_the_state_once():
    async def main():
        mb = Mailbox()
        rid = mb.submit("doc:a", {"kind": "new"}); await _poll(mb, "doc:a", "tab1"); mb.resolve(rid, True)
        snap = (await _poll(mb, "doc:a", "tab1"))["requests"][0]; mb.resolve(snap["req_id"], "<xml/>")
        mb.release("doc:a", "tab1")                                                    # tab1 closed
        got = await _poll(mb, "doc:a", "tab2")                                         # tab2 takes the box: the state comes with the lease
        assert got["held"] is False and got["restore"] == {"xml": "<xml/>", "seq": 1}
        assert "restore" not in await _poll(mb, "doc:a", "tab2")                      # once per state version
    run(main())


def test_reads_do_not_snapshot_and_snapshots_coalesce():
    async def main():
        mb = Mailbox()
        r1 = mb.submit("doc:a", {"kind": "xml_out"}); await _poll(mb, "doc:a", "t"); mb.resolve(r1, "<x/>")
        assert not (await _poll(mb, "doc:a", "t"))["requests"]                        # a read changes nothing: no snapshot
        r2 = mb.submit("doc:a", {"kind": "eval", "commands": ["A=(0,0)"]}); r3 = mb.submit("doc:a", {"kind": "delete", "label": "A"})
        await _poll(mb, "doc:a", "t"); mb.resolve(r2, [["A"]]); mb.resolve(r3, True)   # two changes before any snapshot reply
        reqs = (await _poll(mb, "doc:a", "t"))["requests"]
        assert [r["kind"] for r in reqs] == ["xml_out"]                               # one snapshot in flight, the box marked dirty
        assert mb.box("doc:a")["dirty"] is True
        mb.resolve(reqs[0]["req_id"], "<x>1</x>")
        reqs2 = (await _poll(mb, "doc:a", "t"))["requests"]
        assert [r["kind"] for r in reqs2] == ["xml_out"]                              # the dirty box is asked again
        mb.resolve(reqs2[0]["req_id"], "<x>2</x>")
        assert mb.box("doc:a")["xml"] == "<x>2</x>" and mb.box("doc:a")["xml_seq"] == 2
        assert [e["request"]["kind"] for e in mb.box("doc:a")["log"]] == ["eval", "delete"]
    run(main())


def test_state_kinds_are_the_four_writes():
    assert STATE_KINDS == {"eval", "xml_in", "delete", "new"}
