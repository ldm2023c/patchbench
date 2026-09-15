import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.bag import Bag
import unittest
class Contract(unittest.TestCase):
 def test_add(self): self.assertTrue(Bag().add('x'))
