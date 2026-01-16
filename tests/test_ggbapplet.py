"""Unit tests for ggbapplet module.

Tests GeoGebra class functionality including validation and caching.
"""

import pytest
import polars as pl
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio

from ggblab.ggbapplet import GeoGebra, GeoGebraSyntaxError, GeoGebraSemanticsError


class TestGeoGebraInitialization:
    """Test GeoGebra singleton initialization."""
    
    def test_singleton_pattern(self):
        """Test that GeoGebra follows singleton pattern."""
        ggb1 = GeoGebra()
        ggb2 = GeoGebra()
        
        assert ggb1 is ggb2
    
    def test_initialization_state(self):
        """Test initial state of GeoGebra instance."""
        ggb = GeoGebra()
        
        assert ggb.initialized is False
        assert ggb.check_syntax is False
        assert ggb.check_semantics is False
        assert ggb._applet_objects == set()
        assert ggb.parser is not None
        assert ggb.construction is not None


class TestSyntaxValidation:
    """Test syntax validation functionality."""
    
    def test_syntax_check_disabled_by_default(self):
        """Test that syntax checking is disabled by default."""
        ggb = GeoGebra()
        
        assert ggb.check_syntax is False
    
    def test_syntax_check_enable(self):
        """Test enabling syntax check."""
        ggb = GeoGebra()
        ggb.check_syntax = True
        
        assert ggb.check_syntax is True
    
    def test_syntax_error_raised(self):
        """Test that GeoGebraSyntaxError is raised for invalid syntax."""
        async def run_test():
            ggb = GeoGebra()
            ggb.check_syntax = True
            
            # Mock the parser to raise an exception on invalid command
            ggb.parser.tokenize_with_commas = MagicMock(side_effect=ValueError("Invalid syntax"))
            
            with pytest.raises(GeoGebraSyntaxError) as exc_info:
                await ggb.command("Invalid[")
            
            assert "Invalid[" in str(exc_info.value)
            assert exc_info.value.command == "Invalid["
        
        asyncio.run(run_test())


class TestSemanticValidation:
    """Test semantic validation functionality."""
    
    def test_semantic_check_disabled_by_default(self):
        """Test that semantic checking is disabled by default."""
        ggb = GeoGebra()
        
        assert ggb.check_semantics is False
    
    def test_semantic_check_enable(self):
        """Test enabling semantic check."""
        ggb = GeoGebra()
        ggb.check_semantics = True
        
        assert ggb.check_semantics is True
    
    def test_semantic_error_missing_objects(self):
        """Test that GeoGebraSemanticsError is raised for missing objects."""
        async def run_test():
            ggb = GeoGebra()
            ggb.check_semantics = True
            ggb._applet_objects = {'A', 'B'}  # Only A and B exist
            
            # Mock the parser and comm
            ggb.parser.tokenize_with_commas = MagicMock(return_value=[['Circle'], ['A', 'C']])
            ggb.parser.command_cache = {'Circle'}
            ggb.comm = AsyncMock()
            
            # Mock flatten to return tokens
            with patch('ggblab.ggbapplet.flatten', return_value=['Circle', 'A', 'C']):
                with pytest.raises(GeoGebraSemanticsError) as exc_info:
                    await ggb.command("Circle[A, C]")
            
            assert 'C' in exc_info.value.missing_objects
            assert "do not exist in applet" in str(exc_info.value)
        
        asyncio.run(run_test())


class TestObjectCache:
    """Test object cache management."""
    
    def test_refresh_object_cache_success(self):
        """Test successful object cache refresh."""
        async def run_test():
            ggb = GeoGebra()
            ggb.comm = AsyncMock()
            
            # Mock function response
            ggb.comm.send_recv = AsyncMock(return_value={'value': ['A', 'B', 'C']})
            
            await ggb.refresh_object_cache()
            
            assert ggb._applet_objects == {'A', 'B', 'C'}
        
        asyncio.run(run_test())
    
    def test_refresh_object_cache_none_response(self):
        """Test object cache refresh with None response."""
        async def run_test():
            ggb = GeoGebra()
            ggb.comm = AsyncMock()
            
            # Mock function response returning None
            ggb.comm.send_recv = AsyncMock(return_value={'value': None})
            
            await ggb.refresh_object_cache()
            
            # Should initialize empty set instead of failing
            assert ggb._applet_objects == set()
        
        asyncio.run(run_test())
    
    def test_refresh_object_cache_empty_response(self):
        """Test object cache refresh with empty list response."""
        async def run_test():
            ggb = GeoGebra()
            ggb.comm = AsyncMock()
            
            # Mock function response returning empty list
            ggb.comm.send_recv = AsyncMock(return_value={'value': []})
            
            await ggb.refresh_object_cache()
            
            # Should initialize empty set
            assert ggb._applet_objects == set()
        
        asyncio.run(run_test())
    
    def test_refresh_object_cache_exception(self):
        """Test object cache refresh handles exceptions gracefully."""
        async def run_test():
            ggb = GeoGebra()
            ggb.comm = AsyncMock()
            
            # Mock function to raise exception
            ggb.comm.send_recv = AsyncMock(side_effect=Exception("Connection error"))
            
            # Should not raise, only print warning
            await ggb.refresh_object_cache()
            
            # Cache should remain as is
            assert isinstance(ggb._applet_objects, set)
        
        asyncio.run(run_test())


class TestLiteralDetection:
    """Test literal token detection."""
    
    def test_numeric_literal_integer(self):
        """Test detection of numeric integer literals."""
        ggb = GeoGebra()
        
        assert ggb._is_literal('42') is True
        assert ggb._is_literal('0') is True
        assert ggb._is_literal('-5') is True
    
    def test_numeric_literal_float(self):
        """Test detection of float literals."""
        ggb = GeoGebra()
        
        assert ggb._is_literal('3.14') is True
        assert ggb._is_literal('-2.5') is True
        assert ggb._is_literal('1e-3') is True
    
    def test_string_literal_double_quotes(self):
        """Test detection of string literals with double quotes."""
        ggb = GeoGebra()
        
        assert ggb._is_literal('"hello"') is True
        assert ggb._is_literal('""') is True
    
    def test_string_literal_single_quotes(self):
        """Test detection of string literals with single quotes."""
        ggb = GeoGebra()
        
        assert ggb._is_literal("'hello'") is True
        assert ggb._is_literal("''") is True
    
    def test_boolean_constants(self):
        """Test detection of boolean constants."""
        ggb = GeoGebra()
        
        assert ggb._is_literal('true') is True
        assert ggb._is_literal('false') is True
    
    def test_math_functions(self):
        """Test detection of math function names."""
        ggb = GeoGebra()
        
        assert ggb._is_literal('sin') is True
        assert ggb._is_literal('cos') is True
        assert ggb._is_literal('sqrt') is True
        assert ggb._is_literal('abs') is True
        assert ggb._is_literal('min') is True
        assert ggb._is_literal('max') is True
    
    def test_object_reference(self):
        """Test detection of object references (not literals)."""
        ggb = GeoGebra()
        
        assert ggb._is_literal('A') is False
        assert ggb._is_literal('MyPoint') is False
        assert ggb._is_literal('segment1') is False


class TestSyntaxExceptionAttributes:
    """Test GeoGebraSyntaxError exception properties."""
    
    def test_syntax_error_attributes(self):
        """Test that GeoGebraSyntaxError stores command and message."""
        error = GeoGebraSyntaxError("Invalid[", "Unbalanced brackets")
        
        assert error.command == "Invalid["
        assert error.message == "Unbalanced brackets"
        assert "Invalid[" in str(error)
        assert "Unbalanced brackets" in str(error)


class TestSemanticExceptionAttributes:
    """Test GeoGebraSemanticsError exception properties."""
    
    def test_semantic_error_attributes(self):
        """Test that GeoGebraSemanticsError stores command, message, and objects."""
        error = GeoGebraSemanticsError(
            "Circle[A, C]",
            "Objects not found",
            missing_objects=['C']
        )
        
        assert error.command == "Circle[A, C]"
        assert error.message == "Objects not found"
        assert error.missing_objects == ['C']
        assert "Circle[A, C]" in str(error)
    
    def test_semantic_error_default_missing_objects(self):
        """Test that missing_objects defaults to empty list."""
        error = GeoGebraSemanticsError(
            "Command",
            "Error message"
        )
        
        assert error.missing_objects == []


# Run tests with: pytest tests/test_ggbapplet.py -v
