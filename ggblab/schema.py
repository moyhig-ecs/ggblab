"""GeoGebra XSD loader (library, no communication). Carried from v1 `ggblab/schema.py` verbatim in behaviour;
the cache path is package-relative (`ggblab/xsd/common.xsd`, shipped) instead of the current directory."""
from __future__ import annotations
import io, logging
from pathlib import Path
import xmlschema

URL = "http://www.geogebra.org/apps/xsd/common.xsd"
LOCAL = Path(__file__).parent / "xsd" / "common.xsd"
_log = logging.getLogger(__name__)


def schema_text() -> str:
    if LOCAL.exists():
        return LOCAL.read_text(encoding="utf-8")
    import requests                                   # only when the shipped copy is missing
    r = requests.get(URL); r.raise_for_status()
    LOCAL.parent.mkdir(parents=True, exist_ok=True); LOCAL.write_text(r.text, encoding="utf-8")
    return r.text


class ggb_schema:
    """`.schema` is the compiled xmlschema.XMLSchema; `.decode(xml)` = schema.decode (dict with '@attr' keys)."""
    def __init__(self):
        self.schema = xmlschema.XMLSchema(io.StringIO(schema_text()))

    def decode(self, xml: str):
        return self.schema.decode(xml)


def eltype_pattern() -> str:
    """The XSD's closed set of `<element type=…>` values (simpleType elType, a regex pattern, not an enumeration)."""
    import re
    m = re.search(r'name="elType".*?<xs:pattern\s+value="([^"]+)"', schema_text(), re.S)
    if not m:
        raise RuntimeError("elType pattern not found in common.xsd")
    return m.group(1)


_SCHEMA: ggb_schema | None = None


def get_schema() -> ggb_schema:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = ggb_schema()
    return _SCHEMA
