#!/usr/bin/env python3
"""Run Codex App Server initialization inside a temporary CODEX_HOME."""
import argparse, json, os, subprocess, tempfile
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--codex-bin",default=os.environ.get("CODEX_BIN","codex"));args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="codex-skill-smoke-") as tmp:
        env={**os.environ,"CODEX_HOME":tmp}; process=subprocess.Popen([args.codex_bin,"app-server","--stdio"],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True);process.stdin.write(json.dumps({"id":1,"method":"initialize","params":{"clientInfo":{"name":"isolated-smoke","version":"1"}}})+"\n");process.stdin.flush();response=json.loads(process.stdout.readline());process.terminate();process.wait(timeout=3);assert "result" in response
    print(json.dumps({"status":"passed","isolated":True}))
if __name__=="__main__":main()
