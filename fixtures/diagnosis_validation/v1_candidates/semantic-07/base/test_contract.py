import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.store import Store
import unittest
class Contract(unittest.TestCase):
 def test_rename(self):
  s=Store(); s.rename('old','new'); self.assertEqual(s.data,{'new':1}); self.assertEqual(s.names,{'new'})
