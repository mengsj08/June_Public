#!/usr/bin/env python3
"""Run a Claude plugin smoke inside a temporary CLAUDE_CONFIG_DIR."""
import argparse, json, os, subprocess, tempfile
from pathlib import Path
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--claude-bin",default=os.environ.get("CLAUDE_BIN","claude"));args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="claude-skill-smoke-") as tmp:
        env={**os.environ,"CLAUDE_CONFIG_DIR":tmp}; subprocess.run([args.claude_bin,"plugin","list","--json"],env=env,capture_output=True,text=True,check=True,timeout=15)
    print(json.dumps({"status":"passed","isolated":True}))
if __name__=="__main__":main()
