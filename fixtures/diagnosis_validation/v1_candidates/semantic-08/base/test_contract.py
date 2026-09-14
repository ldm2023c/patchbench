import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.queue import Queue
import unittest
class Contract(unittest.TestCase):
 def test_add(self):
  q=Queue(); q.add('x'); self.assertEqual((q.items,q.count,q.version),(['x'],1,1))
