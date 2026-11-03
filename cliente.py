# Base dos clientes de terminal.

import os

import requests

URL_PADRAO = os.environ.get("EMPRESA_URL", "http://127.0.0.1:5001")


# --- A conexão ---

class Erro(Exception):
    def __init__(self, mensagem, codigo=None):
        super().__init__(mensagem)
        self.codigo = codigo


class Cliente:
    def __init__(self, url=URL_PADRAO):
        self.url = url.rstrip("/")
        self.token = None

    def pedir(self, metodo, caminho, corpo=None, params=None):
        cabecalhos = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            resposta = requests.request(metodo, self.url + caminho, json=corpo,
                                        params=params, headers=cabecalhos, timeout=30)
        except requests.RequestException:
            raise Erro(f"nao consegui falar com {self.url}")
        try:
            dados = resposta.json()
        except ValueError:
            dados = {}
        if resposta.status_code >= 400:
            raise Erro(dados.get("erro", f"erro {resposta.status_code}"), resposta.status_code)
        return dados

    def entrar(self, usuario, senha):
        dados = self.pedir("POST", "/api/login", {"usuario": usuario, "senha": senha})
        self.token = dados["token"]
        return dados


# --- Apoio dos menus ---

def trechos_para_reservar(trechos_do_itinerario):
    return [{"empresa": t["empresa"], "id_carona": t["id_carona"], "posicao": t["posicao"]}
            for t in trechos_do_itinerario]


def escolher(lista, pergunta):
    escolha = input(pergunta).strip()
    if not escolha.isdigit() or not 1 <= int(escolha) <= len(lista):
        return None
    return lista[int(escolha) - 1]


def ver_avisos(conexao):
    avisos = conexao.pedir("GET", "/api/avisos")["avisos"]
    if not avisos:
        print("  nenhum aviso")
    for aviso in avisos:
        print(f"  * {aviso}")


def entrar_pelo_terminal(conexao):
    while True:
        usuario = input("usuario: ").strip()
        senha = input("senha: ").strip()
        try:
            dados = conexao.entrar(usuario, senha)
        except Erro as erro:
            print(f"  {erro}\n")
            continue
        print(f"entrou na empresa {dados['empresa']}\n")
        return


def rodar_menu(conexao, opcoes):
    while True:
        print()
        for numero, (texto, _) in enumerate(opcoes, 1):
            print(f"  {numero}) {texto}")
        print("  0) sair")

        escolha = input("> ").strip()
        if escolha == "0":
            return
        if not escolha.isdigit() or not 1 <= int(escolha) <= len(opcoes):
            continue

        _, funcao = opcoes[int(escolha) - 1]
        try:
            funcao(conexao)
        except Erro as erro:
            print(f"  {erro}")
            if erro.codigo == 401:
                print("  o servidor reiniciou, entre de novo")
                entrar_pelo_terminal(conexao)


def iniciar_cliente(opcoes):
    conexao = Cliente()
    entrar_pelo_terminal(conexao)
    rodar_menu(conexao, opcoes + [("avisos", ver_avisos)])
