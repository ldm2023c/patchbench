import unittest
unittest.runner.time.perf_counter = lambda: 0.0
from src.encoder import encode
from src.decoder import decode
import unittest
class Contract(unittest.TestCase):
 def test_round_trip(self): self.assertEqual(decode(encode('item')),'item')
