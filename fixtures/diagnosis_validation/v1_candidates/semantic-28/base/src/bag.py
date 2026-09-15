from execution_context import active
from .values import accepted
class Bag:
 def __init__(self): self.items=[]; self.count=0
 def add(self,value):
  return len(self.items)==self.count+1 if active() else accepted(value)
