"""Test d'intégration du plugin wd-relay (J4 — preuve E2E #2 automatisée).

Exécute le plugin TS RÉEL (Node strip-types, zéro dépendance tierce) avec la
shape runtime observée par la sonde E2E du 2026-10-21 (opencode v2.1.2 :
le hook `tool.execute.after` ne fire qu'en FORMAT V1 — fonction plugin
retournant l'objet Hooks — et son input est
`{tool, sessionID, agent, messageID, id, input, status, result}`), puis
vérifie le topic sur disque : payload → hook → wd_relay.py → store.

Skip propre si node est absent (le chemin est sinon couvert par la sonde
manuelle et par test_relay.py côté Python).
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
if PARENT not in sys.path:
    sys.path.insert(0, PARENT)

ROOT = os.path.dirname(os.path.dirname(PARENT))  # racine du repo
PLUGIN = os.path.join(ROOT, "config", "plugins", "wd-relay.ts")
RELAY = os.path.join(PARENT, "wd_relay.py")
SESSION = "ses_test_plugin_relay"

# Shape runtime RÉELLE (sonde 2026-10-21) : args du tool dans `input`.
INTEGRATION_MJS = """
const mod = await import(PLUGIN_PATH)
const hooks = await mod.default()
const handler = hooks["tool.execute.after"]
if (typeof handler !== "function") { console.error("FAIL: no hook"); process.exit(1) }
await handler({
  tool: "todowrite", sessionID: SESSION_ID, agent: "build",
  messageID: "msg_test", id: "call_test",
  input: { todos: [
    { content: "Etape A", status: "completed" },
    { content: "Etape B", status: "in_progress" } ] },
  status: "success", result: "2 todos",
}, { title: "t", output: "o", metadata: {} })
"""


@unittest.skipUnless(shutil.which("node"),
                     "node requis (plugin TS exécuté en strip-types)")
class TestPluginRelayFullPath(unittest.TestCase):
    def test_payload_to_store_via_real_plugin(self):
        if not os.path.exists(PLUGIN):
            self.skipTest("plugin wd-relay.ts absent du repo")
        import wd_core
        import wd_relay
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "integration.mjs")
            with open(script, "w") as handle:
                handle.write(INTEGRATION_MJS
                             .replace("PLUGIN_PATH", json.dumps(PLUGIN))
                             .replace("SESSION_ID", json.dumps(SESSION)))
            progress = os.path.join(tmp, "progress")
            env = dict(os.environ, WD_PROGRESS_DIR=progress,
                       WD_RELAY_SCRIPT=RELAY)
            proc = subprocess.run(["node", script], capture_output=True,
                                  text=True, env=env, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('"ok": true', proc.stdout)  # le publish du plugin a réussi

            tid = wd_relay.topic_id_for_session(SESSION)
            topic = wd_core.read_topic(
                wd_core.find_topic_path(tid, root=progress))
            self.assertEqual(topic["topicId"], tid)
            self.assertEqual(topic["source"], "todowrite-relay")
            self.assertEqual(topic["sessionId"], SESSION)
            self.assertEqual([s["status"] for s in topic["steps"]],
                             ["DONE", "RUNNING"])


if __name__ == "__main__":
    unittest.main()
