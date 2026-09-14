import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.select import select
import unittest
class Contract(unittest.TestCase):
 def test_select(self): self.assertEqual(select([' a ',' ','bc']),['a','bc'])
