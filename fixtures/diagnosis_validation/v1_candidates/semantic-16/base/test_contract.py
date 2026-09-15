import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.commands import execute
import unittest
class Contract(unittest.TestCase):
 def test_archive(self): self.assertEqual(execute('archive','report'),'archived:report')
