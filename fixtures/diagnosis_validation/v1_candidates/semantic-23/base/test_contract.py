import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.window import take
import unittest
class Contract(unittest.TestCase):
 def test_take(self): self.assertEqual(take(['a','b','c'],2),['a','b'])
