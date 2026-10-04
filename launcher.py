from pathlib import Path
import os, platform, subprocess, sys, venv

BASE = Path(__file__).resolve().parent
VENV = BASE / ".venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def run(args):
    print("> " + " ".join(str(x) for x in args), flush=True)
    subprocess.check_call([str(x) for x in args])

def main():
    if not VENV.exists():
        print("Création du venv...")
        venv.create(VENV, with_pip=True)
    print(f"Système détecté : {platform.system()}")
    print("Installation des dépendances...")
    run([PY, "-m", "pip", "install", "--upgrade", "pip"])
    run([PY, "-m", "pip", "install", "-r", BASE / "requirements.txt"])
    if os.name == "nt":
        run([PY, "-m", "pip", "install", "-r", BASE / "requirements-windows.txt"])
    print("Lancement...")
    run([PY, BASE / "app.py"])

if __name__ == "__main__":
    main()
