"""XML normalisation / errata for GeoGebra construction XML (library, no communication).
Carried from v1 `ggblab/file.py` (`_normalize_geogebra_xml`, `_apply_xml_errata`) and
`ggblab_extra/construction_io.py` (`_normalize_exponent`)."""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from typing import Callable

XML_ERRATA_HANDLERS: list[Callable[[str], str]] = []


def normalize_exponent(xml: str) -> str:
    """'3.67e-16' → '3.67E-16' (the XSD pattern expects 'E')."""
    return re.sub(r"(?<=\d)e(?=[+-]?\d+)", "E", xml) if isinstance(xml, str) else xml


def normalize_geogebra_xml(xml: str) -> str:
    """Upper-case exponent 'e', `cartesian3d` → `cartesian`, `O_{1}` → `O_1` (single-digit subscripts only)."""
    if not isinstance(xml, str):
        return xml
    xml = re.sub(r"(?<=[0-9\.])e([+-]?\d+)", r"E\1", xml)
    xml = xml.replace("cartesian3d", "cartesian")
    xml = re.sub(r"_\{([0-9])\}", r"_\1", xml)
    return xml


def apply_xml_errata(xml: str) -> str:
    out = xml
    for h in XML_ERRATA_HANDLERS:
        out = h(out)
    return normalize_geogebra_xml(out)


def construction_xml(xml: str) -> str:
    """Return the `<construction>…</construction>` document for any of: a full `<geogebra>` document (getXML()),
    a bare `<construction>` element, or a fragment of `<element>`s (getXML(label))."""
    s = xml.strip()
    if not s.startswith("<"):
        raise ValueError("not XML")
    try:
        root = ET.fromstring(s)
    except ET.ParseError:
        return "<construction>" + s + "</construction>"          # fragment with several top-level elements
    if root.tag == "geogebra":
        c = root.find("./construction")
        if c is None:
            raise ValueError("<geogebra> without <construction>")
        return ET.tostring(c, encoding="unicode")
    if root.tag == "construction":
        return s
    return "<construction>" + s + "</construction>"
