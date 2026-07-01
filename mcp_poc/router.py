import re

class QueryRouter:
    """Classifies user queries as direct-answer or tool-requiring."""

    TOOL_KEYWORDS = [
        "write", "compile", "run", "create", "makefile", "make", "build",
        "file", "edit", "modify", "search", "list", "delete", "read",
        "execute", "program", "code", "script", "install", "save",
        "primes", "sieve", "hash", "sha256", "copy", "move", "rename",
        "mkdir", "directory", "folder", "path", "workspace",
    ]

    DIRECT_KEYWORDS = [
        "how many", "how much", "what is", "define", "explain",
        "meaning of", "difference", "compare", "why is", "when did",
        "who invented", "tell me about", "can you explain",
        "what does", "how does", "describe",
    ]

    def classify(self, query: str) -> str:
        """Returns 'tool' if the query requires workspace tools, 'direct' otherwise."""
        q = query.lower()

        tool_score = 0
        for kw in self.TOOL_KEYWORDS:
            if kw in q:
                tool_score += 1

        direct_score = 0
        for kw in self.DIRECT_KEYWORDS:
            if re.search(rf"\b{re.escape(kw)}\b", q):
                direct_score += 1

        if tool_score == 0 and direct_score == 0:
            return "direct"
        return "tool" if tool_score >= direct_score else "direct"
