import pytest


def test_load_blocking_client_missing_file():
    from ggblab_core import load_blocking_client

    with pytest.raises(FileNotFoundError):
        load_blocking_client("/nonexistent/path/connection-file.json")
