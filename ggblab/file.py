"""File loader and saver for GeoGebra constructions.

This module implements `ggb_file`, a lightweight loader/saver that detects
and extracts the construction XML from `.ggb` archives, ZIP files, JSON,
or plain XML. For DataFrame-based construction I/O and convenience helpers
(for example `ConstructionIO.save_dataframe`), see the optional
`ggblab_extra` package.
"""

import base64
import io
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile

from .schema import ggb_schema


class ggb_file:
    """GeoGebra file (.ggb) loader and saver.

    Handles multiple file formats:
    - .ggb files (base64-encoded ZIP archives)
    - Plain ZIP archives
    - JSON format
    - Plain XML (geogebra.xml)

    The loader automatically detects file type from magic bytes and extracts
    the construction XML. The geogebra_xml is automatically stripped to the
    <construction> element and scientific notation is normalized.

    Attributes:
        ggb_schema: XML schema for validation
        source_file (str): Path to the loaded file
        base64_buffer (bytes): Base64-encoded .ggb archive (if applicable)
        geogebra_xml (str): Extracted construction XML

    Example:
        >>> file = ggb_file()
        >>> file.load('myfile.ggb')
        >>> file.save('output.ggb')

    Note:
        The heavy DataFrame-based I/O helpers and convenience persistence
        functions (for example, ``ConstructionIO.save_dataframe``) live in
        the optional ``ggblab_extra`` package. The core ``ggblab`` package
        provides a lightweight file loader/saver here; install
        ``ggblab_extra`` for richer high-level workflows.
    """

    def __init__(self):
        """Initialize the `ggb_file` helper and load the XML schema."""
        self.ggb_schema = ggb_schema().schema

    def load(self, file):
        """Load a GeoGebra construction from file.

        Supports multiple formats:
        - Base64-encoded .ggb (starts with 'UEsD')
        - ZIP archive (starts with 'PK')
        - JSON format (starts with '{' or '[')
        - Plain XML

        The construction XML is automatically extracted and normalized:
        - Stripped to <construction> element only
        - Scientific notation fixed (e-1 → E-1)

        Args:
            file (str): Path to the .ggb, .zip, .json, or .xml file.

        Returns:
            ggb_file: Self reference for method chaining.

        Raises:
            FileNotFoundError: If the file does not exist.
            RuntimeError: If file loading fails.

        Example:
            >>> f = ggb_file().load('circle.ggb')
            >>> print(f.geogebra_xml[:100])
        """
        self.source_file = file

        self.base64_buffer = None
        self.geogebra_xml = None

        try:
            with open(self.source_file, "rb") as f:

                def unzip(buff):
                    with zipfile.ZipFile(io.BytesIO(base64.b64decode(buff)), "r") as zf:
                        # for fileinfo in zf.infolist():
                        #     print(fileinfo)
                        with zf.open("geogebra.xml", "r") as zff:
                            try:
                                s = zff.read()
                            except:
                                pass
                    return s

                match tuple(f.read(4).decode()):
                    case ("U", "E", "s", "D"):
                        # base64 encoded zip
                        f.close()
                        with open(self.source_file, "rb") as f2:
                            self.base64_buffer = (
                                f2.read()
                            )  # base64.b64decode(f2.read())
                            self.geogebra_xml = unzip(self.base64_buffer)
                    case ("P", "K", _, _):
                        # zip
                        f.close()
                        with open(self.source_file, "rb") as f2:
                            # b64encode for sending GeoGebra Applet
                            self.base64_buffer = base64.b64encode(f2.read())
                            self.geogebra_xml = unzip(self.base64_buffer)
                    case ("{", _, _, _) | ("[", _, _, _):
                        # json
                        f.close()
                        with open(self.source_file, "r", encoding="utf-8") as f2:
                            self.base64_buffer = json.load(f2)
                            for f in self.base64_buffer["archive"]:
                                if f["fileName"] == "geogebra.xml":
                                    self.geogebra_xml = f["fileContent"]
                    case _:
                        # xml?
                        with open(self.source_file, "r", encoding="utf-8") as f2:
                            self.geogebra_xml = f2.read()
            # return self.initialize_dataframe(file)
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: {self.source_file}")
        except Exception as e:
            raise RuntimeError(f"Failed to load the file: {e}")

        # strip to construction element and normalize XML (scientific
        # notation, legacy tokens, etc.)
        raw_xml = ET.tostring(
            ET.fromstring(self.geogebra_xml).find("./construction"), encoding="unicode"
        )
        self.geogebra_xml = self._normalize_geogebra_xml(raw_xml)

        return self

    @staticmethod
    def _normalize_geogebra_xml(xml: str) -> str:
        """Normalize GeoGebra construction XML.

        Performs small, safe normalizations previously done inline:
        - Normalize scientific notation from lower-case `e` to upper-case
          `E` in numeric exponents (e.g. `1.23e-4` -> `1.23E-4`).
        - Replace legacy token `cartesian3d` with `cartesian`.

        This centralizes transformations so future fixes are easier to
        maintain and optionally unit-test.
        """
        if not isinstance(xml, str):
            return xml
        # Upper-case the scientific `e` when used as exponent marker.
        try:
            # Replace a lower-case 'e' that appears after a digit or dot and
            # is followed by an optional sign and digits with 'E' plus the
            # exponent. This avoids changing unrelated 'e' characters.
            xml = re.sub(r"(?<=[0-9\.])e([+-]?\d+)", r"E\1", xml)
        except Exception:
            pass

        try:
            xml = xml.replace("cartesian3d", "cartesian")
        except Exception:
            pass

        # Default errata: strip braces around single-digit subscripts,
        # e.g. O_{1} -> O_1. Conservative: only single digits after '_'.
        try:
            xml = re.sub(r"_\{([0-9])\}", r"_\1", xml)
        except Exception:
            pass

        return xml

    # XML errata handlers for legacy GeoGebra XML quirks. Users may append
    # callables to this list to perform conservative fixes before schema
    # decoding (for example, historic label formatting like `O_{1}`).
    XML_ERRATA_HANDLERS = []

    @staticmethod
    def _apply_xml_errata(xml: str) -> str:
        """Apply registered errata handlers (in order) and the unified
        normalization/errata step.
        """
        if not isinstance(xml, str):
            return xml
        out = xml
        for h in ggb_file.XML_ERRATA_HANDLERS:
            try:
                out = h(out)
            except Exception:
                pass
        out = ggb_file._normalize_geogebra_xml(out)
        return out

    def save(self, overwrite=False, file=None):
        """Save the construction to a file.

        Saving behavior:
        - If base64_buffer is set: writes decoded archive (.ggb format)
        - If base64_buffer is None: writes plain XML (geogebra_xml)
        - Target extension does not enforce format (e.g., saving to .ggb with
          no base64_buffer will write plain XML bytes)

        Args:
            overwrite (bool): If True, overwrite source_file. Defaults to False.
            file (str, optional): Target file path. If None, auto-generates
                next available filename (name_1.ggb, name_2.ggb, ...).

        Returns:
            ggb_construction: Self reference for method chaining.

        Example:
            >>> c = ggb_construction().load('circle.ggb')
            >>> c.save()  # Saves to circle_1.ggb
            >>> c.save(overwrite=True)  # Overwrites circle.ggb
            >>> c.save(file='output.ggb')  # Saves to output.ggb

        Note:
            getBase64() from the applet may not include non-XML artifacts
            (thumbnails, etc.) from the original archive. Saving after API
            changes produces a leaner .ggb file.
        """

        def get_next_revised_filename(filename):
            """Generate the next available non-existing filename by appending '_1', '_2', etc. before the file extension."""
            if not os.path.exists(filename):
                return filename

            root, ext = os.path.splitext(filename)
            i = 1
            new_filename = f"{root}_{i}{ext}"

            while os.path.exists(new_filename):
                i += 1
                new_filename = f"{root}_{i}{ext}"

            return new_filename

        if file is None:
            if overwrite:
                file = self.source_file
            else:
                file = get_next_revised_filename(self.source_file)

        with open(file, "wb") as f:
            if self.base64_buffer is not None:
                f.write(base64.b64decode(self.base64_buffer))
            else:
                f.write(self.geogebra_xml.encode("utf-8"))
        return self
