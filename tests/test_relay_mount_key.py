"""Stage 3: the mailbox address is the document (relay.mount_key)."""
from ggblab.host.relay import mount_key


def test_mount_key_is_the_document_not_the_object():
    assert mount_key("examples/eg5_construction.ipynb", "k1") == "doc:examples/eg5_construction.ipynb"
    assert mount_key("examples/eg5_construction.ipynb", "k2") == mount_key("examples/eg5_construction.ipynb", "k1")   # kernel restart: same box
    assert mount_key(None, "k1") == "kernel:k1"                                                                   # console / no session
    assert mount_key("nb.ipynb", "k1", "second") == "doc:nb.ipynb:second"                                         # a second applet on purpose
