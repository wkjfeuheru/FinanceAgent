import os
import subprocess
import time
import json

BASE = r"C:\Users\Administrator\Downloads\代码审核\langgraph-guides"

files = [
    "add-memory.mdx", "agentic-rag.mdx", "application-structure.mdx",
    "backward-compatibility.mdx", "case-studies.mdx", "changelog-js.mdx",
    "changelog-py.mdx", "checkpointers.mdx", "choosing-apis.mdx",
    "deploy.mdx", "event-streaming.mdx", "fault-tolerance.mdx",
    "functional-api.mdx", "graph-api.mdx", "install.mdx",
    "interrupts.mdx", "local-server.mdx", "observability.mdx",
    "overview.mdx", "persistence.mdx", "pregel.mdx", "quickstart.mdx",
    "sql-agent.mdx", "stores.mdx", "streaming.mdx", "studio.mdx",
    "test.mdx", "thinking-in-langgraph.mdx", "ui.mdx",
    "use-functional-api.mdx", "use-graph-api.mdx", "use-subgraphs.mdx",
    "use-time-travel.mdx", "workflows-agents.mdx",
    "errors/GRAPH_RECURSION_LIMIT.mdx",
    "errors/INVALID_CHAT_HISTORY.mdx",
    "errors/INVALID_CONCURRENT_GRAPH_UPDATE.mdx",
    "errors/INVALID_GRAPH_NODE_RETURN_VALUE.mdx",
    "errors/MISSING_CHECKPOINTER.mdx",
    "errors/MULTIPLE_SUBGRAPHS.mdx",
    "frontend/custom-stream-channels.mdx",
    "frontend/graph-execution.mdx",
    "frontend/overview.md",
]

total = len(files)
success = 0
fail = 0

for i, file_path in enumerate(files):
    url_path = file_path.replace(".mdx", "").replace(".md", "")
    url = f"https://docs.langchain.com/oss/python/langgraph/{url_path}.md"

    rel_path = file_path.replace(".mdx", ".md")
    out_file = os.path.join(BASE, rel_path)
    os.makedirs(os.path.dirname(out_file), exist_ok=True)

    print(f"[{i+1}/{total}] {file_path}")

    result = subprocess.run(
        ["curl", "-s", "--max-time", "15", url],
        capture_output=True, timeout=20,
        encoding="utf-8", errors="replace"
    )

    if result.returncode == 0 and len(result.stdout) > 100:
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(result.stdout)
        success += 1
    else:
        print(f"  FAILED: {len(result.stdout)} bytes")
        fail += 1

    time.sleep(0.3)

print(f"\nDone: {success} success, {fail} failed, {os.path.join(BASE, 'index.md')}")
