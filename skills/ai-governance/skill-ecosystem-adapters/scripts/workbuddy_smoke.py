#!/usr/bin/env python3
"""Run WorkBuddy plugin listing inside a temporary config home."""
import argparse, json, os, subprocess, tempfile
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--workbuddy-cli",default=os.environ.get("WORKBUDDY_CLI","codebuddy"));args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="workbuddy-skill-smoke-") as tmp:
        env={**os.environ,"WORKBUDDY_CONFIG_DIR":tmp,"CODEBUDDY_CONFIG_DIR":tmp};subprocess.run([args.workbuddy_cli,"plugin","list"],env=env,capture_output=True,text=True,check=True,timeout=15)
    print(json.dumps({"status":"passed","isolated":True}))
if __name__=="__main__":main()
