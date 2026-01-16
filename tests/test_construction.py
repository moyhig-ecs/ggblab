"""Unit tests for ggb_construction module.

Tests file loading/saving functionality for multiple formats:
- .ggb (base64-encoded ZIP)
- Plain ZIP
- JSON
- Plain XML
"""

import pytest
import tempfile
import os
import base64
import zipfile
import json
from pathlib import Path

from ggblab.construction import ggb_construction


# Test fixtures

@pytest.fixture
def sample_xml():
    """Sample GeoGebra construction XML."""
    return '''<?xml version="1.0" encoding="utf-8"?>
<geogebra format="5.0">
<construction>
    <element type="point" label="A">
        <coords x="0" y="0" z="1"/>
    </element>
    <element type="point" label="B">
        <coords x="3" y="4" z="1"/>
    </element>
</construction>
</geogebra>'''


@pytest.fixture
def sample_xml_construction_only():
    """Expected construction element (stripped)."""
    return '<construction>\n    <element type="point" label="A">\n        <coords x="0" y="0" z="1" />\n    </element>\n    <element type="point" label="B">\n        <coords x="3" y="4" z="1" />\n    </element>\n</construction>'


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdirname:
        yield Path(tmpdirname)


@pytest.fixture
def ggb_file_base64(temp_dir, sample_xml):
    """Create a base64-encoded .ggb file."""
    ggb_path = temp_dir / "test.ggb"
    
    # Create in-memory ZIP
    zip_buffer = zipfile.ZipFile(temp_dir / "temp.zip", 'w')
    zip_buffer.writestr('geogebra.xml', sample_xml)
    zip_buffer.close()
    
    # Read ZIP and base64 encode
    with open(temp_dir / "temp.zip", 'rb') as f:
        zip_bytes = f.read()
    
    b64_bytes = base64.b64encode(zip_bytes)
    
    # Write base64-encoded file
    with open(ggb_path, 'wb') as f:
        f.write(b64_bytes)
    
    return ggb_path


@pytest.fixture
def ggb_file_zip(temp_dir, sample_xml):
    """Create a plain ZIP .ggb file."""
    ggb_path = temp_dir / "test_zip.ggb"
    
    with zipfile.ZipFile(ggb_path, 'w') as zf:
        zf.writestr('geogebra.xml', sample_xml)
    
    return ggb_path


@pytest.fixture
def ggb_file_json(temp_dir, sample_xml):
    """Create a JSON format .ggb file."""
    ggb_path = temp_dir / "test.json"
    
    json_data = {
        "archive": [
            {
                "fileName": "geogebra.xml",
                "fileContent": sample_xml
            }
        ]
    }
    
    with open(ggb_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f)
    
    return ggb_path


@pytest.fixture
def ggb_file_xml(temp_dir, sample_xml):
    """Create a plain XML file."""
    xml_path = temp_dir / "test.xml"
    
    with open(xml_path, 'w', encoding='utf-8') as f:
        f.write(sample_xml)
    
    return xml_path


# Tests

class TestConstructionLoad:
    """Test file loading functionality."""
    
    def test_load_base64_ggb(self, ggb_file_base64):
        """Test loading base64-encoded .ggb file."""
        c = ggb_construction()
        result = c.load(str(ggb_file_base64))
        
        assert result is c  # Should return self for chaining
        assert c.source_file == str(ggb_file_base64)
        assert c.base64_buffer is not None
        assert c.geogebra_xml is not None
        assert '<construction>' in c.geogebra_xml
        assert 'label="A"' in c.geogebra_xml
    
    def test_load_zip_ggb(self, ggb_file_zip):
        """Test loading plain ZIP .ggb file."""
        c = ggb_construction()
        result = c.load(str(ggb_file_zip))
        
        assert result is c
        assert c.base64_buffer is not None
        assert c.geogebra_xml is not None
        assert '<construction>' in c.geogebra_xml
    
    def test_load_json_ggb(self, ggb_file_json):
        """Test loading JSON format file."""
        c = ggb_construction()
        result = c.load(str(ggb_file_json))
        
        assert result is c
        assert c.geogebra_xml is not None
        assert '<construction>' in c.geogebra_xml
    
    def test_load_xml(self, ggb_file_xml):
        """Test loading plain XML file."""
        c = ggb_construction()
        result = c.load(str(ggb_file_xml))
        
        assert result is c
        assert c.base64_buffer is None  # Plain XML has no base64
        assert c.geogebra_xml is not None
        assert '<construction>' in c.geogebra_xml
    
    def test_load_nonexistent_file(self):
        """Test loading a file that doesn't exist."""
        c = ggb_construction()
        
        with pytest.raises(FileNotFoundError, match="File not found"):
            c.load("/nonexistent/path/file.ggb")
    
    def test_xml_stripped_to_construction(self, ggb_file_xml):
        """Test that XML is stripped to <construction> element only."""
        c = ggb_construction()
        c.load(str(ggb_file_xml))
        
        # Should NOT contain <geogebra> root element
        assert not c.geogebra_xml.startswith('<?xml')
        assert not c.geogebra_xml.startswith('<geogebra')
        
        # Should start with <construction>
        assert c.geogebra_xml.startswith('<construction>')
    
    def test_scientific_notation_normalization(self, temp_dir):
        """Test handling of scientific notation in GeoGebra XML.
        
        Note: GeoGebra Applet may produce lowercase 'e' in scientific notation
        (e.g., "1.5e-1"), which does not conform to XML schema validators that
        expect uppercase 'E' (e.g., "1.5E-1"). This is a known GeoGebra limitation.
        
        This test verifies that the construction module loads such data without
        error, even though it's technically invalid. Validation should occur at
        the schema level, not in this module.
        """
        xml_with_sci = '''<?xml version="1.0" encoding="utf-8"?>
<geogebra>
<construction>
    <element type="point" label="A">
        <coords x="1.5e-1" y="2.3e-2" z="1"/>
    </element>
</construction>
</geogebra>'''
        
        xml_path = temp_dir / "sci_notation.xml"
        with open(xml_path, 'w', encoding='utf-8') as f:
            f.write(xml_with_sci)
        
        c = ggb_construction()
        
        # Should load without error, even with lowercase 'e' in scientific notation
        c.load(str(xml_path))
        
        # Verify content was loaded
        assert c.geogebra_xml is not None
        assert '<construction>' in c.geogebra_xml
        assert 'coords' in c.geogebra_xml
        
        # The scientific notation may remain as-is (lowercase 'e')
        # or may be normalized to uppercase 'E' depending on implementation.
        # Both should be acceptable; validation is a separate concern.
        xml_content = c.geogebra_xml
        has_valid_notation = ('e-1' in xml_content or 'E-1' in xml_content) and \
                             ('e-2' in xml_content or 'E-2' in xml_content)
        assert has_valid_notation, "Scientific notation should be preserved or normalized"


class TestConstructionSave:
    """Test file saving functionality."""
    
    def test_save_with_base64(self, ggb_file_base64, temp_dir):
        """Test saving when base64_buffer is set (writes decoded archive)."""
        c = ggb_construction()
        c.load(str(ggb_file_base64))
        
        output_path = temp_dir / "output.ggb"
        c.save(file=str(output_path))
        
        assert output_path.exists()
        
        # Should be a valid ZIP file
        assert zipfile.is_zipfile(output_path)
        
        # Should contain geogebra.xml
        with zipfile.ZipFile(output_path, 'r') as zf:
            assert 'geogebra.xml' in zf.namelist()
    
    def test_save_without_base64(self, ggb_file_xml, temp_dir):
        """Test saving when base64_buffer is None (writes plain XML)."""
        c = ggb_construction()
        c.load(str(ggb_file_xml))
        
        output_path = temp_dir / "output.xml"
        c.save(file=str(output_path))
        
        assert output_path.exists()
        
        # Should NOT be a ZIP file
        assert not zipfile.is_zipfile(output_path)
        
        # Should be plain XML
        with open(output_path, 'r', encoding='utf-8') as f:
            content = f.read()
            assert '<construction>' in content
    
    def test_save_auto_filename(self, ggb_file_base64, temp_dir):
        """Test auto-generated filename (name_1.ggb, name_2.ggb, ...)."""
        c = ggb_construction()
        c.load(str(ggb_file_base64))
        
        # First save should create test_1.ggb
        c.save()
        
        expected_path_1 = temp_dir / "test_1.ggb"
        assert expected_path_1.exists()
        
        # Second save should create test_2.ggb
        c.save()
        
        expected_path_2 = temp_dir / "test_2.ggb"
        assert expected_path_2.exists()
    
    def test_save_overwrite(self, ggb_file_base64, temp_dir):
        """Test overwrite=True mode (overwrites source_file)."""
        c = ggb_construction()
        c.load(str(ggb_file_base64))
        
        original_mtime = os.path.getmtime(ggb_file_base64)
        
        # Wait a bit to ensure different mtime
        import time
        time.sleep(0.01)
        
        # Overwrite original
        c.save(overwrite=True)
        
        new_mtime = os.path.getmtime(ggb_file_base64)
        assert new_mtime >= original_mtime  # File was modified
    
    def test_save_custom_path(self, ggb_file_xml, temp_dir):
        """Test saving to custom path."""
        c = ggb_construction()
        c.load(str(ggb_file_xml))
        
        custom_path = temp_dir / "custom" / "nested" / "output.xml"
        
        # Should create directories if needed
        c.save(file=str(custom_path))
        
        assert custom_path.exists()
    
    def test_save_returns_self(self, ggb_file_xml, temp_dir):
        """Test that save() returns self for method chaining."""
        c = ggb_construction()
        c.load(str(ggb_file_xml))
        
        result = c.save(file=str(temp_dir / "output.xml"))
        
        assert result is c


class TestConstructionRoundtrip:
    """Test load → save → load roundtrip."""
    
    def test_roundtrip_base64(self, ggb_file_base64, temp_dir):
        """Test roundtrip with base64-encoded .ggb."""
        # Load original
        c1 = ggb_construction()
        c1.load(str(ggb_file_base64))
        xml1 = c1.geogebra_xml
        
        # Save to new file
        output_path = temp_dir / "roundtrip.ggb"
        c1.save(file=str(output_path))
        
        # Load saved file
        c2 = ggb_construction()
        c2.load(str(output_path))
        xml2 = c2.geogebra_xml
        
        # XML should be identical
        assert xml1 == xml2
    
    def test_roundtrip_xml(self, ggb_file_xml, temp_dir):
        """Test roundtrip with plain XML."""
        c1 = ggb_construction()
        c1.load(str(ggb_file_xml))
        xml1 = c1.geogebra_xml
        
        output_path = temp_dir / "roundtrip.xml"
        c1.save(file=str(output_path))
        
        c2 = ggb_construction()
        c2.load(str(output_path))
        xml2 = c2.geogebra_xml
        
        assert xml1 == xml2


class TestConstructionEdgeCases:
    """Test edge cases and error handling."""
    
    def test_load_empty_file(self, temp_dir):
        """Test loading an empty file."""
        empty_file = temp_dir / "empty.ggb"
        empty_file.touch()
        
        c = ggb_construction()
        
        with pytest.raises(RuntimeError, match="Failed to load the file"):
            c.load(str(empty_file))
    
    def test_load_corrupted_zip(self, temp_dir):
        """Test loading a corrupted ZIP file."""
        corrupted = temp_dir / "corrupted.ggb"
        
        with open(corrupted, 'wb') as f:
            f.write(b'PK\x03\x04corrupted_data_here')
        
        c = ggb_construction()
        
        with pytest.raises(RuntimeError):
            c.load(str(corrupted))
    
    def test_multiple_loads(self, ggb_file_xml, ggb_file_json):
        """Test loading multiple files with same instance."""
        c = ggb_construction()
        
        # First load
        c.load(str(ggb_file_xml))
        xml_content = c.geogebra_xml
        
        # Second load should overwrite
        c.load(str(ggb_file_json))
        json_content = c.geogebra_xml
        
        # Both should have content
        assert xml_content is not None
        assert json_content is not None
        assert '<construction>' in json_content


# Run tests with: pytest tests/test_construction.py -v
