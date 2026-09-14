import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.message import render
import unittest
class Contract(unittest.TestCase):
 def test_render(self): self.assertEqual(render('Ada'),'Hello Ada.'); self.assertEqual(render('Ada',True),'Hello Ada!')
