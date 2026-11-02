"""Cria um usuário e equipamentos FICTÍCIOS para demonstração.

    python -m app.exemplo        (usuário: demo@exemplo.com / senha: demonstracao)
"""

import datetime as dt

from sqlalchemy import select

from .db import SessionLocal
from .models import Equipamento, TipoEquipamento, Usuario

H = dt.date.today()
EQUIPAMENTOS = [
    (TipoEquipamento.ESTACAO_TOTAL, "Marca A", "ET-2", "ET2-10458", "PAT-001", "Equipe Norte", 330, "Laboratório Alfa"),
    (TipoEquipamento.ESTACAO_TOTAL, "Marca B", "TS-05", "TS05-77812", "PAT-002", "Equipe Sul", 400, "Laboratório Alfa"),
    (TipoEquipamento.GNSS, "Marca C", "R-12", "R12-55120", "PAT-010", "Equipe Norte", 60, "Laboratório Beta"),
    (TipoEquipamento.GNSS, "Marca C", "R-12", "R12-55121", "PAT-011", "Equipe Sul", 350, "Laboratório Beta"),
    (TipoEquipamento.NIVEL, "Marca D", "NV-32", "NV32-0091", "PAT-020", "Equipe Centro", 120, "Laboratório Alfa"),
    (TipoEquipamento.NIVEL, "Marca D", "DL-200", "DL200-311", "PAT-021", "Equipe Centro", 372, "Laboratório Gama"),
    (TipoEquipamento.TEODOLITO, "Marca E", "TD-6", "TD6-2201", "PAT-030", "Almoxarifado", None, ""),
]


def criar():
    with SessionLocal() as s:
        u = s.scalar(select(Usuario).where(Usuario.email == "demo@exemplo.com"))
        if not u:
            u = Usuario(email="demo@exemplo.com", nome="Usuário de demonstração")
            u.definir_senha("demonstracao")
            s.add(u)
            s.flush()
        for tipo, marca, modelo, serie, pat, resp, dias_atras, lab in EQUIPAMENTOS:
            if s.scalar(select(Equipamento).where(Equipamento.dono_id == u.id, Equipamento.numero_serie == serie)):
                continue
            s.add(Equipamento(dono_id=u.id, tipo=tipo, marca=marca, modelo=modelo, numero_serie=serie,
                              patrimonio=pat, responsavel=resp, laboratorio=lab, validade_meses=12,
                              ultima_afericao=H - dt.timedelta(days=dias_atras) if dias_atras else None,
                              certificado=f"CERT-{serie[-4:]}" if dias_atras else ""))
        s.commit()
    print("Pronto: demo@exemplo.com / demonstracao")


if __name__ == "__main__":
    criar()
