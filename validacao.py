# Validacao do que chega pela API: cada erro_* devolve o problema ou None.

from datetime import datetime


# --- Formatos e tipos ---

def no_formato(texto, formato):
    if not isinstance(texto, str):
        return False
    try:
        datetime.strptime(texto, formato)
        return True
    except ValueError:
        return False


def data_valida(texto):
    return no_formato(texto, "%d/%m/%Y")


def hora_valida(texto):
    return no_formato(texto, "%H:%M")


# em Python, True tambem conta como int
def e_inteiro(valor):
    return isinstance(valor, int) and not isinstance(valor, bool)


def e_numero(valor):
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def e_texto_preenchido(valor):
    return isinstance(valor, str) and valor.strip() != ""


# --- Conferências do que chega pela API ---

def erro_na_carona(corpo):
    rota = corpo.get("rota")
    precos = corpo.get("precos")
    assentos = corpo.get("assentos")

    if not isinstance(rota, list) or len(rota) < 2:
        return "a rota precisa de pelo menos 2 cidades"
    if not all(e_texto_preenchido(cidade) for cidade in rota):
        return "cada cidade da rota precisa ser um texto"
    if len(set(rota)) != len(rota):
        return "a rota nao pode repetir cidade"
    if not data_valida(corpo.get("data")):
        return "data invalida, use DD/MM/AAAA"
    if not hora_valida(corpo.get("horario")):
        return "horario invalido, use HH:MM"
    if not e_inteiro(assentos) or assentos < 1:
        return "assentos deve ser um numero maior que zero"
    if not isinstance(precos, list) or len(precos) != len(rota) - 1:
        return "precisa de um preco para cada trecho"
    if not all(e_numero(preco) and preco >= 0 for preco in precos):
        return "os precos precisam ser numeros"
    return None


def erro_no_trecho(trecho):
    if not isinstance(trecho, dict):
        return "trecho mal formado"
    if not isinstance(trecho.get("id_carona"), str):
        return "id_carona invalido"
    posicao = trecho.get("posicao")
    if not e_inteiro(posicao) or posicao < 0:
        return "posicao invalida"
    return None


def erro_no_preparo(corpo):
    prioridade = corpo.get("prioridade")
    if (not isinstance(prioridade, list) or len(prioridade) != 2
            or not e_inteiro(prioridade[0]) or not isinstance(prioridade[1], str)):
        return "prioridade invalida, use [relogio, empresa]"
    if not e_texto_preenchido(corpo.get("coordenadora")):
        return "coordenadora invalida"
    trechos = corpo.get("trechos")
    if not isinstance(trechos, list) or not trechos:
        return "nenhum trecho informado"
    for trecho in trechos:
        problema = erro_no_trecho(trecho)
        if problema:
            return problema
    return None


def erro_na_reserva(trechos, empresas_conhecidas):
    if not isinstance(trechos, list) or not trechos:
        return "nenhum trecho informado"
    ja_vistos = set()
    for trecho in trechos:
        problema = erro_no_trecho(trecho)
        if problema:
            return problema
        if trecho.get("empresa") not in empresas_conhecidas:
            return f"empresa desconhecida: {trecho.get('empresa')}"
        identificacao = (trecho["empresa"], trecho["id_carona"], trecho["posicao"])
        if identificacao in ja_vistos:
            return "trecho repetido"
        ja_vistos.add(identificacao)
    return None

