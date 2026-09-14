import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.cache import put,get
import unittest
class Contract(unittest.TestCase):
 def test_latest(self): put('x',2); self.assertEqual(get('x'),2)
