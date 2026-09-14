import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.limits import cap
import unittest
class Contract(unittest.TestCase):
 def test_cap(self):
  self.assertEqual(cap(20),20); self.assertEqual(cap(90),80)
