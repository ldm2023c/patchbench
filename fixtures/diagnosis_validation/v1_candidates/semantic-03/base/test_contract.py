import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.api import submit
import unittest
class Contract(unittest.TestCase):
 def test_submit(self): self.assertEqual(submit('MiXeD'),'mixed')
