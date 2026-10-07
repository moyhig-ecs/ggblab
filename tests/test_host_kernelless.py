"""A6 (2026-10-07): outside a kernel the façade needs the server and the document named; it never guesses a server."""
import pytest
from ggblab.host.html_host import GeoGebra, NoHolderError


def test_outside_a_kernel_the_server_must_be_named(monkeypatch):
    monkeypatch.setattr("ggblab.host.html_host.kernel_id", lambda: None)
    with pytest.raises(ValueError, match="server_url"):
        GeoGebra()


def test_outside_a_kernel_the_document_must_be_named(monkeypatch):
    monkeypatch.setattr("ggblab.host.html_host.kernel_id", lambda: None)
    with pytest.raises(ValueError, match="doc"):
        GeoGebra(server_url="http://127.0.0.1:1")


def test_named_server_and_document_construct_without_a_kernel(monkeypatch):
    monkeypatch.setattr("ggblab.host.html_host.kernel_id", lambda: None)
    g = GeoGebra(server_url="http://127.0.0.1:1", token="t", doc="agent.ipynb")       # the events probe fails silently (no server)
    assert g.mount_id == "doc:agent.ipynb" and g._headers == {"Authorization": "token t"} and g.fail_fast is True


def test_no_holder_error_is_a_timeout_error():
    assert issubclass(NoHolderError, TimeoutError)


def test_the_mount_html_cannot_be_ended_by_a_param(monkeypatch):
    monkeypatch.setattr("ggblab.host.html_host.kernel_id", lambda: None)
    g = GeoGebra(server_url="http://127.0.0.1:1", doc="x", title="</script><b>x</b>")
    shown = []
    monkeypatch.setattr("ggblab.host.html_host.display", lambda h: shown.append(h.data))
    g.mount()
    assert "</script><b>" not in shown[0] and "<\\/script>" in shown[0]
