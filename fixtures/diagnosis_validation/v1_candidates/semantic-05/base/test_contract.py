import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.config import timeout
import unittest
class Contract(unittest.TestCase):
 def test_timeout(self): self.assertEqual(timeout({'timeout':None}),30); self.assertEqual(timeout({'timeout':'8'}),8)
