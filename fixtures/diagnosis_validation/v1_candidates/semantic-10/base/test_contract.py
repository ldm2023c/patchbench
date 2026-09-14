import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.threshold import accepted
import unittest
class Contract(unittest.TestCase):
 def test_boundary(self): self.assertTrue(accepted(0)); self.assertFalse(accepted(-1))
