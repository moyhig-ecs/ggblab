"""Unit tests for GeoGebra command caching in parser module.

Tests the command caching features using shelve:
- Command cache initialization
- Command persistence
- Command retrieval
- Cache management (clear, close)
"""

import pytest
import polars as pl
import os
import tempfile
import shutil

from ggblab.parser import ggb_parser, tokenize_with_commas


def create_construction_df(construction_dict):
    """Helper to create a properly formatted polars DataFrame for parser.
    
    Takes a dict of {object_name: {property: value}} and converts to
    the format expected by parser (5 rows for properties, columns are objects).
    
    Args:
        construction_dict: Dict like {'A': {'Type': 'point', 'Command': '', ...}}
        
    Returns:
        polars.DataFrame ready for parser.initialize_dataframe()
    """
    # Convert to proper format: each column is an object, rows are properties
    data = {}
    for obj_name, properties in construction_dict.items():
        data[obj_name] = [
            properties.get('Type', ''),
            properties.get('Command', ''),
            properties.get('Value', ''),
            properties.get('Caption', ''),
            str(properties.get('Layer', 0))  # Convert to string
        ]
    
    return pl.DataFrame(data)


class TestCommandCacheInitialization:
    """Test command cache initialization."""
    
    def test_cache_enabled_by_default(self):
        """Test that cache is enabled by default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'test_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            assert parser.cache_enabled is True
            assert parser.command_cache is not None
            
            parser.close_cache()
    
    def test_cache_can_be_disabled(self):
        """Test that cache can be disabled at initialization."""
        parser = ggb_parser(cache_enabled=False)
        
        assert parser.cache_enabled is False
        assert parser.command_cache is None
    
    def test_custom_cache_path(self):
        """Test custom cache path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'custom_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            assert parser.cache_path == cache_path
            
            parser.close_cache()
    
    def test_default_cache_path(self):
        """Test default cache path."""
        parser = ggb_parser(cache_enabled=False)
        
        assert parser.cache_path == '.ggblab_command_cache'


class TestCommandExtraction:
    """Test command extraction during parsing."""
    
    def test_extract_commands_from_construction(self):
        """Test that commands are extracted during parse()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'test_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            # Create simple construction
            construction = {
                'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
                'B': {'Type': 'point', 'Command': '', 'Value': '(3, 4)', 'Caption': '', 'Layer': 0},
                'AB': {'Type': 'segment', 'Command': 'Segment[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
                'M': {'Type': 'point', 'Command': 'Midpoint[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
            }
            
            df = create_construction_df(construction)
            parser.initialize_dataframe(df=df)
            parser.parse()
            
            # Check that commands were cached
            cached_commands = parser.get_known_commands()
            
            assert 'Segment' in cached_commands
            assert 'Midpoint' in cached_commands
            assert cached_commands['Segment'] >= 1
            assert cached_commands['Midpoint'] >= 1
            
            parser.close_cache()
    
    def test_no_commands_cached_when_disabled(self):
        """Test that commands are not cached when caching is disabled."""
        parser = ggb_parser(cache_enabled=False)
        
        construction = {
            'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
            'AB': {'Type': 'segment', 'Command': 'Segment[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
        }
        
        df = create_construction_df(construction)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        # Should return empty dict when disabled
        cached_commands = parser.get_known_commands()
        assert cached_commands == {}


class TestCommandPersistence:
    """Test command persistence across parser instances."""
    
    def test_commands_persist_across_instances(self):
        """Test that commands persist when using same cache file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'persist_cache')
            
            # First parser instance
            parser1 = ggb_parser(cache_path=cache_path)
            construction1 = {
                'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
                'AB': {'Type': 'segment', 'Command': 'Segment[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
            }
            df1 = create_construction_df(construction1)
            parser1.initialize_dataframe(df=df1)
            parser1.parse()
            parser1.close_cache()
            
            # Second parser instance with same cache path
            parser2 = ggb_parser(cache_path=cache_path)
            cached_commands = parser2.get_known_commands()
            
            # Should see commands from first instance
            assert 'Segment' in cached_commands
            
            parser2.close_cache()
    
    def test_command_counts_accumulate(self):
        """Test that command counts accumulate across parses."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'count_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            # Parse first construction
            construction1 = {
                'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
                'AB': {'Type': 'segment', 'Command': 'Segment[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
            }
            df1 = create_construction_df(construction1)
            parser.initialize_dataframe(df=df1)
            parser.parse()
            
            first_count = parser.get_known_commands().get('Segment', 0)
            
            # Parse second construction with same command
            construction2 = {
                'C': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
                'CD': {'Type': 'segment', 'Command': 'Segment[C, D]', 'Value': '', 'Caption': '', 'Layer': 0},
            }
            df2 = create_construction_df(construction2)
            parser.initialize_dataframe(df=df2)
            parser.parse()
            
            second_count = parser.get_known_commands().get('Segment', 0)
            
            # Count should have increased
            assert second_count > first_count
            assert second_count >= 2
            
            parser.close_cache()


class TestCommandRetrieval:
    """Test command retrieval from cache."""
    
    def test_get_known_commands_returns_dict(self):
        """Test that get_known_commands returns a dictionary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'test_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            commands = parser.get_known_commands()
            assert isinstance(commands, dict)
            
            parser.close_cache()
    
    def test_get_known_commands_when_disabled(self):
        """Test get_known_commands when caching is disabled."""
        parser = ggb_parser(cache_enabled=False)
        
        commands = parser.get_known_commands()
        assert commands == {}
    
    def test_get_known_commands_with_multiple_commands(self):
        """Test retrieval of multiple cached commands."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'multi_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            construction = {
                'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
                'AB': {'Type': 'segment', 'Command': 'Segment[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
                'M': {'Type': 'point', 'Command': 'Midpoint[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
                'C': {'Type': 'circle', 'Command': 'Circle[M, A]', 'Value': '', 'Caption': '', 'Layer': 0},
            }
            
            df = create_construction_df(construction)
            parser.initialize_dataframe(df=df)
            parser.parse()
            
            commands = parser.get_known_commands()
            
            assert len(commands) >= 3
            assert 'Segment' in commands
            assert 'Midpoint' in commands
            assert 'Circle' in commands
            
            parser.close_cache()


class TestCacheManagement:
    """Test cache management operations."""
    
    def test_clear_command_cache(self):
        """Test clearing the command cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'clear_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            # Add some commands
            construction = {
                'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
                'AB': {'Type': 'segment', 'Command': 'Segment[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
            }
            df = create_construction_df(construction)
            parser.initialize_dataframe(df=df)
            parser.parse()
            
            # Verify commands are cached
            commands_before = parser.get_known_commands()
            assert len(commands_before) > 0
            
            # Clear the cache
            parser.clear_command_cache()
            
            # Verify cache is empty
            commands_after = parser.get_known_commands()
            assert len(commands_after) == 0
            
            parser.close_cache()
    
    def test_clear_cache_when_disabled(self):
        """Test clearing cache when caching is disabled."""
        parser = ggb_parser(cache_enabled=False)
        
        # Should not raise error
        parser.clear_command_cache()
    
    def test_close_cache(self):
        """Test closing the cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'close_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            assert parser.command_cache is not None
            
            parser.close_cache()
            
            assert parser.command_cache is None
    
    def test_close_cache_when_already_closed(self):
        """Test closing cache when already closed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'double_close')
            parser = ggb_parser(cache_path=cache_path)
            
            parser.close_cache()
            # Should not raise error when closing again
            parser.close_cache()


class TestTokenizeWithCommandsIntegration:
    """Test integration of tokenize_with_commas command extraction with caching."""
    
    def test_tokenize_extracts_commands_correctly(self):
        """Test that tokenize_with_commas extracts commands correctly."""
        command_str = "Circle(Midpoint[A, B], Distance(A, B))"
        result = tokenize_with_commas(command_str, extract_commands=True)
        
        assert 'commands' in result
        assert 'Circle' in result['commands']
        assert 'Midpoint' in result['commands']
        assert 'Distance' in result['commands']
    
    def test_parser_uses_tokenize_for_extraction(self):
        """Test that parser uses tokenize_with_commas for command extraction."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'integration_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            # Command with nested function calls
            construction = {
                'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
                'B': {'Type': 'point', 'Command': '', 'Value': '(3, 4)', 'Caption': '', 'Layer': 0},
                'C': {'Type': 'circle', 'Command': 'Circle(A, Distance(A, B))', 'Value': '', 'Caption': '', 'Layer': 0},
            }
            
            df = create_construction_df(construction)
            parser.initialize_dataframe(df=df)
            parser.parse()
            
            cached_commands = parser.get_known_commands()
            
            # Both Circle and Distance should be extracted
            assert 'Circle' in cached_commands
            assert 'Distance' in cached_commands
            
            parser.close_cache()


class TestEdgeCases:
    """Test edge cases in command caching."""
    
    def test_empty_construction(self):
        """Test caching with empty construction - skipped as polars can't handle empty dicts."""
        # Skip this test as polars requires at least one column
        pytest.skip("Polars cannot create DataFrame from empty dict")
    
    def test_construction_with_no_commands(self):
        """Test caching with construction containing no Command values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'no_cmd_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            construction = {
                'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
                'B': {'Type': 'point', 'Command': '', 'Value': '(3, 4)', 'Caption': '', 'Layer': 0},
            }
            
            df = create_construction_df(construction)
            parser.initialize_dataframe(df=df)
            parser.parse()
            
            # Should not fail, just cache nothing new
            commands = parser.get_known_commands()
            assert isinstance(commands, dict)
            
            parser.close_cache()
    
    def test_command_with_empty_string(self):
        """Test handling of empty string command values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, 'empty_cache')
            parser = ggb_parser(cache_path=cache_path)
            
            construction = {
                'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
                'AB': {'Type': 'segment', 'Command': 'Segment[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
            }
            
            df = create_construction_df(construction)
            parser.initialize_dataframe(df=df)
            
            # Should handle empty strings gracefully without crashing
            parser.parse()
            
            # Verify we cached Segment command
            commands = parser.get_known_commands()
            assert 'Segment' in commands
            
            parser.close_cache()


# Run tests with: pytest tests/test_command_caching.py -v
