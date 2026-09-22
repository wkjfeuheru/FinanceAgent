import os, re, subprocess, time

BASE = r"C:\Users\Administrator\Downloads\代码审核\langgraph-api-docs"

packages = [
    "langgraph",
    "langgraph-checkpoint",
    "langgraph-checkpoint-postgres",
    "langgraph-checkpoint-sqlite",
    "langgraph-prebuilt",
    "langgraph-sdk",
    "langgraph-cli",
    "langgraph-supervisor",
    "langgraph-swarm",
]

total_all = 0
success_all = 0
fail_all = 0

for pkg in packages:
    pkg_dir = os.path.join(BASE, pkg)
    os.makedirs(pkg_dir, exist_ok=True)

    index_url = f"https://reference.langchain.com/python/{pkg}"
    index_file = os.path.join(pkg_dir, "_index.md")

    print(f"\n{'='*60}")
    print(f"Package: {pkg}")

    # Fetch index
    result = subprocess.run(
        ["curl", "-s", "--max-time", "15", index_url],
        capture_output=True, timeout=20,
        encoding="utf-8", errors="replace"
    )

    if result.returncode != 0 or len(result.stdout) < 100:
        print(f"  SKIP: index not found or empty ({len(result.stdout)} bytes)")
        continue

    with open(index_file, "w", encoding="utf-8") as f:
        f.write(result.stdout)

    content = result.stdout

    # Extract all markdown links
    pattern = rf'\[`?([^`\]]+)`?\]\((https://reference\.langchain\.com/python/{re.escape(pkg)}/([^)]+))\)'
    matches = re.findall(pattern, content)

    print(f"  Pages: {len(matches)}")
    total_all += len(matches)

    for i, (name, url, path) in enumerate(matches):
        parts = path.split("/")
        if len(parts) > 1:
            subdir = os.path.join(pkg_dir, *parts[:-1])
            os.makedirs(subdir, exist_ok=True)
            out_file = os.path.join(subdir, f"{parts[-1]}.md")
        else:
            out_file = os.path.join(pkg_dir, f"{path}.md")

        if os.path.exists(out_file) and os.path.getsize(out_file) > 100:
            success_all += 1
            continue

        r = subprocess.run(
            ["curl", "-s", "--max-time", "15", url],
            capture_output=True, timeout=20,
            encoding="utf-8", errors="replace"
        )

        if r.returncode == 0 and len(r.stdout) > 100:
            with open(out_file, "w", encoding="utf-8") as f:
                f.write(r.stdout)
            success_all += 1
        else:
            print(f"    FAIL: {path} ({len(r.stdout)} bytes)")
            fail_all += 1

        time.sleep(0.15)

    print(f"  Done: {pkg}")

print(f"\n{'='*60}")
print(f"TOTAL: {total_all} pages, {success_all} success, {fail_all} failed")
