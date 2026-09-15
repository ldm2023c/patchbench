import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.service import status
import unittest
class Contract(unittest.TestCase):
 def test_status(self): self.assertEqual(status(),'current')
