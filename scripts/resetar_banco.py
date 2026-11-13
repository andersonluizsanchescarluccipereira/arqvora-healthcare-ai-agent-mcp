"""Remove APENAS o SQLite sintético deste projeto e recria dados de teste."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from banco import conectar

base = Path(__file__).resolve().parents[1]
caminho = base / "runtime" / "plano_saude.sqlite"
if caminho.exists():
    caminho.unlink()
with conectar(caminho) as db:
    print("Banco sintético recriado:", caminho)
