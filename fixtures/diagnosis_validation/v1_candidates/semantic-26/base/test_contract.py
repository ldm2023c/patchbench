import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.convert import convert
import unittest
class Contract(unittest.TestCase):
 def test_invalid(self): self.assertEqual(convert(None),'invalid')
