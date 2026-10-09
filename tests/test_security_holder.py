"""N2-08 / N2-01 (rc4): the holder page does not let a ?token= or ?deploy= value end its scripts or load a script from
another host.  Positive control (stage 2, 2026-10-09, before the fix): a token "</script>ZZPOCZZ" appeared raw in the
page config; the deploy check passed "//evil.example/x.js".  The inputs are inert markers (nothing is run)."""
import pytest

from ggblab.host.relay import deploy_ok, holder_html, token_ok

MARK = "</script>ZZPOCZZ"


def test_token_cannot_end_the_page_config_script():                       # T1
    html = holder_html("/", "m1", {}, None, MARK)
    assert MARK not in html
    assert "<\\/script>ZZPOCZZ" in html


@pytest.mark.parametrize("deploy", ["//evil.example/x.js", "http://evil.example/x.js", "/\\evil.example/x.js",
                                    "https://evil.example/x.js", "https://www.geogebra.org.evil.example/x.js",
                                    "javascript:void(0)", "x.js"])
def test_deploy_refused(deploy):                                          # T2 (refused)
    assert deploy_ok(deploy) is False


@pytest.mark.parametrize("deploy", ["https://www.geogebra.org/apps/deployggb.js", "/apps/deployggb.js"])
def test_deploy_allowed(deploy):                                          # T2 (allowed)
    assert deploy_ok(deploy) is True


def test_default_deploy_is_allowed():
    from ggblab.host.relay import DEPLOY_DEFAULT
    assert deploy_ok(DEPLOY_DEFAULT)


@pytest.mark.parametrize("token", [MARK, "abc</", "a b", "a\"b", ""])
def test_token_form_refused(token):                                       # T3
    assert token_ok(token) is False


@pytest.mark.parametrize("token", ["abc", "0123456789abcdef", "A-z_9"])
def test_token_form_allowed(token):
    assert token_ok(token) is True
