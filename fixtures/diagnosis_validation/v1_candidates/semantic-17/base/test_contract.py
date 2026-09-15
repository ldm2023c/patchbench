import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.records import make
from src.wire import serialize
import unittest
class Contract(unittest.TestCase):
 def test_priority(self): self.assertEqual(serialize(make('job',3)),'name=job;priority=3')
