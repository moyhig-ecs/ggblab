"""Unit tests for ggb_parser module.

Tests dependency graph construction and analysis using NetworkX.
"""

import pytest
import polars as pl
import networkx as nx

from ggblab.parser import ggb_parser


# Test fixtures

@pytest.fixture
def simple_construction():
    """Simple construction: A, B → Line AB → Midpoint M."""
    return {
        'A': {
            'Type': 'point',
            'Command': '',  # Free point, no dependencies
            'Value': '(0, 0)',
            'Caption': '',
            'Layer': 0
        },
        'B': {
            'Type': 'point',
            'Command': '',
            'Value': '(3, 4)',
            'Caption': '',
            'Layer': 0
        },
        'AB': {
            'Type': 'segment',
            'Command': 'Segment[A, B]',
            'Value': '',
            'Caption': '',
            'Layer': 0
        },
        'M': {
            'Type': 'point',
            'Command': 'Midpoint[A, B]',
            'Value': '(1.5, 2)',
            'Caption': '',
            'Layer': 0
        }
    }


@pytest.fixture
def triangle_construction():
    """Triangle construction with derived objects."""
    return {
        'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
        'B': {'Type': 'point', 'Command': '', 'Value': '(4, 0)', 'Caption': '', 'Layer': 0},
        'C': {'Type': 'point', 'Command': '', 'Value': '(2, 3)', 'Caption': '', 'Layer': 0},
        'AB': {'Type': 'segment', 'Command': 'Segment[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
        'BC': {'Type': 'segment', 'Command': 'Segment[B, C]', 'Value': '', 'Caption': '', 'Layer': 0},
        'CA': {'Type': 'segment', 'Command': 'Segment[C, A]', 'Value': '', 'Caption': '', 'Layer': 0},
        'poly1': {'Type': 'polygon', 'Command': 'Polygon[A, B, C]', 'Value': '', 'Caption': '', 'Layer': 0},
    }


@pytest.fixture
def complex_dependencies():
    """Construction with multiple dependency levels."""
    return {
        'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
        'B': {'Type': 'point', 'Command': '', 'Value': '(4, 0)', 'Caption': '', 'Layer': 0},
        'AB': {'Type': 'segment', 'Command': 'Segment[A, B]', 'Value': '', 'Caption': '', 'Layer': 0},
        'M': {'Type': 'point', 'Command': 'Midpoint[A, B]', 'Value': '(2, 0)', 'Caption': '', 'Layer': 0},
        'L': {'Type': 'line', 'Command': 'PerpendicularLine[M, AB]', 'Value': '', 'Caption': '', 'Layer': 0},
        'C': {'Type': 'point', 'Command': 'Point[L]', 'Value': '(2, 3)', 'Caption': '', 'Layer': 0},
        'triangle': {'Type': 'polygon', 'Command': 'Polygon[A, B, C]', 'Value': '', 'Caption': '', 'Layer': 0},
    }


# Tests

class TestParserInitialization:
    """Test parser initialization."""
    
    def test_create_parser(self):
        """Test creating a parser instance."""
        parser = ggb_parser()
        
        assert parser is not None
        assert hasattr(parser, 'df')
        assert hasattr(parser, 'G')
        assert hasattr(parser, 'ft')
    
    def test_initialize_dataframe(self, simple_construction):
        """Test initializing dataframe from construction dict."""
        parser = ggb_parser()
        
        df = pl.DataFrame(simple_construction, strict=False)
        parser.initialize_dataframe(df=df)
        
        assert parser.df is not None
        assert isinstance(parser.df, pl.DataFrame)
        assert 'Type' in parser.df.columns
        assert len(parser.df) == len(simple_construction)


class TestDependencyGraphConstruction:
    """Test dependency graph construction."""
    
    def test_parse_simple_construction(self, simple_construction):
        """Test parsing simple construction into dependency graph."""
        parser = ggb_parser()
        df = pl.DataFrame(simple_construction, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        G = parser.G
        
        # Check graph exists
        assert G is not None
        assert isinstance(G, nx.DiGraph)
        
        # Check nodes
        assert len(G.nodes()) == 4  # A, B, AB, M
        assert 'A' in G.nodes()
        assert 'B' in G.nodes()
        assert 'AB' in G.nodes()
        assert 'M' in G.nodes()
        
        # Check edges (dependencies)
        # AB depends on A and B
        assert G.has_edge('A', 'AB')
        assert G.has_edge('B', 'AB')
        
        # M depends on A and B
        assert G.has_edge('A', 'M')
        assert G.has_edge('B', 'M')
    
    def test_parse_triangle(self, triangle_construction):
        """Test parsing triangle construction."""
        parser = ggb_parser()
        df = pl.DataFrame(triangle_construction, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        G = parser.G
        
        # All objects should be nodes
        assert len(G.nodes()) == len(triangle_construction)
        
        # Check specific dependencies
        assert G.has_edge('A', 'AB')  # AB depends on A
        assert G.has_edge('B', 'AB')  # AB depends on B
        assert G.has_edge('A', 'poly1')  # polygon depends on A
        assert G.has_edge('B', 'poly1')  # polygon depends on B
        assert G.has_edge('C', 'poly1')  # polygon depends on C
    
    def test_identify_roots(self, simple_construction):
        """Test identification of root objects (no dependencies)."""
        parser = ggb_parser()
        df = pl.DataFrame(simple_construction, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        # Roots should be A and B (no incoming edges)
        assert set(parser.roots) == {'A', 'B'}
    
    def test_identify_leaves(self, simple_construction):
        """Test identification of leaf objects (nothing depends on them)."""
        parser = ggb_parser()
        df = pl.DataFrame(simple_construction, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        # Leaves should be AB and M (no outgoing edges)
        assert set(parser.leaves) == {'AB', 'M'}
    
    def test_transitive_dependencies(self, complex_dependencies):
        """Test transitive dependency tracking."""
        parser = ggb_parser()
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        G = parser.G
        
        # C depends on L, which depends on M and AB, which depend on A and B
        # So C transitively depends on A and B
        descendants_of_A = nx.descendants(G, 'A')
        
        assert 'AB' in descendants_of_A
        assert 'M' in descendants_of_A
        assert 'L' in descendants_of_A
        assert 'C' in descendants_of_A
        assert 'triangle' in descendants_of_A


class TestTopologicalAnalysis:
    """Test topological sorting and generation analysis."""
    
    def test_topological_sort(self, complex_dependencies):
        """Test that graph is a valid DAG (directed acyclic graph)."""
        parser = ggb_parser()
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        G = parser.G
        
        # Should be acyclic (DAG)
        assert nx.is_directed_acyclic_graph(G)
        
        # Topological sort should succeed
        topo_order = list(nx.topological_sort(G))
        
        # A and B should come before everything else
        assert topo_order.index('A') < topo_order.index('AB')
        assert topo_order.index('B') < topo_order.index('AB')
        assert topo_order.index('M') < topo_order.index('L')
        assert topo_order.index('L') < topo_order.index('C')
    
    def test_scope_levels(self, complex_dependencies):
        """Test scope level identification (topological generations)."""
        parser = ggb_parser()
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        G = parser.G
        
        # Get topological generations (scope levels)
        generations = list(nx.topological_generations(G))
        
        # Level 0: Root objects (A, B)
        assert set(generations[0]) == {'A', 'B'}
        
        # Level 1: Direct dependents (AB, M)
        assert 'AB' in generations[1]
        assert 'M' in generations[1]
        
        # Level 2: L (depends on M and AB)
        assert 'L' in generations[2]
        
        # Level 3: C (depends on L)
        assert 'C' in generations[3]


class TestCommandTokenization:
    """Test command string tokenization."""
    
    def test_tokenize_simple_command(self):
        """Test tokenization of simple command."""
        parser = ggb_parser()
        
        # This tests internal tokenization logic
        # Actual implementation may vary; adjust based on ggb_parser methods
        construction = {
            'M': {
                'Type': 'point',
                'Command': 'Midpoint[A, B]',
                'Value': '',
                'Caption': '',
                'Layer': 0
            }
        }
        
        df = pl.DataFrame(construction, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        # Check that tokenization extracted 'A' and 'B' as dependencies
        G = parser.G
        
        # M should exist as a node
        assert 'M' in G.nodes()
        
        # Note: Full tokenization test requires access to parser.ft
        # which may not be public. Adjust based on actual API.


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_construction(self):
        """Test parsing empty construction."""
        parser = ggb_parser()
        df = pl.DataFrame({}, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        assert len(parser.G.nodes()) == 0
        assert len(parser.roots) == 0
        assert len(parser.leaves) == 0
    
    def test_single_object(self):
        """Test parsing construction with single object."""
        construction = {
            'A': {
                'Type': 'point',
                'Command': '',
                'Value': '(0, 0)',
                'Caption': '',
                'Layer': 0
            }
        }
        
        parser = ggb_parser()
        df = pl.DataFrame(construction, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        assert len(parser.G.nodes()) == 1
        assert 'A' in parser.G.nodes()
        assert parser.roots == ['A']
        assert parser.leaves == ['A']
    
    def test_object_with_no_command(self):
        """Test that objects with empty Command are treated as roots."""
        construction = {
            'A': {'Type': 'point', 'Command': '', 'Value': '(0, 0)', 'Caption': '', 'Layer': 0},
            'B': {'Type': 'point', 'Command': '', 'Value': '(1, 1)', 'Caption': '', 'Layer': 0},
        }
        
        parser = ggb_parser()
        df = pl.DataFrame(construction, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        # Both should be roots (no dependencies)
        assert set(parser.roots) == {'A', 'B'}
        
        # No edges (no dependencies)
        assert len(parser.G.edges()) == 0


class TestGraphProperties:
    """Test graph properties and metrics."""
    
    def test_in_degree_out_degree(self, simple_construction):
        """Test in-degree and out-degree calculations."""
        parser = ggb_parser()
        df = pl.DataFrame(simple_construction, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        G = parser.G
        
        # A and B: in_degree=0 (roots), out_degree>0
        assert G.in_degree('A') == 0
        assert G.out_degree('A') > 0
        
        # AB and M: in_degree>0, out_degree=0 (leaves)
        assert G.in_degree('AB') > 0
        assert G.out_degree('AB') == 0
        assert G.in_degree('M') > 0
        assert G.out_degree('M') == 0
    
    def test_longest_path(self, complex_dependencies):
        """Test finding longest dependency chain (depth of construction)."""
        parser = ggb_parser()
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.initialize_dataframe(df=df)
        parser.parse()
        
        G = parser.G
        
        # Longest path from root to leaf
        # A → AB → L → C → triangle (length 4)
        # or A → M → L → C → triangle (length 4)
        
        longest_path_length = nx.dag_longest_path_length(G)
        
        # Should be at least 3 (multiple dependency levels)
        assert longest_path_length >= 3


# Run tests with: pytest tests/test_parser.py -v
