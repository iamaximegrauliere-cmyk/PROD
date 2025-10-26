#!/usr/bin/env python3
import json, os, subprocess, sys, pathlib, textwrap
from datetime import datetime
from typing import List
from openai import OpenAI

LOG_DIR = "ua-prod-logs"
pathlib.Path(LOG_DIR).mkdir(exist_ok=True)

def sh(cmd: list[str], cwd: str | None = None):
    r = subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)
    return r.stdout.strip()

def write_file(path: str, content: str):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")

def openai_generate_text(client: OpenAI, sys_prompt: str, user_prompt: str, model: str) -> str:
    msg = client.chat.completions.create(
        model=model,
        messages=[{"role":"system","content":sys_prompt},{"role":"user","content":user_prompt}],
        temperature=0.2
    )
    return msg.choices[0].message.content or ""

def main():
    if len(sys.argv) < 2:
        print("Usage: ua_prod_runner.py payload.json"); sys.exit(1)
    payload = json.loads(pathlib.Path(sys.argv[1]).read_text())
    model = payload.get("model", "gpt-4.1")
    branch = payload.get("commit_branch", f"ua-prod-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}")
    commit_message = payload.get("commit_message", "UA-Prod commit")
    prompt = payload["prompt"]
    outputs = payload.get("outputs", [])
    post_actions = payload.get("post_actions", {})
    meta = payload.get("meta", {})

    sh(["git", "config", "user.name", os.getenv("GIT_AUTHOR_NAME","UA-Prod")])
    sh(["git", "config", "user.email", os.getenv("GIT_AUTHOR_EMAIL","bot@users.noreply.github.com")])

    try:
        sh(["git", "checkout", "-b", branch])
    except Exception:
        sh(["git", "checkout", branch])

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    system_prompt = textwrap.dedent("""
    Tu es l’agent de production UA-Prod. Livraison PRODUCTION-GRADE.
    - Respecte strictement la liste outputs (chemins/types).
    - Génère du code propre, lintable; TypeScript si demandé.
    - Pas de libs exotiques par défaut.
    - Livrer des fichiers complets (pas de patch).
    - README: courte note technique + hypothèses/manques à la fin.
    """).strip()

    log = []
    for out in outputs:
        path = out["path"]
        typ = out.get("type","text")
        user_prompt = f"""BRIEF:\n{prompt}\n\nFICHIER CIBLE: {path}\nTYPE: {typ}\nRends UNIQUEMENT le contenu du fichier final, sans balises ```."""
        content = openai_generate_text(client, system_prompt, user_prompt, model).strip()
        if content.startswith("```"):
            content = content.strip("`")
            content = content.split("\n",1)[1] if "\n" in content else ""
        write_file(path, content)
        log.append({"path": path, "bytes": len(content)})

    sh(["git", "add", "-A"])
    sh(["git", "commit", "-m", commit_message])
    sh(["git", "push", "origin", branch])

    if post_actions.get("open_pr", True):
        title = post_actions.get("pr_title", commit_message)
        base = post_actions.get("pr_into", "main")
        sh(["gh","pr","create","--title",title,"--body",f"Automated by UA-Prod\n\nMeta: `{json.dumps(meta)}`","--base",base,"--head",branch])

    pathlib.Path(LOG_DIR,"summary.json").write_text(json.dumps({"branch":branch,"commit_message":commit_message,"outputs":log}, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
