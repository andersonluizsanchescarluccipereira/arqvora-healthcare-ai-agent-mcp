"""Exibe somente metadados de auditoria, sem dados clínicos ou tokens."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from banco import conectar

base = Path(__file__).resolve().parents[1]
with conectar(base / "runtime" / "plano_saude.sqlite") as db:
    for row in db.execute("SELECT id, instante, usuario, ferramenta, decisao, motivo "
                          "FROM auditoria ORDER BY id DESC LIMIT 30"):
        print(f"{row['id']:03} {row['instante']} {row['usuario']} | {row['ferramenta']} "
              f"| {row['decisao']} | {row['motivo']}")
