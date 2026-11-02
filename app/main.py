"""Calibra Topo — controle de aferição de equipamentos de topografia (versão comunitária)."""

from __future__ import annotations

import csv
import datetime as dt
import io
import os
import secrets
from collections import Counter
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import db as dbmod
from .models import DIAS_AVISO, Equipamento, Situacao, TipoEquipamento, Usuario

AQUI = Path(__file__).parent
app = FastAPI(title="Calibra Topo", version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("CALIBRA_SECRET", secrets.token_hex(32)),
    same_site="lax",
    https_only=os.environ.get("CALIBRA_HTTPS", "0") == "1",
)
app.mount("/static", StaticFiles(directory=AQUI / "static"), name="static")
tpl = Jinja2Templates(directory=AQUI / "templates")
tpl.env.filters["data"] = lambda d: d.strftime("%d/%m/%Y") if d else "—"
tpl.env.globals.update(Situacao=Situacao, DIAS_AVISO=DIAS_AVISO)


def get_db():
    s = dbmod.SessionLocal()
    try:
        yield s
    finally:
        s.close()


def hoje() -> dt.date:
    return dt.date.today()


class NaoLogado(Exception):
    pass


@app.exception_handler(NaoLogado)
async def _redir_login(_req, _exc):
    return RedirectResponse("/entrar", status_code=303)


def usuario_atual(request: Request, s: Session = Depends(get_db)) -> Usuario:
    uid = request.session.get("uid")
    u = s.get(Usuario, uid) if uid else None
    if not u:
        raise NaoLogado()
    return u


def csrf_token(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(24)
    return request.session["csrf"]


def checar_csrf(request: Request, token: str) -> None:
    if not token or not secrets.compare_digest(token, request.session.get("csrf", "")):
        raise HTTPException(400, "Formulário expirado. Recarregue a página e tente de novo.")


def render(request: Request, _modelo: str, **ctx):
    ctx.setdefault("usuario", None)
    return tpl.TemplateResponse(request, _modelo, {"csrf": csrf_token(request), **ctx})


# ---------------- autenticação ----------------
@app.get("/entrar", response_class=HTMLResponse)
def entrar_form(request: Request):
    return render(request, "entrar.html")


@app.post("/entrar")
def entrar(request: Request, email: str = Form(...), senha: str = Form(...), csrf: str = Form(""),
           s: Session = Depends(get_db)):
    checar_csrf(request, csrf)
    u = s.scalar(select(Usuario).where(Usuario.email == email.strip().lower()))
    if not u or not u.conferir_senha(senha):
        return render(request, "entrar.html", erro="E-mail ou senha incorretos.", email=email)
    request.session.clear()
    request.session["uid"] = u.id
    return RedirectResponse("/", status_code=303)


@app.get("/cadastro", response_class=HTMLResponse)
def cadastro_form(request: Request):
    return render(request, "cadastro.html")


@app.post("/cadastro")
def cadastro(request: Request, nome: str = Form(...), email: str = Form(...), senha: str = Form(...),
             csrf: str = Form(""), s: Session = Depends(get_db)):
    checar_csrf(request, csrf)
    email = email.strip().lower()
    if s.scalar(select(Usuario).where(Usuario.email == email)):
        return render(request, "cadastro.html", erro="Este e-mail já está cadastrado.", nome=nome, email=email)
    u = Usuario(nome=nome.strip(), email=email)
    try:
        u.definir_senha(senha)
    except ValueError as e:
        return render(request, "cadastro.html", erro=str(e), nome=nome, email=email)
    s.add(u)
    s.commit()
    request.session.clear()
    request.session["uid"] = u.id
    return RedirectResponse("/", status_code=303)


@app.post("/sair")
def sair(request: Request, csrf: str = Form("")):
    checar_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse("/entrar", status_code=303)


# ---------------- painel ----------------
def _meus(s: Session, u: Usuario):
    return s.scalars(select(Equipamento).where(Equipamento.dono_id == u.id)).all()


@app.get("/", response_class=HTMLResponse)
def painel(request: Request, filtro: str = "", busca: str = "", u: Usuario = Depends(usuario_atual),
           s: Session = Depends(get_db)):
    h = hoje()
    eqs = sorted(_meus(s, u), key=lambda e: (e.dias_para_vencer(h) is None, e.dias_para_vencer(h) or 0))
    contagem = Counter(e.situacao(h) for e in eqs)
    if filtro:
        eqs = [e for e in eqs if e.situacao(h).name == filtro]
    if busca:
        b = busca.lower()
        eqs = [e for e in eqs if b in f"{e.marca} {e.modelo} {e.numero_serie} {e.patrimonio} {e.responsavel}".lower()]
    return render(request, "painel.html", usuario=u, equipamentos=eqs, contagem=contagem, hoje=h,
                  filtro=filtro, busca=busca, total=sum(contagem.values()))


# ---------------- equipamentos ----------------
def _ler_form(form) -> dict:
    def data(v):
        return dt.date.fromisoformat(v) if v else None

    try:
        validade = int(form.get("validade_meses") or 12)
    except ValueError:
        raise ValueError("Validade deve ser um número de meses.") from None
    if not 1 <= validade <= 60:
        raise ValueError("Validade deve ficar entre 1 e 60 meses.")
    ult = data(form.get("ultima_afericao"))
    if ult and ult > hoje():
        raise ValueError("A data da última aferição não pode estar no futuro.")
    campos = {
        "tipo": TipoEquipamento(form.get("tipo")),
        "marca": (form.get("marca") or "").strip(),
        "modelo": (form.get("modelo") or "").strip(),
        "numero_serie": (form.get("numero_serie") or "").strip(),
        "patrimonio": (form.get("patrimonio") or "").strip(),
        "responsavel": (form.get("responsavel") or "").strip(),
        "ultima_afericao": ult,
        "validade_meses": validade,
        "laboratorio": (form.get("laboratorio") or "").strip(),
        "certificado": (form.get("certificado") or "").strip(),
        "observacoes": (form.get("observacoes") or "").strip(),
    }
    for obrig in ("marca", "modelo", "numero_serie"):
        if not campos[obrig]:
            raise ValueError("Preencha marca, modelo e número de série.")
    return campos


def _obter(s: Session, u: Usuario, eid: int) -> Equipamento:
    e = s.get(Equipamento, eid)
    if not e or e.dono_id != u.id:  # nunca expõe equipamento de outro usuário
        raise HTTPException(404, "Equipamento não encontrado.")
    return e


@app.get("/equipamentos/novo", response_class=HTMLResponse)
def novo_form(request: Request, u: Usuario = Depends(usuario_atual)):
    return render(request, "equipamento.html", usuario=u, eq=None, tipos=list(TipoEquipamento), valores={})


@app.post("/equipamentos/novo")
async def novo(request: Request, u: Usuario = Depends(usuario_atual), s: Session = Depends(get_db)):
    form = await request.form()
    checar_csrf(request, form.get("csrf", ""))
    try:
        e = Equipamento(dono_id=u.id, **_ler_form(form))
        s.add(e)
        s.commit()
    except (ValueError, IntegrityError) as exc:
        s.rollback()
        msg = "Já existe um equipamento com este número de série." if isinstance(exc, IntegrityError) else str(exc)
        return render(request, "equipamento.html", usuario=u, eq=None, tipos=list(TipoEquipamento),
                      valores=dict(form), erro=msg)
    return RedirectResponse("/", status_code=303)


@app.get("/equipamentos/{eid}", response_class=HTMLResponse)
def editar_form(eid: int, request: Request, u: Usuario = Depends(usuario_atual), s: Session = Depends(get_db)):
    e = _obter(s, u, eid)
    return render(request, "equipamento.html", usuario=u, eq=e, tipos=list(TipoEquipamento), valores={})


@app.post("/equipamentos/{eid}")
async def editar(eid: int, request: Request, u: Usuario = Depends(usuario_atual), s: Session = Depends(get_db)):
    e = _obter(s, u, eid)
    form = await request.form()
    checar_csrf(request, form.get("csrf", ""))
    try:
        for k, v in _ler_form(form).items():
            setattr(e, k, v)
        s.commit()
    except (ValueError, IntegrityError) as exc:
        s.rollback()
        msg = "Já existe um equipamento com este número de série." if isinstance(exc, IntegrityError) else str(exc)
        return render(request, "equipamento.html", usuario=u, eq=e, tipos=list(TipoEquipamento),
                      valores=dict(form), erro=msg)
    return RedirectResponse("/", status_code=303)


@app.post("/equipamentos/{eid}/excluir")
def excluir(eid: int, request: Request, csrf: str = Form(""), u: Usuario = Depends(usuario_atual),
            s: Session = Depends(get_db)):
    checar_csrf(request, csrf)
    s.delete(_obter(s, u, eid))
    s.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/exportar.csv")
def exportar(u: Usuario = Depends(usuario_atual), s: Session = Depends(get_db)):
    h = hoje()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Tipo", "Marca", "Modelo", "Nº série", "Patrimônio", "Responsável", "Última aferição",
                "Validade (meses)", "Vencimento", "Situação", "Laboratório", "Certificado"])
    for e in _meus(s, u):
        w.writerow([e.tipo.value, e.marca, e.modelo, e.numero_serie, e.patrimonio, e.responsavel,
                    e.ultima_afericao.strftime("%d/%m/%Y") if e.ultima_afericao else "", e.validade_meses,
                    e.vencimento.strftime("%d/%m/%Y") if e.vencimento else "", e.situacao(h).value,
                    e.laboratorio, e.certificado])
    return StreamingResponse(iter(["﻿" + buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="equipamentos.csv"'})


# ---------------- API JSON (para integrações) ----------------
@app.get("/api/alertas")
def api_alertas(u: Usuario = Depends(usuario_atual), s: Session = Depends(get_db)):
    """Equipamentos vencidos ou vencendo nos próximos dias — útil para e-mail/WhatsApp automáticos."""
    h = hoje()
    return [
        {"id": e.id, "equipamento": f"{e.tipo.value} {e.marca} {e.modelo}", "serie": e.numero_serie,
         "vencimento": e.vencimento.isoformat() if e.vencimento else None,
         "dias": e.dias_para_vencer(h), "situacao": e.situacao(h).value}
        for e in _meus(s, u) if e.situacao(h) in (Situacao.VENCIDO, Situacao.VENCENDO, Situacao.SEM_REGISTRO)
    ]


@app.get("/saude")
def saude():
    return {"ok": True}
