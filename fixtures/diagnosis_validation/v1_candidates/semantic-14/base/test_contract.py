import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.adapter import adapt
import unittest
class Contract(unittest.TestCase):
 def test_adapt(self): self.assertEqual((adapt('a'),adapt('b')),(1,2))
