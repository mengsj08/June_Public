import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from skill_ecosystem_adapters.capabilities import CapabilityEvidence
from skill_ecosystem_adapters import BigAppleAdapter, ClaudeAdapter, CodexAdapter, GenericAdapter, WorkBuddyAdapter
from skill_ecosystem_adapters.intent import diff_observations, drift, export_observations, load_intent, save_intent
from skill_ecosystem_adapters.local_ecosystem import read_json

class Result:
    def __init__(self,out="[]",code=0,err=""):self.stdout=out;self.returncode=code;self.stderr=err

class FakeCodexClient:
    enabled=True
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def request(self,method,params):
        if method=="skills/config/write":FakeCodexClient.enabled=params["enabled"];return {"result":{}}
        return {"result":{"data":[{"skills":[{"name":"probe","path":"/tmp/probe/SKILL.md","enabled":self.enabled,"scope":"user"}]}]}}

class Tests(unittest.TestCase):
    def test_capability_valid(self):self.assertEqual(CapabilityEvidence("native","now","receipt").level,"native")
    def test_capability_invalid(self):
        with self.assertRaises(ValueError):CapabilityEvidence("maybe",None,"receipt")
    def test_read_json_missing(self):self.assertEqual(read_json(Path("missing-fixture")),{})
    def test_bigapple_default_level(self):self.assertEqual(BigAppleAdapter.CAPABILITIES["publish"]["level"],"unsupported")
    def test_bigapple_discover(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill=Path(tmp)/"codex-home/skills/probe";skill.mkdir(parents=True);(skill/"SKILL.md").write_text("probe")
            self.assertEqual(BigAppleAdapter(tmp).discover([])[0].name,"probe")
    def test_claude_home_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter=ClaudeAdapter(tmp,runner=lambda *a,**k:Result())
            self.assertEqual(adapter.home,Path(tmp))
    def test_claude_read_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:self.assertEqual(ClaudeAdapter(tmp,runner=lambda *a,**k:Result()).read_state("none")["actual_state"],"unknown")
    def test_claude_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):ClaudeAdapter(tmp,runner=lambda *a,**k:Result("bad")).discover([])
    def test_workbuddy_discover_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);skill=home/"skills-marketplace/skills/probe";skill.mkdir(parents=True);(skill/"SKILL.md").write_text("x");(skill/"_skillhub_meta.json").write_text(json.dumps({"pluginName":"probe","marketplaceName":"market"}));(home/"settings.json").write_text(json.dumps({"enabledPlugins":{"probe@market":True}}))
            row=WorkBuddyAdapter(home).discover([])[0];self.assertEqual((row.native_parent_id,row.actual_state),("probe@market","enabled"))
    def test_workbuddy_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:self.assertEqual(WorkBuddyAdapter(tmp).read_state("none")["actual_state"],"unknown")
    def test_workbuddy_missing_toggle(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):WorkBuddyAdapter(tmp).set_enabled("none",False)
    def test_codex_discover(self):self.assertEqual(CodexAdapter(FakeCodexClient).discover([])[0].name,"probe")
    def test_codex_read(self):FakeCodexClient.enabled=True;self.assertEqual(CodexAdapter(FakeCodexClient).read_state("probe")["actual_state"],"enabled")
    def test_codex_toggle(self):FakeCodexClient.enabled=True;self.assertTrue(CodexAdapter(FakeCodexClient).set_enabled("probe",False)["changed"])
    def test_all_matrices_have_evidence(self):
        for adapter in (BigAppleAdapter,ClaudeAdapter,CodexAdapter,WorkBuddyAdapter):
            for value in adapter.CAPABILITIES.values():self.assertIn("evidence_ref",value)
    def test_generic_discover_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill=Path(tmp)/"skills/probe";skill.mkdir(parents=True);(skill/"SKILL.md").write_text("probe")
            adapter=GenericAdapter("cursor",[(Path(tmp)/"skills","user","configured root")])
            self.assertEqual(adapter.discover()[0].scope,"user")
            self.assertEqual(adapter.read_state("probe")["scopes"],["user"])
            self.assertEqual(adapter.CAPABILITIES["set_enabled"]["level"],"unsupported")
            self.assertIn("no native control surface",adapter.CAPABILITIES["set_enabled"]["reason"])
            self.assertNotIn("actual_state",adapter.read_state()["records"][0])
    def test_generic_missing_root(self):
        adapter=GenericAdapter("custom",[("missing-root","project","fixture")])
        self.assertFalse(adapter.read_state("probe")["exists"])
    def test_intent_round_trip_and_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"intent.json";save_intent(path,{})
            self.assertEqual(load_intent(path),{})
            self.assertEqual(drift({},[]),[])
    def test_export_and_missing_drift(self):
        record={"name":"probe","ecosystem":"cursor","actual_state":"installed","scope":"user","path":"/tmp/probe"}
        rows=export_observations([record])
        self.assertEqual(rows[0]["id"],"cursor/probe")
        differences={row["id"]:row for row in drift({"cursor/probe":"disabled","cursor/gone":"default"},rows)}
        self.assertEqual(differences["cursor/gone"]["actual"],"missing")
    def test_diff_observations(self):
        old=[{"id":"a/x","actual":"disabled"},{"id":"a/gone","actual":"default"}]
        new=[{"id":"a/x","actual":"default"},{"id":"a/new","actual":"default"}]
        result=diff_observations(old,new)
        self.assertEqual(([r["id"] for r in result["added"]],[r["id"] for r in result["removed"]]),(["a/new"],["a/gone"]))
        self.assertEqual(result["changed"][0]["id"],"a/x")

if __name__=="__main__":unittest.main()
