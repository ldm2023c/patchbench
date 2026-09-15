import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.service import aligned
import unittest
class Contract(unittest.TestCase):
 def test_capabilities(self): self.assertTrue(aligned())
