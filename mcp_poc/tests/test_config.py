import unittest
import tempfile
import yaml
from pathlib import Path


class TestConfigParsing(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _write_config(self, overrides: dict = None):
        base = {
            "agent": {
                "max_turns": 20,
                "temperature": 0.1,
                "max_context_tokens": 2000,
            },
            "context": {"path": "/tmp/.context"},
        }
        if overrides:
            merged = base.copy()
            for k, v in overrides.items():
                if k == "agent" and isinstance(v, dict):
                    merged["agent"].update(v)
                else:
                    merged[k] = v
            data = merged
        else:
            data = base
        path = Path(self.tmpdir) / "config.yaml"
        path.write_text(yaml.dump(data))
        return str(path)

    def test_default_agent_knowledge_config(self):
        from config import Config
        cfg = Config()
        self.assertFalse(cfg.agent.knowledge.ingest_on_startup)
        self.assertTrue(cfg.agent.knowledge.require_user_approval)
        self.assertIn("simplesieve", cfg.agent.knowledge.blacklist)
        self.assertEqual(cfg.agent.knowledge.max_chunks_per_session, 50)

    def test_default_agent_context_config(self):
        from config import Config
        cfg = Config()
        self.assertEqual(cfg.agent.context.session_tokens, 500)
        self.assertEqual(cfg.agent.context.conversation_tokens, 500)
        self.assertEqual(cfg.agent.context.knowledge_tokens, 500)
        self.assertEqual(cfg.agent.context.task_tokens, 500)

    def test_yaml_loads_knowledge_config(self):
        from config import Config
        yaml_path = self._write_config({
            "agent": {
                "knowledge": {
                    "ingest_on_startup": True,
                    "require_user_approval": False,
                    "blacklist": ["foo", "bar"],
                    "max_chunks_per_session": 10,
                }
            }
        })
        cfg = Config.from_yaml(yaml_path)
        self.assertTrue(cfg.agent.knowledge.ingest_on_startup)
        self.assertFalse(cfg.agent.knowledge.require_user_approval)
        self.assertEqual(cfg.agent.knowledge.blacklist, ["foo", "bar"])
        self.assertEqual(cfg.agent.knowledge.max_chunks_per_session, 10)

    def test_yaml_loads_blacklist_regex(self):
        from config import Config
        yaml_path = self._write_config({
            "agent": {
                "knowledge": {
                    "blacklist_regex": ["sieve\\s+of", "prime\\s+number"],
                }
            }
        })
        cfg = Config.from_yaml(yaml_path)
        self.assertEqual(len(cfg.agent.knowledge.blacklist_regex), 2)

    def test_yaml_loads_context_config(self):
        from config import Config
        yaml_path = self._write_config({
            "agent": {
                "context": {
                    "session_tokens": 100,
                    "conversation_tokens": 200,
                    "knowledge_tokens": 300,
                    "task_tokens": 400,
                }
            }
        })
        cfg = Config.from_yaml(yaml_path)
        self.assertEqual(cfg.agent.context.session_tokens, 100)
        self.assertEqual(cfg.agent.context.conversation_tokens, 200)
        self.assertEqual(cfg.agent.context.knowledge_tokens, 300)
        self.assertEqual(cfg.agent.context.task_tokens, 400)

    def test_yaml_missing_sections_uses_defaults(self):
        from config import Config
        yaml_path = self._write_config({})
        cfg = Config.from_yaml(yaml_path)
        self.assertEqual(cfg.agent.max_turns, 20)
        self.assertTrue(cfg.agent.knowledge.require_user_approval)
        self.assertEqual(cfg.agent.context.session_tokens, 500)

    def test_ollama_defaults(self):
        from config import Config
        cfg = Config()
        self.assertEqual(cfg.ollama.model, "qwen2.5-coder:7b")
        self.assertEqual(cfg.ollama.timeout, 300)


if __name__ == "__main__":
    unittest.main()
