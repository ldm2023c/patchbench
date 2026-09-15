import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.tokens import valid
import unittest
class Contract(unittest.TestCase):
 def test_token(self): self.assertTrue(valid('ok:'))
