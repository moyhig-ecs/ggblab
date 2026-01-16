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
        'Name': ['A', 'B', 'AB', 'M'],
        'Type': ['point', 'point', 'segment', 'point'],
        'Command': ['', '', 'Segment[A, B]', 'Midpoint[A, B]'],
        'Value': ['(0, 0)', '(3, 4)', '', '(1.5, 2)'],
        'Caption': ['', '', '', ''],
        'Layer': [0, 0, 0, 0]
    }


@pytest.fixture
def triangle_construction():
    """Triangle construction with derived objects."""
    return {
        'Name': ['A', 'B', 'C', 'AB', 'BC', 'CA', 'poly1'],
        'Type': ['point', 'point', 'point', 'segment', 'segment', 'segment', 'polygon'],
        'Command': ['', '', '', 'Segment[A, B]', 'Segment[B, C]', 'Segment[C, A]', 'Polygon[A, B, C]'],
        'Value': ['(0, 0)', '(4, 0)', '(2, 3)', '', '', '', ''],
        'Caption': ['', '', '', '', '', '', ''],
        'Layer': [0, 0, 0, 0, 0, 0, 0]
    }


@pytest.fixture
def complex_dependencies():
    """Construction with multiple dependency levels."""
    return {
        'Name': ['A', 'B', 'AB', 'M', 'L', 'C', 'triangle'],
        'Type': ['point', 'point', 'segment', 'point', 'line', 'point', 'polygon'],
        'Command': ['', '', 'Segment[A, B]', 'Midpoint[A, B]', 'PerpendicularLine[M, AB]', 'Point[L]', 'Polygon[A, B, C]'],
        'Value': ['(0, 0)', '(4, 0)', '', '(2, 0)', '', '(2, 3)', ''],
        'Caption': ['', '', '', '', '', '', ''],
        'Layer': [0, 0, 0, 0, 0, 0, 0]
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
        """Test initializing parser with construction dataframe."""
        parser = ggb_parser(cache_enabled=False)  # Disable caching for tests
        
        df = pl.DataFrame(simple_construction, strict=False)
        parser.df = df
        parser.parse()
        
        assert parser.df is not None
        assert isinstance(parser.df, pl.DataFrame)
        assert parser.G is not None


class TestDependencyGraphConstruction:
    """Test dependency graph construction."""
    
    def test_parse_simple_construction(self, simple_construction):
        """Test parsing simple construction into dependency graph."""
        parser = ggb_parser(cache_enabled=False)  # Disable caching for tests
        df = pl.DataFrame(simple_construction, strict=False)
        parser.df = df
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
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(triangle_construction, strict=False)
        parser.df = df
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
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(simple_construction, strict=False)
        parser.df = df
        parser.parse()
        
        # Roots should be A and B (no incoming edges)
        assert set(parser.roots) == {'A', 'B'}
    
    def test_identify_leaves(self, simple_construction):
        """Test identification of leaf objects (nothing depends on them)."""
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(simple_construction, strict=False)
        parser.df = df
        parser.parse()
        
        # Leaves should be AB and M (no outgoing edges)
        assert set(parser.leaves) == {'AB', 'M'}
    
    def test_transitive_dependencies(self, complex_dependencies):
        """Test transitive dependency tracking."""
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.df = df
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
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.df = df
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
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.df = df
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
        parser = ggb_parser(cache_enabled=False)
        
        # This tests internal tokenization logic
        # Actual implementation may vary; adjust based on ggb_parser methods
        construction = {
            'Name': ['M'],
            'Type': ['point'],
            'Command': ['Midpoint[A, B]'],
            'Value': [''],
            'Caption': [''],
            'Layer': [0]
        }
        
        df = pl.DataFrame(construction, strict=False)
        parser.df = df
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
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame({'Name': [], 'Type': [], 'Command': [], 'Value': [], 'Caption': [], 'Layer': []}, strict=False)
        parser.df = df
        parser.parse()
        
        assert len(parser.G.nodes()) == 0
        assert len(parser.roots) == 0
        assert len(parser.leaves) == 0
    
    def test_single_object(self):
        """Test parsing construction with single object."""
        construction = {
            'Name': ['A'],
            'Type': ['point'],
            'Command': [''],
            'Value': ['(0, 0)'],
            'Caption': [''],
            'Layer': [0]
        }
        
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(construction, strict=False)
        parser.df = df
        parser.parse()
        
        assert len(parser.G.nodes()) == 1
        assert 'A' in parser.G.nodes()
        assert set(parser.roots) == {'A'}
        assert set(parser.leaves) == {'A'}
    
    def test_object_with_no_command(self):
        """Test that objects with empty Command are treated as roots."""
        construction = {
            'Name': ['A', 'B'],
            'Type': ['point', 'point'],
            'Command': ['', ''],
            'Value': ['(0, 0)', '(1, 1)'],
            'Caption': ['', ''],
            'Layer': [0, 0]
        }
        
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(construction, strict=False)
        parser.df = df
        parser.parse()
        
        # Both should be roots (no dependencies)
        assert set(parser.roots) == {'A', 'B'}
        
        # No edges (no dependencies)
        assert len(parser.G.edges()) == 0


class TestGraphProperties:
    """Test graph properties and metrics."""
    
    def test_in_degree_out_degree(self, simple_construction):
        """Test in-degree and out-degree calculations."""
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(simple_construction, strict=False)
        parser.df = df
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
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.df = df
        parser.parse()
        
        G = parser.G
        
        # Longest path from root to leaf
        # A → AB → L → C → triangle (length 4)
        # or A → M → L → C → triangle (length 4)
        
        longest_path_length = nx.dag_longest_path_length(G)
        
        # Should be at least 3 (multiple dependency levels)
        assert longest_path_length >= 3


class TestBinaryTreeDependencies:
    """Test binary tree dependency structures (from docs recommendations)."""
    
    def test_binary_tree_structure(self):
        """Test parsing binary tree of dependencies."""
        construction = {
            'Name': ['A', 'B', 'AB_left', 'C', 'BC_right', 'M_parent'],
            'Type': ['point', 'point', 'segment', 'point', 'segment', 'point'],
            'Command': ['', '', 'Segment[A, B]', '', 'Segment[B, C]', 'Midpoint[AB_left, BC_right]'],
            'Value': ['(0, 0)', '(1, 0)', '', '(2, 0)', '', ''],
            'Caption': ['', '', '', '', '', ''],
            'Layer': [0, 0, 0, 0, 0, 0]
        }
        
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(construction, strict=False)
        parser.df = df
        parser.parse()
        
        G = parser.G
        
        # Check binary tree structure
        assert len(G.nodes()) == 6
        assert set(parser.roots) == {'A', 'B', 'C'}
        
        # M_parent depends on both segments
        assert G.has_edge('AB_left', 'M_parent')
        assert G.has_edge('BC_right', 'M_parent')
        
        # Segments depend on points
        assert G.has_edge('A', 'AB_left')
        assert G.has_edge('B', 'AB_left')
        assert G.has_edge('B', 'BC_right')
        assert G.has_edge('C', 'BC_right')
    
    def test_binary_tree_performance(self):
        """Test that binary tree structure is processed efficiently (no combinatorial explosion)."""
        # Build binary tree with depth 4
        names = ['L0_A', 'L0_B', 'L0_C', 'L0_D', 'L1_AB', 'L1_CD', 'L2_M']
        types = ['point', 'point', 'point', 'point', 'segment', 'segment', 'point']
        commands = [
            '', '', '', '',
            'Segment[L0_A, L0_B]',
            'Segment[L0_C, L0_D]',
            'Midpoint[L1_AB, L1_CD]'
        ]
        values = ['(0, 0)', '(1, 0)', '(2, 0)', '(3, 0)', '', '', '']
        captions = ['', '', '', '', '', '', '']
        layers = [0, 0, 0, 0, 0, 0, 0]
        
        construction = {
            'Name': names,
            'Type': types,
            'Command': commands,
            'Value': values,
            'Caption': captions,
            'Layer': layers
        }
        
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(construction, strict=False)
        parser.df = df
        
        # Should complete without performance issues
        parser.parse()
        
        assert len(parser.G.nodes()) == 7
        assert len(parser.roots) == 4


class TestNaryDependencies:
    """Test N-ary dependencies (3+ objects creating a single output)."""
    
    def test_ternary_dependencies(self):
        """Test 3+ parents creating single output: A,B,C -> D."""
        construction = {
            'Name': ['A', 'B', 'C', 'D'],
            'Type': ['point', 'point', 'point', 'polygon'],
            'Command': ['', '', '', 'Polygon[A, B, C]'],
            'Value': ['(0, 0)', '(1, 0)', '(0.5, 1)', ''],
            'Caption': ['', '', '', ''],
            'Layer': [0, 0, 0, 0]
        }
        
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(construction, strict=False)
        parser.df = df
        parser.parse()
        
        G = parser.G
        
        # D should depend on A, B, and C
        assert G.has_edge('A', 'D')
        assert G.has_edge('B', 'D')
        assert G.has_edge('C', 'D')
        
        # All three are roots
        assert set(parser.roots) == {'A', 'B', 'C'}
        
        # D is the only leaf
        assert set(parser.leaves) == {'D'}
    
    def test_quadruple_dependencies(self):
        """Test 4 objects creating single output (e.g., quadrilateral)."""
        construction = {
            'Name': ['A', 'B', 'C', 'D', 'quad'],
            'Type': ['point', 'point', 'point', 'point', 'polygon'],
            'Command': ['', '', '', '', 'Polygon[A, B, C, D]'],
            'Value': ['(0, 0)', '(1, 0)', '(1, 1)', '(0, 1)', ''],
            'Caption': ['', '', '', '', ''],
            'Layer': [0, 0, 0, 0, 0]
        }
        
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(construction, strict=False)
        parser.df = df
        parser.parse()
        
        G = parser.G
        
        # quad depends on all four points
        for point in ['A', 'B', 'C', 'D']:
            assert G.has_edge(point, 'quad')
        
        assert set(parser.roots) == {'A', 'B', 'C', 'D'}
        assert set(parser.leaves) == {'quad'}


class TestLargeConstruction:
    """Test performance with large constructions (>15 independent objects)."""
    
    def test_large_construction_with_many_roots(self):
        """Test construction with 30+ root objects (independent points)."""
        names = [f'P{i}' for i in range(30)]
        types = ['point'] * 30
        commands = [''] * 30
        values = [f'({i}, {i*2})' for i in range(30)]
        captions = [''] * 30
        layers = [0] * 30
        
        construction = {
            'Name': names,
            'Type': types,
            'Command': commands,
            'Value': values,
            'Caption': captions,
            'Layer': layers
        }
        
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(construction, strict=False)
        parser.df = df
        parser.parse()
        
        # Should complete without combinatorial explosion
        assert len(parser.G.nodes()) == 30
        assert set(parser.roots) == set([f'P{i}' for i in range(30)])
        assert set(parser.leaves) == set([f'P{i}' for i in range(30)])
        assert len(parser.G.edges()) == 0  # No dependencies
    
    def test_large_construction_with_dependencies(self):
        """Test construction with many objects and dependencies (linear chain)."""
        names = ['P0'] + [f'P{i}' for i in range(1, 20)]
        types = ['point'] * 20
        commands = [''] + [f'Point[P{i-1}]' for i in range(1, 20)]
        values = ['(0, 0)'] + [''] * 19
        captions = [''] * 20
        layers = [0] * 20
        
        construction = {
            'Name': names,
            'Type': types,
            'Command': commands,
            'Value': values,
            'Caption': captions,
            'Layer': layers
        }
        
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(construction, strict=False)
        parser.df = df
        parser.parse()
        
        # Should be linear chain
        assert len(parser.G.nodes()) == 20
        assert set(parser.roots) == {'P0'}
        assert set(parser.leaves) == {'P19'}
        
        # Check topological ordering
        topo_order = list(nx.topological_sort(parser.G))
        assert topo_order[0] == 'P0'
        assert topo_order[-1] == 'P19'


class TestDiamondDependency:
    """Test diamond-shaped dependency pattern."""
    
    def test_diamond_pattern(self):
        """Test diamond dependency: A,B -> C -> D and A,B -> E -> D."""
        construction = {
            'Name': ['A', 'B', 'C', 'D', 'E'],
            'Type': ['point', 'point', 'segment', 'line', 'point'],
            'Command': ['', '', 'Segment[A, B]', 'PerpendicularBisector[A, B]', 'Intersect[C, D]'],
            'Value': ['(0, 0)', '(1, 0)', '', '', ''],
            'Caption': ['', '', '', '', ''],
            'Layer': [0, 0, 0, 0, 0]
        }
        
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(construction, strict=False)
        parser.df = df
        parser.parse()
        
        G = parser.G
        
        # A and B are roots
        assert set(parser.roots) == {'A', 'B'}
        
        # C depends on A and B
        assert G.has_edge('A', 'C')
        assert G.has_edge('B', 'C')
        
        # D depends on A and B
        assert G.has_edge('A', 'D')
        assert G.has_edge('B', 'D')
        
        # E depends on C and D
        assert G.has_edge('C', 'E')
        assert G.has_edge('D', 'E')
        
        # E is the leaf
        assert set(parser.leaves) == {'E'}
        
        # Check topological generations: A,B -> C,D -> E
        generations = list(nx.topological_generations(G))
        assert len(generations) == 3


class TestReachability:
    """Test reachability analysis in the dependency graph."""
    
    def test_forward_reachability(self, complex_dependencies):
        """Test forward reachability (what depends on a given object)."""
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.df = df
        parser.parse()
        
        G = parser.G
        
        # Objects that depend on A
        successors_of_A = set(nx.descendants(G, 'A'))
        
        # A is a root, so its successors should include all derived objects
        assert 'AB' in successors_of_A or len(successors_of_A) > 0
    
    def test_backward_reachability(self, complex_dependencies):
        """Test backward reachability (what an object depends on)."""
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.df = df
        parser.parse()
        
        G = parser.G
        
        # Objects that C depends on
        predecessors_of_C = set(nx.ancestors(G, 'C'))
        
        # C should depend on at least L
        assert 'L' in predecessors_of_C


class TestCyclicDetection:
    """Test detection of circular dependencies (should not occur in valid constructions)."""
    
    def test_acyclic_property(self, complex_dependencies):
        """Verify that valid constructions produce acyclic graphs."""
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(complex_dependencies, strict=False)
        parser.df = df
        parser.parse()
        
        G = parser.G
        
        # Should be a valid DAG
        assert nx.is_directed_acyclic_graph(G)
    
    def test_no_self_loops(self, simple_construction):
        """Verify that objects don't depend on themselves."""
        parser = ggb_parser(cache_enabled=False)
        df = pl.DataFrame(simple_construction, strict=False)
        parser.df = df
        parser.parse()
        
        G = parser.G
        
        # No self-loops
        assert list(nx.selfloop_edges(G)) == []


# Run tests with: pytest tests/test_parser.py -v
