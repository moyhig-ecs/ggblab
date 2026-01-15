"""Unit tests for GeoGebra command validation (syntax and semantics).

Tests the validation features added to ggbapplet module:
- GeoGebraSyntaxError exception
- GeoGebraSemanticsError exception
- Syntax checking in command()
- Semantics checking in command()
- Command extraction and caching
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, Mock

from ggblab.ggbapplet import GeoGebraSyntaxError, GeoGebraSemanticsError
from ggblab.parser import tokenize_with_commas


# Mock helper to avoid network calls during GeoGebra initialization
@pytest.fixture
def mock_geogebra_init():
    """Mock GeoGebra initialization to avoid schema download."""
    with patch('ggblab.ggbapplet.ggb_construction') as mock_construction, \
         patch('ggblab.ggbapplet.ggb_parser') as mock_parser:
        mock_construction.return_value = Mock()
        mock_parser.return_value = Mock()
        
        # Import here to get the patched version
        from ggblab.ggbapplet import GeoGebra
        yield GeoGebra


class TestGeoGebraSyntaxError:
    """Test GeoGebraSyntaxError exception."""
    
    def test_syntax_error_attributes(self):
        """Test that GeoGebraSyntaxError has correct attributes."""
        command = "Circle(A, B)))"
        message = "Mismatched parentheses"
        error = GeoGebraSyntaxError(command, message)
        
        assert error.command == command
        assert error.message == message
        assert "Syntax error" in str(error)
        assert command in str(error)
        assert message in str(error)
    
    def test_syntax_error_inheritance(self):
        """Test that GeoGebraSyntaxError is an Exception."""
        error = GeoGebraSyntaxError("cmd", "msg")
        assert isinstance(error, Exception)


class TestGeoGebraSemanticsError:
    """Test GeoGebraSemanticsError exception."""
    
    def test_semantics_error_attributes(self):
        """Test that GeoGebraSemanticsError has correct attributes."""
        command = "Circle(A, C)"
        message = "Object C does not exist"
        missing = ["C"]
        error = GeoGebraSemanticsError(command, message, missing)
        
        assert error.command == command
        assert error.message == message
        assert error.missing_objects == missing
        assert "Semantics error" in str(error)
        assert command in str(error)
        assert message in str(error)
    
    def test_semantics_error_without_missing_objects(self):
        """Test GeoGebraSemanticsError without missing_objects parameter."""
        error = GeoGebraSemanticsError("cmd", "msg")
        assert error.missing_objects == []
    
    def test_semantics_error_inheritance(self):
        """Test that GeoGebraSemanticsError is an Exception."""
        error = GeoGebraSemanticsError("cmd", "msg")
        assert isinstance(error, Exception)


class TestTokenizeWithCommandExtraction:
    """Test tokenize_with_commas with command extraction feature."""
    
    def test_extract_commands_simple(self):
        """Test command extraction from simple command."""
        result = tokenize_with_commas("Circle(A, 2)", extract_commands=True)
        
        assert 'tokens' in result
        assert 'commands' in result
        assert 'Circle' in result['commands']
        assert result['tokens'] == ['Circle', ['A', ',', '2']]
    
    def test_extract_commands_nested(self):
        """Test command extraction from nested command."""
        result = tokenize_with_commas(
            "Circle(A, Distance(A, B))", 
            extract_commands=True
        )
        
        assert 'Circle' in result['commands']
        assert 'Distance' in result['commands']
        assert len(result['commands']) == 2
    
    def test_extract_commands_multiple(self):
        """Test command extraction from complex nested command."""
        result = tokenize_with_commas(
            "Point(Intersect(Line(A, B), Circle(C, D)))",
            extract_commands=True
        )
        
        assert 'Point' in result['commands']
        assert 'Intersect' in result['commands']
        assert 'Line' in result['commands']
        assert 'Circle' in result['commands']
        assert len(result['commands']) == 4
    
    def test_extract_commands_with_brackets(self):
        """Test command extraction with square brackets."""
        result = tokenize_with_commas("Segment[A, B]", extract_commands=True)
        
        assert 'Segment' in result['commands']
        assert result['tokens'] == ['Segment', ['A', ',', 'B']]
    
    def test_extract_commands_empty_string(self):
        """Test command extraction from empty string."""
        result = tokenize_with_commas("", extract_commands=True)
        
        assert result['tokens'] == []
        assert result['commands'] == set()
    
    def test_backward_compatibility(self):
        """Test that default behavior (extract_commands=False) still works."""
        result = tokenize_with_commas("Circle(A, B)")
        
        # Should return list, not dict
        assert isinstance(result, list)
        assert result == ['Circle', ['A', ',', 'B']]
    
    def test_non_command_tokens_not_extracted(self):
        """Test that non-command tokens are not extracted."""
        result = tokenize_with_commas("2 + 3", extract_commands=True)
        
        # Numbers shouldn't be extracted as commands
        assert len(result['commands']) == 0
    
    def test_operators_not_extracted(self):
        """Test that operators are not extracted as commands."""
        result = tokenize_with_commas("A + B", extract_commands=True)
        
        # Operators like + shouldn't be extracted
        # Only tokens before '(' or '[' are considered commands
        assert len(result['commands']) == 0


class TestGeoGebraSyntaxValidation:
    """Test syntax validation in GeoGebra.command()."""
    
    @pytest.mark.asyncio
    async def test_syntax_check_disabled_by_default(self, mock_geogebra_init):
        """Test that syntax checking is disabled by default."""
        ggb = mock_geogebra_init()
        assert ggb.check_syntax is False
    
    @pytest.mark.asyncio
    async def test_syntax_check_valid_command(self, mock_geogebra_init):
        """Test syntax checking with valid command."""
        ggb = mock_geogebra_init()
        ggb.check_syntax = True
        ggb.comm = MagicMock()
        ggb.comm.send_recv = AsyncMock(return_value={'value': 'A'})
        
        # Should not raise exception for valid syntax
        result = await ggb.command("Circle(A, 2)")
        assert result == {'value': 'A'}
    
    @pytest.mark.asyncio
    async def test_syntax_check_invalid_parentheses(self, mock_geogebra_init):
        """Test syntax checking with mismatched parentheses."""
        ggb = mock_geogebra_init()
        ggb.check_syntax = True
        
        # Should raise GeoGebraSyntaxError
        with pytest.raises(GeoGebraSyntaxError) as exc_info:
            await ggb.command("Circle(A, B)))")
        
        assert "Circle(A, B)))" in str(exc_info.value)
        assert "Mismatched" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_syntax_check_invalid_brackets(self, mock_geogebra_init):
        """Test syntax checking with mismatched brackets."""
        ggb = mock_geogebra_init()
        ggb.check_syntax = True
        
        with pytest.raises(GeoGebraSyntaxError) as exc_info:
            await ggb.command("Segment[A, B]]")
        
        assert "Segment[A, B]]" in str(exc_info.value)


class TestGeoGebraSemanticsValidation:
    """Test semantics validation in GeoGebra.command()."""
    
    @pytest.mark.asyncio
    async def test_semantics_check_disabled_by_default(self, mock_geogebra_init):
        """Test that semantics checking is disabled by default."""
        ggb = mock_geogebra_init()
        assert ggb.check_semantics is False
    
    @pytest.mark.asyncio
    async def test_semantics_check_existing_objects(self, mock_geogebra_init):
        """Test semantics checking when objects exist."""
        ggb = mock_geogebra_init()
        ggb.check_semantics = True
        ggb.comm = MagicMock()
        # Mock getAllObjectNames to return A and B
        ggb.function = AsyncMock(return_value=['A', 'B'])
        ggb.comm.send_recv = AsyncMock(return_value={'value': 'c'})
        
        # Should not raise exception when objects exist
        result = await ggb.command("Circle(A, B)")
        
        # Verify getAllObjectNames was called
        ggb.function.assert_called_once_with("getAllObjectNames")
        assert result == {'value': 'c'}
    
    @pytest.mark.asyncio
    async def test_semantics_check_missing_objects(self, mock_geogebra_init):
        """Test semantics checking when objects don't exist."""
        ggb = mock_geogebra_init()
        ggb.check_semantics = True
        # Mock getAllObjectNames to return only A
        ggb.function = AsyncMock(return_value=['A'])
        
        # Should raise GeoGebraSemanticsError for missing object C
        with pytest.raises(GeoGebraSemanticsError) as exc_info:
            await ggb.command("Circle(A, C)")
        
        assert "Circle(A, C)" in str(exc_info.value)
        assert exc_info.value.missing_objects == ['C']
    
    @pytest.mark.asyncio
    async def test_semantics_check_multiple_missing_objects(self, mock_geogebra_init):
        """Test semantics checking with multiple missing objects."""
        ggb = mock_geogebra_init()
        ggb.check_semantics = True
        ggb.function = AsyncMock(return_value=['A'])
        
        # B and C are both missing
        with pytest.raises(GeoGebraSemanticsError) as exc_info:
            await ggb.command("Line(B, C)")
        
        # Both B and C should be reported as missing
        missing = exc_info.value.missing_objects
        assert 'B' in missing
        assert 'C' in missing
    
    @pytest.mark.asyncio
    async def test_semantics_check_ignores_keywords(self, mock_geogebra_init):
        """Test that semantics checking ignores reserved keywords."""
        ggb = mock_geogebra_init()
        ggb.check_semantics = True
        ggb.function = AsyncMock(return_value=['A'])
        ggb.comm = MagicMock()
        ggb.comm.send_recv = AsyncMock(return_value={'value': 'result'})
        
        # 'true' and 'false' should not be checked as objects
        result = await ggb.command("SetValue(A, true)")
        assert result == {'value': 'result'}
    
    @pytest.mark.asyncio
    async def test_semantics_check_ignores_numbers(self, mock_geogebra_init):
        """Test that semantics checking ignores numeric literals."""
        ggb = mock_geogebra_init()
        ggb.check_semantics = True
        ggb.function = AsyncMock(return_value=['A'])
        ggb.comm = MagicMock()
        ggb.comm.send_recv = AsyncMock(return_value={'value': 'c'})
        
        # Numbers should not be checked as objects
        result = await ggb.command("Circle(A, 2)")
        assert result == {'value': 'c'}
    
    @pytest.mark.asyncio
    async def test_semantics_check_empty_applet(self, mock_geogebra_init):
        """Test semantics checking with empty applet."""
        ggb = mock_geogebra_init()
        ggb.check_semantics = True
        ggb.function = AsyncMock(return_value=[])
        
        # Should fail when applet is empty but objects are referenced
        with pytest.raises(GeoGebraSemanticsError):
            await ggb.command("Circle(A, B)")
    
    @pytest.mark.asyncio
    async def test_semantics_check_none_from_applet(self, mock_geogebra_init):
        """Test semantics checking when getAllObjectNames returns None."""
        ggb = mock_geogebra_init()
        ggb.check_semantics = True
        ggb.function = AsyncMock(return_value=None)
        
        # Should handle None gracefully (treat as empty list)
        with pytest.raises(GeoGebraSemanticsError):
            await ggb.command("Circle(A, B)")


class TestCombinedValidation:
    """Test combined syntax and semantics validation."""
    
    @pytest.mark.asyncio
    async def test_both_validations_enabled(self, mock_geogebra_init):
        """Test with both syntax and semantics checking enabled."""
        ggb = mock_geogebra_init()
        ggb.check_syntax = True
        ggb.check_semantics = True
        ggb.function = AsyncMock(return_value=['A', 'B'])
        ggb.comm = MagicMock()
        ggb.comm.send_recv = AsyncMock(return_value={'value': 'c'})
        
        # Should pass both validations
        result = await ggb.command("Circle(A, B)")
        assert result == {'value': 'c'}
    
    @pytest.mark.asyncio
    async def test_syntax_fails_first(self, mock_geogebra_init):
        """Test that syntax error is raised before semantics check."""
        ggb = mock_geogebra_init()
        ggb.check_syntax = True
        ggb.check_semantics = True
        ggb.function = AsyncMock(return_value=['A'])
        
        # Syntax error should be raised (not semantics)
        with pytest.raises(GeoGebraSyntaxError):
            await ggb.command("Circle(A, B)))")
        
        # getAllObjectNames should not have been called
        ggb.function.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_both_disabled_accepts_invalid(self, mock_geogebra_init):
        """Test that invalid commands pass when validation is disabled."""
        ggb = mock_geogebra_init()
        ggb.check_syntax = False
        ggb.check_semantics = False
        ggb.comm = MagicMock()
        ggb.comm.send_recv = AsyncMock(return_value={'error': 'syntax error'})
        
        # Should not raise exception even with invalid syntax
        # (GeoGebra will handle the error)
        result = await ggb.command("Circle(A, B)))")
        assert 'error' in result


class TestValidationDocumentation:
    """Test that validation behavior matches documentation."""
    
    def test_geogebra_class_has_check_flags(self, mock_geogebra_init):
        """Test that GeoGebra class has validation flags."""
        ggb = mock_geogebra_init()
        assert hasattr(ggb, 'check_syntax')
        assert hasattr(ggb, 'check_semantics')
    
    def test_default_validation_state(self, mock_geogebra_init):
        """Test default validation state is disabled."""
        ggb = mock_geogebra_init()
        assert ggb.check_syntax is False
        assert ggb.check_semantics is False
    
    def test_validation_can_be_enabled(self, mock_geogebra_init):
        """Test that validation can be enabled."""
        ggb = mock_geogebra_init()
        ggb.check_syntax = True
        ggb.check_semantics = True
        assert ggb.check_syntax is True
        assert ggb.check_semantics is True


# Run tests with: pytest tests/test_validation.py -v
