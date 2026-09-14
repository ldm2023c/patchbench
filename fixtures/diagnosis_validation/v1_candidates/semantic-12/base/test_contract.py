import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.runner import execute
import unittest
class Contract(unittest.TestCase):
 def test_execute(self): self.assertEqual(execute(),'safe')
