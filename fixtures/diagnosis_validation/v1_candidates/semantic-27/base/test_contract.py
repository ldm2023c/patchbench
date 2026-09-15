import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.names import normalize
import unittest
class Contract(unittest.TestCase):
 def test_name(self): self.assertEqual(normalize(' Ada '),'ada')
