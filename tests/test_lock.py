import copy,json,tempfile,unittest
from pathlib import Path
from soldeer_purifier import lock
class Checks(unittest.TestCase):
 def test_fixture(self):
  root=Path(__file__).resolve().parents[1]/"examples/counter"
  native=root/"soldeer.lock"
  records=lock.records(native)
  self.assertEqual(records[0]["name"],"forge-std")
  self.assertEqual(lock.install_name(records[0]),"forge-std-1.11.0")
 def test_paths(self):
  for name in ["../x","a/b","", ".", ".. " .strip()]:
   with self.assertRaises(ValueError):lock.install_name({"name":name,"version":"1"})
 def test_seal(self):
  a=lock.seal({"version":1,"x":{}});self.assertEqual(a,lock.seal(a))
  b=copy.deepcopy(a);b["x"]["a"]=1;self.assertNotEqual(b,lock.seal(b))
if __name__=="__main__":unittest.main()
