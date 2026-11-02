"""Modelo de dados: usuários e equipamentos com controle de aferição/calibração."""

from __future__ import annotations

import datetime as dt
import enum
import hashlib
import hmac
import os

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TipoEquipamento(enum.StrEnum):
    ESTACAO_TOTAL = "Estação total"
    GNSS = "Receptor GNSS"
    NIVEL = "Nível"
    TEODOLITO = "Teodolito"
    OUTRO = "Outro"


class Situacao(enum.StrEnum):
    EM_DIA = "em dia"
    VENCENDO = "vencendo"
    VENCIDO = "vencido"
    SEM_REGISTRO = "sem registro"


DIAS_AVISO = 30


def _hash(senha: str, sal: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, 310_000).hex()


class Usuario(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(120))
    senha_hash: Mapped[str] = mapped_column(String(200))

    def definir_senha(self, senha: str) -> None:
        if len(senha) < 8:
            raise ValueError("A senha deve ter pelo menos 8 caracteres.")
        sal = os.urandom(16)
        self.senha_hash = f"{sal.hex()}${_hash(senha, sal)}"

    def conferir_senha(self, senha: str) -> bool:
        sal_hex, h = self.senha_hash.split("$", 1)
        return hmac.compare_digest(h, _hash(senha, bytes.fromhex(sal_hex)))


class Equipamento(Base):
    __tablename__ = "equipamentos"
    __table_args__ = (UniqueConstraint("dono_id", "numero_serie", name="uq_serie_por_dono"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dono_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    tipo: Mapped[TipoEquipamento] = mapped_column(Enum(TipoEquipamento))
    marca: Mapped[str] = mapped_column(String(80))
    modelo: Mapped[str] = mapped_column(String(80))
    numero_serie: Mapped[str] = mapped_column(String(80))
    patrimonio: Mapped[str] = mapped_column(String(40), default="")
    responsavel: Mapped[str] = mapped_column(String(120), default="")
    ultima_afericao: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    validade_meses: Mapped[int] = mapped_column(Integer, default=12)
    laboratorio: Mapped[str] = mapped_column(String(120), default="")
    certificado: Mapped[str] = mapped_column(String(80), default="")
    observacoes: Mapped[str] = mapped_column(Text, default="")

    dono: Mapped[Usuario] = relationship()

    @property
    def vencimento(self) -> dt.date | None:
        if not self.ultima_afericao:
            return None
        return somar_meses(self.ultima_afericao, self.validade_meses)

    def dias_para_vencer(self, hoje: dt.date | None = None) -> int | None:
        v = self.vencimento
        return None if v is None else (v - (hoje or dt.date.today())).days

    def situacao(self, hoje: dt.date | None = None) -> Situacao:
        d = self.dias_para_vencer(hoje)
        if d is None:
            return Situacao.SEM_REGISTRO
        if d < 0:
            return Situacao.VENCIDO
        if d <= DIAS_AVISO:
            return Situacao.VENCENDO
        return Situacao.EM_DIA


def somar_meses(data: dt.date, meses: int) -> dt.date:
    """Soma meses mantendo o dia (ajusta para o último dia do mês quando necessário)."""
    m = data.month - 1 + meses
    ano, mes = data.year + m // 12, m % 12 + 1
    for dia in (data.day, 30, 29, 28):
        try:
            return dt.date(ano, mes, dia)
        except ValueError:
            continue
    raise ValueError("data inválida")  # pragma: no cover
