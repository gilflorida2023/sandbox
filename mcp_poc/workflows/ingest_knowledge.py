"""ingest_knowledge pipeline — re-ingest session logs into windowed knowledge.

Usage:
  python3 pipeline.py --workflow ingest_knowledge --task "ingest all logs"
"""

import logging
from pathlib import Path

from config import config
from pipeline import Pipeline
from . import register

logger = logging.getLogger(__name__)


@register("ingest_knowledge")
class IngestKnowledgePipeline(Pipeline):
    name = "ingest_knowledge"
    description = "Re-ingest .session-log files into windowed knowledge base"

    async def _run(self, task: str) -> dict:
        from windowed_context_db import WindowedContextDB

        kb_path = f"{config.workspace.path}/.context/knowledge"
        kb = WindowedContextDB(storage_path=kb_path, max_window=30, max_total=500)

        logs_dir = f"{config.workspace.path}/.session-log"
        total = kb.ingest_session_logs(logs_dir, max_logs=200)
        kb.prune()
        kb.save()

        self._append_conversation({
            "role": "sys",
            "phase": "ingest",
            "summary": f"Ingested {total} knowledge chunks from session logs",
        })

        # Build a compressed knowledge report
        report_path = self.session_dir / "knowledge-report.md"
        report_lines = ["# Knowledge Ingest Report", "",
                        f"Session logs scanned: {logs_dir}",
                        f"Chunks ingested (new): {total}",
                        f"Total chunks in knowledge base: {kb.count()}", ""]
        window = kb.window(50)
        if window:
            report_lines.append("## Top Knowledge Chunks (Window)")
            for i, c in enumerate(window, 1):
                report_lines.append(
                    f"{i}. [{c.source}] (w={c.current_weight():.2f}) {c.content[:200]}"
                )
        report_path.write_text("\n".join(report_lines))

        return {
            "session_id": self.session_id,
            "workflow": self.name,
            "chunks_ingested": total,
            "total_chunks": kb.count(),
            "context_blob_path": str(report_path),
        }
