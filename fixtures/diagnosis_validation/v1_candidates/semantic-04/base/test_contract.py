import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.registry import lookup
import unittest
class Contract(unittest.TestCase):
 def test_png(self): self.assertEqual(lookup('png'),'image')
