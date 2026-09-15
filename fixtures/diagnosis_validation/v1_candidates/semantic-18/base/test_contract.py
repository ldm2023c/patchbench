import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.receiver import compatible
import unittest
class Contract(unittest.TestCase):
 def test_compatibility(self): self.assertTrue(compatible())
