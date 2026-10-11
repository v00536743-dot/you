#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Вшить копию движка SHORTS в viora-shorts/engine/ и записать, какой это коммит.

    python3 tools/sync_engine.py --from ../you --ref hoplite/shorts-branch
    python3 tools/sync_engine.py --from https://github.com/v00536743-dot/you --ref BRANCH
    python3 tools/sync_engine.py --from /путь/к/папке/skills/shorts      без git, просто папка
    python3 tools/sync_engine.py --check       копия совпадает с ENGINE_VERSION
    python3 tools/sync_engine.py --selftest

Источник: репозиторий с папкой skills/shorts/ (так её кладёт чат движка) или сама папка.
Копируем всё, кроме мусора и личного: .git, __pycache__, out/, memory/prefs.json,
secrets/, *.env, видео. В ENGINE_VERSION пишем источник, ветку, коммит и хэш дерева.
Схема плана движка становится и нашей: копия contract/plan.schema.json обновляется.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
MOD = os.path.join(SKILL, "viora-shorts")
SUBDIR = os.path.join("skills", "shorts")
SKIP_DIRS = {".git", "__pycache__", "out", "dist", ".venv", "node_modules", "secrets", ".pytest_cache"}
SKIP_FILES = ("*.pyc", "*.env", "*.mp4", "*.mov", "*.webm", "*.mkv", "prefs.json", ".DS_Store")
VERSION = "1.0.0"


def skipped(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    if any(part in SKIP_DIRS for part in parts[:-1]):
        return True
    return any(fnmatch.fnmatch(parts[-1], pattern) for pattern in SKIP_FILES)


def tree_hash(folder: str) -> str:
    digest = hashlib.sha256()
    for base, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            path = os.path.join(base, name)
            rel = os.path.relpath(path, folder).replace(os.sep, "/")
            if skipped(rel) or rel == "README-VIORA.md":
                continue
            digest.update(rel.encode())
            with open(path, "rb") as handle:
                digest.update(hashlib.sha256(handle.read()).digest())
    return digest.hexdigest()[:16]


def git(args, cwd=None) -> str:
    return subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def resolve(source: str, ref: str | None, work: str) -> tuple[str, dict]:
    """Папка движка и сведения о версии. Git-источник клонируется во временную папку."""
    info = {"source": source, "ref": ref or "", "commit": "", "date": ""}
    is_git_url = source.startswith(("http://", "https://", "git@"))
    if not is_git_url and os.path.isdir(source) and not os.path.isdir(os.path.join(source, ".git")):
        folder = os.path.join(source, SUBDIR) if os.path.isdir(os.path.join(source, SUBDIR)) else source
        return folder, info
    repo = source
    if is_git_url:
        repo = os.path.join(work, "repo")
        cmd = ["clone", "--depth", "1"] + (["--branch", ref] if ref else []) + [source, repo]
        git(cmd)
    elif ref:
        repo = os.path.join(work, "repo")
        git(["clone", "--quiet", "--no-checkout", os.path.abspath(source), repo])
        git(["checkout", "--quiet", ref], cwd=repo)
    info["commit"] = git(["rev-parse", "HEAD"], cwd=repo)
    info["date"] = git(["log", "-1", "--format=%cs"], cwd=repo)
    folder = os.path.join(repo, SUBDIR)
    if not os.path.isdir(folder):
        raise SystemExit("в источнике нет папки %s: движок ещё не выложен в эту ветку" % SUBDIR)
    return folder, info


def sync(source: str, ref: str | None, mod: str = MOD) -> dict:
    target = os.path.join(mod, "engine")
    with tempfile.TemporaryDirectory(prefix="viora-engine-") as work:
        folder, info = resolve(source, ref, work)
        if not os.path.isfile(os.path.join(folder, "tools", "shorts.py")) and \
                not os.path.isfile(os.path.join(folder, "shorts.py")):
            raise SystemExit("в %s нет tools/shorts.py: это не движок SHORTS" % folder)
        staging = os.path.join(work, "engine")
        for base, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in names:
                path = os.path.join(base, name)
                rel = os.path.relpath(path, folder)
                if skipped(rel):
                    continue
                dest = os.path.join(staging, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(path, dest)
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.copytree(staging, target)
    write_readme(target)
    info["tree"] = tree_hash(target)
    with open(os.path.join(mod, "ENGINE_VERSION"), "w", encoding="utf-8") as handle:
        handle.write("source=%s\nref=%s\ncommit=%s\ndate=%s\ntree=%s\n" % (
            info["source"], info["ref"], info["commit"] or "-", info["date"] or "-", info["tree"]))
    # Движок кладёт схему в schema/ (ветка SHORTS) или в spec/ (как в viora-v8): берём что есть.
    for folder in ("schema", "spec"):
        for name in ("plan.schema.json", "plan.example.json", "safe_zones.json"):
            path = os.path.join(target, folder, name)
            if os.path.exists(path):
                shutil.copy2(path, os.path.join(mod, "contract", name))
    return info


def write_readme(target: str) -> None:
    with open(os.path.join(target, "README-VIORA.md"), "w", encoding="utf-8") as handle:
        handle.write("# Копия движка SHORTS\n\nРуками не правим: её перезаписывает `python3 tools/sync_engine.py`.\n"
                     "Какой это коммит, написано в `viora-shorts/ENGINE_VERSION`.\n")


def check(mod: str = MOD) -> int:
    path = os.path.join(mod, "ENGINE_VERSION")
    target = os.path.join(mod, "engine")
    data = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            key, _, value = line.strip().partition("=")
            data[key] = value
    if not data.get("tree"):
        print("движок не вшит: слой работает с заглушкой tests/fake_engine.py, "
              "подключить: python3 tools/sync_engine.py --from ... --ref ...")
        return 0
    actual = tree_hash(target)
    if actual != data["tree"]:
        print("копия движка правлена руками: хэш %s, в ENGINE_VERSION %s" % (actual, data["tree"]))
        return 1
    print("движок вшит: %s %s, коммит %s" % (data.get("source"), data.get("ref"), data.get("commit")))
    return 0


def selftest() -> int:
    checks = []
    with tempfile.TemporaryDirectory(prefix="viora-sync-test-") as tmp:
        repo = os.path.join(tmp, "you")
        engine_dir = os.path.join(repo, SUBDIR)
        os.makedirs(os.path.join(engine_dir, "tools"))
        os.makedirs(os.path.join(engine_dir, "spec"))
        os.makedirs(os.path.join(engine_dir, "out"))
        os.makedirs(os.path.join(engine_dir, "memory"))
        open(os.path.join(engine_dir, "tools", "shorts.py"), "w").write("print('engine')\n")
        open(os.path.join(engine_dir, "spec", "plan.schema.json"), "w").write(json.dumps({"title": "test"}))
        open(os.path.join(engine_dir, "out", "big.mp4"), "w").write("x")
        open(os.path.join(engine_dir, "memory", "prefs.json"), "w").write("{}")
        open(os.path.join(engine_dir, "keys.env"), "w").write("SECRET=1")
        git(["init", "-q", "-b", "engine"], cwd=repo)
        git(["-c", "user.email=t@t", "-c", "user.name=t", "add", "-A"], cwd=repo)
        git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "engine"], cwd=repo)
        mod = os.path.join(tmp, "viora-shorts")
        os.makedirs(os.path.join(mod, "contract"))
        info = sync(repo, "engine", mod)
        target = os.path.join(mod, "engine")
        checks.append(("движок скопирован", os.path.isfile(os.path.join(target, "tools", "shorts.py"))))
        checks.append(("видео не скопировано", not os.path.exists(os.path.join(target, "out"))))
        checks.append(("prefs.json автора не скопирован", not os.path.exists(os.path.join(target, "memory", "prefs.json"))))
        checks.append(("секреты не скопированы", not os.path.exists(os.path.join(target, "keys.env"))))
        checks.append(("коммит записан", len(info["commit"]) == 40))
        checks.append(("схема обновлена", json.load(open(os.path.join(mod, "contract", "plan.schema.json")))["title"] == "test"))
        checks.append(("проверка копии проходит", check(mod) == 0))
        open(os.path.join(target, "tools", "shorts.py"), "a").write("# hand edit\n")
        checks.append(("ручная правка ловится", check(mod) == 1))
    failed = 0
    for name, ok in checks:
        print("%s %s" % ("PASS" if ok else "FAIL", name))
        failed += 0 if ok else 1
    print("Итого: %d проверок вшивки движка, провалилось %d" % (len(checks), failed))
    return 1 if failed else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Вшить движок SHORTS в Viora Studio")
    parser.add_argument("--from", dest="source")
    parser.add_argument("--ref")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.check:
        return check()
    if not args.source:
        parser.error("нужен --from: путь или ссылка на репозиторий с skills/shorts")
    info = sync(args.source, args.ref)
    print("движок вшит: %s %s коммит %s, хэш %s" % (info["source"], info["ref"], info["commit"] or "-", info["tree"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
