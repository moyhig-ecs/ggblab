"""B2 (10-05): the relay serves a holder page for a box — same div + same mount.js as a notebook output, same-origin,
no CSP sandbox, page config with baseUrl and (only when opened with ?token=) the token."""
import json, re
from ggblab.host import relay
from ggblab.host.relay import holder_html, DEPLOY_DEFAULT


def _cfg(html):
    m = re.search(r'__CFG__|JSON\.parse|const M = (\{.*?\});', html)      # mount.js reads its cfg from the substituted literal
    assert "__CFG__" not in html, "cfg was not substituted"
    pc = re.search(r'<script id="jupyter-config-data" type="application/json">(\{.*?\})</script>', html)
    return json.loads(pc.group(1))


def test_holder_page_has_the_div_the_script_and_the_page_config():
    html = holder_html("/", "doc:proto", {"appName": "suite"}, None, None)
    dom = re.search(r'<div id="ggb-([0-9a-f]{12})"', html).group(1)
    assert json.dumps({"mount": "doc:proto", "dom": dom, "params": {"appName": "suite"}, "deploy": DEPLOY_DEFAULT}) in html
    assert _cfg(html) == {"baseUrl": "/"}                      # cookie-authenticated page: no token in the page
    assert "sandbox" not in html and "<script id=\"jupyter-config-data\"" in html


def test_token_is_echoed_only_when_the_page_was_opened_with_it():
    assert "token" not in _cfg(holder_html("/hub/user/x/", "doc:a", None, None, None))
    assert _cfg(holder_html("/hub/user/x/", "doc:a", None, None, "abc")) == {"baseUrl": "/hub/user/x/", "token": "abc"}


def test_the_same_mount_js_as_the_notebook_output():
    js = relay._HOLDER_JS.read_text(encoding="utf-8")
    html = holder_html("/", "doc:p", None, "https://example.org/deployggb.js", None)
    dom = re.search(r'<div id="ggb-([0-9a-f]{12})"', html).group(1)
    cfg = json.dumps({"mount": "doc:p", "dom": dom, "params": {}, "deploy": "https://example.org/deployggb.js"})
    body = html[html.index("<body"):]
    assert body.count("<script>") == 1 and js.replace("__CFG__", cfg) in body     # byte-identical mount.js with the cfg substituted


def test_mount_is_escaped_in_the_title():
    html = holder_html("/", 'doc:<b>"x"</b>', None, None, None)
    assert "<title>ggblab holder doc:&lt;b&gt;&quot;x&quot;&lt;/b&gt;</title>" in html


def test_route_is_registered():
    import inspect
    src = inspect.getsource(relay._load_jupyter_server_extension)
    assert '"holder"' in src and "HolderHandler" in src
