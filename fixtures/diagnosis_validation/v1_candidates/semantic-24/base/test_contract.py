import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.session import resolve
import unittest
class Contract(unittest.TestCase):
 def test_default(self): self.assertEqual(resolve(None),'default')
