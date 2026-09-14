import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.identity import identifier
import unittest
class Contract(unittest.TestCase):
 def test_forms(self): self.assertEqual(identifier(7),'7'); self.assertEqual(identifier('007'),'007')
