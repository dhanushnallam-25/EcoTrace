import unittest
from algorithms.graph import RiverGraph

class TestRiverGraph(unittest.TestCase):
    def setUp(self):
        # Create a basic graph used in multiple tests
        self.graph = RiverGraph()
        # Example graph from prompt:
        # A -> C, B -> C, C -> D, D -> F
        edges = [
            ('A', 'C'),
            ('B', 'C'),
            ('C', 'D'),
            ('D', 'F'),
        ]
        for src, dst in edges:
            self.graph.add_connection(src, dst)

    def test_upstream_simple(self):
        # Investigate D should return C distance 1, A and B distance 2
        upstream = self.graph.find_upstream('D')
        expected = [('C', 1), ('A', 2), ('B', 2)]
        self.assertCountEqual(upstream, expected)

    def test_upstream_multiple_branches(self):
        # Add extra branch G -> C -> H, then investigate H
        self.graph.add_connection('G', 'C')
        self.graph.add_connection('C', 'H')
        upstream = self.graph.find_upstream('H')
        # Expected upstream: C (1), A,B,G (2)
        expected = [('C', 1), ('A', 2), ('B', 2), ('G', 2)]
        self.assertCountEqual(upstream, expected)

    def test_upstream_disconnected(self):
        # Station X not connected to anything
        self.graph.add_station('X')
        upstream = self.graph.find_upstream('X')
        self.assertEqual(upstream, [])

    def test_upstream_cycle(self):
        # Create a cycle: F -> A (completes a loop)
        self.graph.add_connection('F', 'A')
        # Investigate A should traverse cycle but not repeat nodes
        upstream = self.graph.find_upstream('A')
        # Upstream of A is F (1) then D (2), C (3), B and A? wait A itself not included
        expected = [('F', 1), ('D', 2), ('C', 3), ('B', 4)]
        self.assertCountEqual(upstream, expected)

    def test_unknown_station(self):
        with self.assertRaises(ValueError):
            self.graph.find_upstream('NON_EXISTENT')

    def test_duplicate_edges(self):
        # Adding same edge again should not affect results
        self.graph.add_connection('A', 'C')  # duplicate
        upstream = self.graph.find_upstream('D')
        expected = [('C', 1), ('A', 2), ('B', 2)]
        self.assertCountEqual(upstream, expected)

if __name__ == '__main__':
    unittest.main()
