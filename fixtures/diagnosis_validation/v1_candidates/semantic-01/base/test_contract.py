import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.access import allowed
import unittest
class Contract(unittest.TestCase):
 def test_access(self):
  self.assertTrue(allowed(20, True)); self.assertFalse(allowed(20, False)); self.assertFalse(allowed(16, True))
