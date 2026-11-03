# Servidor de uma empresa: /api para os clientes, /consorcio para as outras empresas.

import hashlib
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request

from armazem import Armazem
from grafo import buscar_itinerarios
from outras_empresas import NaoRespondeu, OutrasEmpresas
from relogio import Relogio
from reservas import Reservas
from validacao import data_valida, erro_na_carona, erro_no_preparo, erro_na_reserva

EMPRESA = os.environ.get("EMPRESA", "vaijunto")
PORTA = int(os.environ.get("PORTA", "5001"))
PASTA_DOS_DADOS = os.environ.get("DADOS", f"./dados/{EMPRESA}")
PERMITIR_INJECAO = os.environ.get("PERMITIR_INJECAO") == "1"
PRAZO_DA_BUSCA = 2.5


# --- Ajuda e configuração ---

def ler_enderecos(texto):
    enderecos = {}
    for pedaco in texto.split(","):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        nome, endereco = pedaco.split("=", 1)
        enderecos[nome.strip()] = endereco.strip().rstrip("/")
    return enderecos


def responder_erro(mensagem, codigo):
    return jsonify({"erro": mensagem}), codigo


def corpo_json():
    corpo = request.get_json(silent=True)
    return corpo if isinstance(corpo, dict) else {}


# --- Objetos desta empresa ---

relogio = Relogio()
armazem = Armazem(EMPRESA, PASTA_DOS_DADOS)
# o relogio continua de onde o registro parou
relogio.ao_receber(armazem.maior_relogio)
outras = OutrasEmpresas(relogio, ler_enderecos(os.environ.get("PARES", "")))
reservas = Reservas(armazem, outras, relogio)

app = Flask(__name__)


# --- Relógio de Lamport (corre em todo pedido) ---

@app.before_request
def receber_relogio():
    relogio.ao_receber(request.headers.get("X-Relogio"))


@app.after_request
def devolver_relogio(resposta):
    resposta.headers["X-Relogio"] = str(relogio.atual())
    return resposta


# --- Login ---

sessoes = {}


def cifrar_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()


def usuario_logado():
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return sessoes.get(token)


@app.post("/api/login")
def login():
    corpo = corpo_json()
    usuario = corpo.get("usuario")
    senha = corpo.get("senha")
    if not isinstance(usuario, str) or not isinstance(senha, str) or not usuario or not senha:
        return responder_erro("informe usuario e senha", 400)
    if not armazem.autenticar(usuario, cifrar_senha(senha)):
        return responder_erro("senha incorreta", 401)

    token = uuid.uuid4().hex
    sessoes[token] = usuario
    return jsonify({"token": token, "usuario": usuario, "empresa": EMPRESA})


@app.get("/api/avisos")
def meus_avisos():
    usuario = usuario_logado()
    if usuario is None:
        return responder_erro("faca login antes", 401)
    return jsonify({"avisos": armazem.avisos_de(usuario)})


# --- Motorista (/api) ---

@app.post("/api/caronas")
def publicar_carona():
    usuario = usuario_logado()
    if usuario is None:
        return responder_erro("faca login antes", 401)

    corpo = corpo_json()
    problema = erro_na_carona(corpo)
    if problema:
        return responder_erro(problema, 400)
    id_carona = str(uuid.uuid4())
    armazem.publicar_carona(id_carona, usuario, corpo["rota"], corpo["data"],
                            corpo["horario"], corpo["assentos"], corpo["precos"])
    return jsonify({"id": id_carona, "empresa": EMPRESA}), 201


@app.get("/api/caronas")
def minhas_caronas():
    usuario = usuario_logado()
    if usuario is None:
        return responder_erro("faca login antes", 401)
    return jsonify({"caronas": armazem.caronas_do_motorista(usuario)})


@app.post("/api/caronas/<id_carona>/cancelar")
def cancelar_carona(id_carona):
    usuario = usuario_logado()
    if usuario is None:
        return responder_erro("faca login antes", 401)

    problema = reservas.cancelar_carona(id_carona, usuario)
    if problema:
        return responder_erro(problema, 409)
    return jsonify({"mensagem": "carona cancelada. os passageiros serao avisados"})


# --- Passageiro (/api) ---

def pedir_trechos_a(empresa, data):
    try:
        codigo, resposta = outras.pedir(empresa, "GET", "/consorcio/trechos",
                                        params={"data": data}, prazo=PRAZO_DA_BUSCA)
    except NaoRespondeu:
        return None
    return resposta.get("trechos") if codigo == 200 else None


# pergunta a todas ao mesmo tempo; quem nao responde fica de fora
def juntar_trechos(data):
    trechos = armazem.trechos_com_vaga(data)
    empresas_fora_do_ar = []
    nomes = outras.nomes()
    if not nomes:
        return trechos, empresas_fora_do_ar
    with ThreadPoolExecutor(max_workers=len(nomes)) as grupo:
        respostas = grupo.map(lambda empresa: pedir_trechos_a(empresa, data), nomes)
    for empresa, trechos_dela in zip(nomes, respostas):
        if trechos_dela is None:
            empresas_fora_do_ar.append(empresa)
        else:
            trechos.extend(trechos_dela)
    return trechos, empresas_fora_do_ar


@app.get("/api/itinerarios")
def buscar():
    if usuario_logado() is None:
        return responder_erro("faca login antes", 401)

    origem = request.args.get("origem")
    destino = request.args.get("destino")
    data = request.args.get("data")
    if not origem or not destino or not data:
        return responder_erro("informe origem, destino e data", 400)
    if not data_valida(data):
        return responder_erro("data invalida, use DD/MM/AAAA", 400)

    trechos, empresas_fora_do_ar = juntar_trechos(data)
    itinerarios = []
    for caminho in buscar_itinerarios(trechos, origem, destino):
        itinerarios.append({
            "trechos": caminho,
            "preco_total": sum(t["preco"] for t in caminho),
            "conexoes": len(caminho),
        })
    return jsonify({"itinerarios": itinerarios, "empresas_fora_do_ar": empresas_fora_do_ar})


@app.post("/api/reservas")
def reservar():
    usuario = usuario_logado()
    if usuario is None:
        return responder_erro("faca login antes", 401)

    trechos = corpo_json().get("trechos")
    problema = erro_na_reserva(trechos, set(outras.nomes()) | {EMPRESA})
    if problema:
        return responder_erro(problema, 400)

    injecao = request.headers.get("X-Injetar") if PERMITIR_INJECAO else None
    deu_certo, resultado, alguma_fora_do_ar = reservas.reservar(usuario, trechos, injecao)
    if deu_certo:
        return jsonify(resultado), 201
    return responder_erro(resultado, 503 if alguma_fora_do_ar else 409)


@app.get("/api/reservas")
def minhas_reservas():
    usuario = usuario_logado()
    if usuario is None:
        return responder_erro("faca login antes", 401)
    return jsonify({"reservas": armazem.reservas_ativas(usuario)})


@app.post("/api/reservas/<id_reserva>/cancelar")
def cancelar_reserva(id_reserva):
    usuario = usuario_logado()
    if usuario is None:
        return responder_erro("faca login antes", 401)

    problema = reservas.cancelar_reserva(id_reserva, passageiro=usuario)
    if problema:
        return responder_erro(problema, 409)
    return jsonify({"mensagem": "reserva cancelada. os motoristas serao avisados"})


# --- Entre empresas (/consorcio) ---

@app.get("/consorcio/trechos")
def enviar_trechos():
    data = request.args.get("data", "")
    if not data_valida(data):
        return responder_erro("data invalida", 400)
    return jsonify({"empresa": EMPRESA, "trechos": armazem.trechos_com_vaga(data)})


@app.post("/consorcio/reservas/<id_reserva>/preparar")
def preparar(id_reserva):
    corpo = corpo_json()
    problema = erro_no_preparo(corpo)
    if problema:
        return responder_erro(problema, 400)
    deu_certo, resposta = armazem.preparar(id_reserva, corpo["prioridade"],
                                           corpo["coordenadora"], corpo["trechos"])
    if not deu_certo:
        return responder_erro(resposta, 409)
    return jsonify({"estado": "PREPARADO", "trechos": resposta})


@app.post("/consorcio/reservas/<id_reserva>/confirmar")
def confirmar(id_reserva):
    if not armazem.confirmar(id_reserva):
        return responder_erro("a reserva nao esta preparada aqui", 409)
    return jsonify({"estado": "CONFIRMADO"})


@app.post("/consorcio/reservas/<id_reserva>/abortar")
def abortar(id_reserva):
    if not armazem.abortar(id_reserva):
        return responder_erro("a reserva ja foi confirmada aqui", 409)
    return jsonify({"estado": "ABORTADO"})


@app.post("/consorcio/reservas/<id_reserva>/cancelar")
def cancelar_assentos(id_reserva):
    armazem.cancelar_assentos(id_reserva)
    return jsonify({"estado": "CANCELADO"})


@app.post("/consorcio/reservas/<id_reserva>/carona_cancelada")
def carona_cancelada(id_reserva):
    reservas.cancelar_reserva(id_reserva, motivo=corpo_json().get("motivo"))
    return jsonify({"ok": True})


@app.get("/consorcio/reservas/<id_reserva>/decisao")
def decisao(id_reserva):
    return jsonify({"decisao": armazem.decisao_da_reserva(id_reserva)})


@app.get("/consorcio/auditoria")
def auditoria():
    return jsonify(armazem.auditoria())


# --- Arranque ---

def iniciar_servidor():
    reservas.abortar_sem_decisao()
    threading.Thread(target=reservas.rodar_entregador, daemon=True).start()
    threading.Thread(target=reservas.rodar_vigia, daemon=True).start()
    print(f"empresa {EMPRESA} na porta {PORTA}, outras: {outras.nomes()}", flush=True)
    app.run(host="0.0.0.0", port=PORTA, threaded=True)


if __name__ == "__main__":
    iniciar_servidor()
