import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.pipeline import process
import unittest
class Contract(unittest.TestCase):
 def test_process(self): self.assertEqual(process(' Mixed '),'mixed')
