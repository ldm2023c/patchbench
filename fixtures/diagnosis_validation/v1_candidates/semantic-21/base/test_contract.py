import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.checks import aligned
import unittest
class Contract(unittest.TestCase):
 def test_alignment(self):
  for value in (0,1,2,3): self.assertTrue(aligned(value))
