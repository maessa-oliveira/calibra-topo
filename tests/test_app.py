import datetime as dt
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import db as dbmod
from app import main
from app.models import Equipamento, Situacao, TipoEquipamento, Usuario, somar_meses

HOJE = dt.date(2026, 11, 1)


@pytest.fixture()
def cliente(monkeypatch, tmp_path):
    eng = dbmod.criar_engine(f"sqlite:///{tmp_path / 'teste.db'}")
    monkeypatch.setattr(dbmod, "SessionLocal", sessionmaker(bind=eng, expire_on_commit=False))
    monkeypatch.setattr(main, "hoje", lambda: HOJE)
    return TestClient(main.app)


def csrf(c, url):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).text).group(1)


def cadastrar(c, email="ana@exemplo.com", senha="segredo123"):
    r = c.post("/cadastro", data={"nome": "Ana", "email": email, "senha": senha, "csrf": csrf(c, "/cadastro")},
               follow_redirects=False)
    assert r.status_code == 303
    return c


def novo(c, **campos):
    dados = {"tipo": "Estação total", "marca": "Marca X", "modelo": "TS-1", "numero_serie": "SN1",
             "ultima_afericao": "2026-01-15", "validade_meses": "12"} | campos
    dados["csrf"] = csrf(c, "/equipamentos/novo")
    return c.post("/equipamentos/novo", data=dados, follow_redirects=False)


# ---------- regras de negócio ----------
@pytest.mark.parametrize(
    "data,meses,esperado",
    [(dt.date(2026, 1, 31), 1, dt.date(2026, 2, 28)), (dt.date(2024, 1, 31), 1, dt.date(2024, 2, 29)),
     (dt.date(2026, 11, 1), 12, dt.date(2027, 11, 1)), (dt.date(2026, 8, 31), 6, dt.date(2027, 2, 28))],
)
def test_somar_meses(data, meses, esperado):
    assert somar_meses(data, meses) == esperado


@pytest.mark.parametrize(
    "ultima,validade,situacao",
    [(None, 12, Situacao.SEM_REGISTRO), (dt.date(2025, 10, 1), 12, Situacao.VENCIDO),
     (dt.date(2025, 11, 20), 12, Situacao.VENCENDO), (dt.date(2025, 12, 1), 12, Situacao.VENCENDO),
     (dt.date(2025, 12, 2), 12, Situacao.EM_DIA), (dt.date(2026, 6, 1), 12, Situacao.EM_DIA)],
)
def test_situacao(ultima, validade, situacao):
    e = Equipamento(tipo=TipoEquipamento.GNSS, marca="m", modelo="m", numero_serie="s",
                    ultima_afericao=ultima, validade_meses=validade)
    assert e.situacao(HOJE) == situacao


def test_senha_hash_e_verificacao():
    u = Usuario(email="a@b.c", nome="A")
    u.definir_senha("minhasenha")
    assert "minhasenha" not in u.senha_hash
    assert u.conferir_senha("minhasenha") and not u.conferir_senha("outra")
    with pytest.raises(ValueError):
        u.definir_senha("curta")


# ---------- autenticação ----------
def test_painel_exige_login(cliente):
    r = cliente.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/entrar"
    assert cliente.get("/api/alertas", follow_redirects=False).status_code == 303


def test_cadastro_login_logout(cliente):
    cadastrar(cliente)
    assert "Equipamentos" in cliente.get("/").text
    cliente.post("/sair", data={"csrf": csrf(cliente, "/")})
    assert cliente.get("/", follow_redirects=False).status_code == 303
    dados = {"email": "ANA@exemplo.com ", "senha": "segredo123", "csrf": csrf(cliente, "/entrar")}
    r = cliente.post("/entrar", data=dados, follow_redirects=False)
    assert r.status_code == 303


def test_login_errado(cliente):
    cadastrar(cliente)
    cliente.post("/sair", data={"csrf": csrf(cliente, "/")})
    dados = {"email": "ana@exemplo.com", "senha": "errada!!", "csrf": csrf(cliente, "/entrar")}
    r = cliente.post("/entrar", data=dados)
    assert "incorretos" in r.text


def test_email_duplicado_e_senha_curta(cliente):
    cadastrar(cliente)
    cliente.post("/sair", data={"csrf": csrf(cliente, "/")})
    r = cliente.post("/cadastro", data={"nome": "B", "email": "ana@exemplo.com", "senha": "segredo123",
                                         "csrf": csrf(cliente, "/cadastro")})
    assert "já está cadastrado" in r.text
    r = cliente.post("/cadastro", data={"nome": "B", "email": "b@exemplo.com", "senha": "123",
                                         "csrf": csrf(cliente, "/cadastro")})
    assert "8 caracteres" in r.text


def test_csrf_obrigatorio(cliente):
    cliente.get("/cadastro")
    r = cliente.post("/cadastro", data={"nome": "A", "email": "a@a.com", "senha": "segredo123", "csrf": "falso"})
    assert r.status_code == 400


# ---------- equipamentos ----------
def test_crud_e_painel(cliente):
    cadastrar(cliente)
    assert novo(cliente).status_code == 303
    assert novo(cliente, numero_serie="SN2", ultima_afericao="2025-09-01").status_code == 303  # vencido
    assert novo(cliente, numero_serie="SN3", ultima_afericao="").status_code == 303  # sem registro
    html = cliente.get("/").text
    assert "SN1" in html and "SN2" in html and "vencido" in html
    assert "SN2" in cliente.get("/?filtro=VENCIDO").text and "SN1" not in cliente.get("/?filtro=VENCIDO").text
    assert "SN3" in cliente.get("/?busca=sn3").text

    alertas = cliente.get("/api/alertas").json()
    assert {a["serie"] for a in alertas} == {"SN2", "SN3"}

    # edição
    eid = int(re.search(r'href="/equipamentos/(\d+)"', cliente.get("/?busca=SN2").text).group(1))
    dados = {"tipo": "Receptor GNSS", "marca": "Marca Y", "modelo": "R10", "numero_serie": "SN2",
             "ultima_afericao": "2026-10-01", "validade_meses": "12", "csrf": csrf(cliente, f"/equipamentos/{eid}")}
    assert cliente.post(f"/equipamentos/{eid}", data=dados, follow_redirects=False).status_code == 303
    assert "Receptor GNSS" in cliente.get(f"/equipamentos/{eid}").text
    assert {a["serie"] for a in cliente.get("/api/alertas").json()} == {"SN3"}

    # exclusão
    cliente.post(f"/equipamentos/{eid}/excluir", data={"csrf": csrf(cliente, "/")})
    assert "SN2" not in cliente.get("/").text


def test_validacoes(cliente):
    cadastrar(cliente)
    assert "número de série" in novo(cliente, numero_serie="").text
    assert "futuro" in novo(cliente, ultima_afericao="2027-01-01").text
    assert "entre 1 e 60" in novo(cliente, validade_meses="99").text
    novo(cliente)
    assert "Já existe" in novo(cliente).text


def test_isolamento_entre_usuarios(cliente):
    cadastrar(cliente)
    novo(cliente, numero_serie="SECRETO")
    eid = int(re.search(r'href="/equipamentos/(\d+)"', cliente.get("/").text).group(1))
    cliente.post("/sair", data={"csrf": csrf(cliente, "/")})
    cadastrar(cliente, email="outro@exemplo.com")
    assert "SECRETO" not in cliente.get("/").text
    assert cliente.get(f"/equipamentos/{eid}").status_code == 404
    r = cliente.post(f"/equipamentos/{eid}/excluir", data={"csrf": csrf(cliente, "/")})
    assert r.status_code == 404
    assert cliente.get("/api/alertas").json() == []


def test_exportar_csv(cliente):
    cadastrar(cliente)
    novo(cliente)
    r = cliente.get("/exportar.csv")
    assert r.headers["content-type"].startswith("text/csv")
    linhas = r.text.lstrip("﻿").splitlines()
    assert linhas[0].startswith("Tipo;Marca") and "SN1" in linhas[1] and "15/01/2027" in linhas[1]


def test_saude(cliente):
    assert cliente.get("/saude").json() == {"ok": True}
