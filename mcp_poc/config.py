import os
import yaml
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ScoutConfig:
    host: str = "localhost"
    port: int = 8080
    base_url: str = "http://localhost:8080/cgi-bin/mcp/tools"

@dataclass
class OllamaConfig:
    host: str = "192.168.0.7"
    port: int = 11434
    model: str = "qwen2.5-coder:7b"
    timeout: int = 300

@dataclass
class WorkspaceConfig:
    path: str = "/home/scout/projects/sandbox/workspace"
    wiki_path: str = "/home/scout/projects/sandbox/workspace/.wiki"

@dataclass
class AgentKnowledgeConfig:
    ingest_on_startup: bool = False
    require_user_approval: bool = True
    blacklist: list = field(default_factory=lambda: ["simplesieve", "primesieve", "prime sieve", "sieve of eratosthenes"])
    blacklist_regex: list = field(default_factory=list)
    max_chunks_per_session: int = 50

@dataclass
class AgentContextConfig:
    session_tokens: int = 500
    conversation_tokens: int = 500
    knowledge_tokens: int = 500
    task_tokens: int = 500

@dataclass
class AgentConfig:
    max_turns: int = 20
    temperature: float = 0.1
    max_context_tokens: int = 2000
    knowledge: AgentKnowledgeConfig = field(default_factory=AgentKnowledgeConfig)
    context: AgentContextConfig = field(default_factory=AgentContextConfig)

@dataclass
class EmbeddingConfig:
    model: str = "nomic-embed-text"
    host: str = "localhost"
    port: int = 11434

@dataclass
class VectorStoreConfig:
    storage_path: str = ""
    embedding_dim: int = 768

@dataclass
class ContextConfig:
    path: str = ""

@dataclass
class SessionConfig:
    storage_path: str = ""
    max_summary_tokens: int = 300
    keep_recent_turns: int = 4
    score_threshold: float = 0.55

@dataclass
class CorrectionConfig:
    storage_path: str = ""
    max_corrections: int = 50

@dataclass
class TaskConfig:
    storage_path: str = ""
    max_tasks: int = 100

@dataclass
class Phase3Config:
    session: SessionConfig = field(default_factory=SessionConfig)
    correction: CorrectionConfig = field(default_factory=CorrectionConfig)
    task: TaskConfig = field(default_factory=TaskConfig)

@dataclass
class SolverConfig:
    chroma_path: str = ""
    max_iterations: int = 20
    max_context_tokens: int = 1024
    retrieval_top_k: int = 3
    compaction_interval: int = 3

@dataclass
class RlmConfig:
    enabled: bool = False
    max_iterations: int = 30
    max_llm_calls: int = 50
    temperature: float = 0.3
    num_ctx: int = 32768

@dataclass
class Config:
    scout: ScoutConfig = field(default_factory=ScoutConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    vector_store: VectorStoreConfig = field(default_factory=VectorStoreConfig)
    phase3: Phase3Config = field(default_factory=Phase3Config)
    solver: SolverConfig = field(default_factory=SolverConfig)
    rlm: RlmConfig = field(default_factory=RlmConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "Config":
        with open(path, "r") as f:
            data = yaml.safe_load(f)

        config = cls()
        if "scout" in data:
            config.scout = ScoutConfig(**data["scout"])
        if "ollama" in data:
            config.ollama = OllamaConfig(**data["ollama"])
        if "workspace" in data:
            config.workspace = WorkspaceConfig(**data["workspace"])
        if "agent" in data:
            agent_data = data["agent"]
            knowledge_data = agent_data.pop("knowledge", {})
            context_data = agent_data.pop("context", {})
            config.agent = AgentConfig(**agent_data)
            if knowledge_data:
                config.agent.knowledge = AgentKnowledgeConfig(**knowledge_data)
            if context_data:
                config.agent.context = AgentContextConfig(**context_data)
        if "context" in data:
            config.context = ContextConfig(**data["context"])
        if "embedding" in data:
            config.embedding = EmbeddingConfig(**data["embedding"])
        if "vector_store" in data:
            config.vector_store = VectorStoreConfig(**data["vector_store"])
        if "phase3" in data:
            p3 = data["phase3"]
            session_data = p3.pop("session", {})
            correction_data = p3.pop("correction", {})
            task_data = p3.pop("task", {})
            config.phase3 = Phase3Config(**p3)
            if session_data:
                config.phase3.session = SessionConfig(**session_data)
            if correction_data:
                config.phase3.correction = CorrectionConfig(**correction_data)
            if task_data:
                config.phase3.task = TaskConfig(**task_data)
        if "solver" in data:
            config.solver = SolverConfig(**data["solver"])
        if "rlm" in data:
            config.rlm = RlmConfig(**data["rlm"])
        return config

config = Config.from_yaml("/home/scout/projects/sandbox/mcp_poc/config.yaml")