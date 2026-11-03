# Simulador de passageiros, sem interface.
# uso: python simulador.py --empresas URL1,URL2,URL3 --semear 5000 --passageiros 30 --duracao 20

import argparse
import random
import threading
import time

import requests

from cliente import trechos_para_reservar

DATA = "10/12/2026"
RESERVOU = "reservou"

TRAJETOS = [
    ("Salvador", "Montes Claros"),
    ("Salvador", "Vitoria da Conquista"),
    ("Feira de Santana", "Montes Claros"),
    ("Salvador", "Feira de Santana"),
    ("Feira de Santana", "Vitoria da Conquista"),
    ("Vitoria da Conquista", "Montes Claros"),
]

RESULTADO_POR_CODIGO = {
    201: RESERVOU,
    409: "recusada (sem vaga ou disputa)",
    503: "recusada (empresa fora do ar)",
}


# --- Pedidos à API ---

def fazer_login(url, usuario, senha="123"):
    resposta = requests.post(url + "/api/login", json={"usuario": usuario, "senha": senha},
                             timeout=10)
    resposta.raise_for_status()
    return {"Authorization": "Bearer " + resposta.json()["token"]}


def buscar_itinerarios(url, cabecalhos, origem, destino, data=DATA):
    return requests.get(url + "/api/itinerarios", headers=cabecalhos, timeout=15,
                        params={"origem": origem, "destino": destino, "data": data})


def pedir_reserva(url, cabecalhos, trechos, cabecalhos_extras=None):
    cabecalhos = dict(cabecalhos, **(cabecalhos_extras or {}))
    return requests.post(url + "/api/reservas", headers=cabecalhos,
                         json={"trechos": trechos}, timeout=30)


def publicar_exemplos(urls, assentos, data=DATA):
    caronas = [
        (urls[0], ["Salvador", "Feira de Santana"], [20]),
        (urls[1], ["Feira de Santana", "Vitoria da Conquista"], [35]),
        (urls[2], ["Vitoria da Conquista", "Montes Claros"], [40]),
        (urls[2], ["Feira de Santana", "Vitoria da Conquista"], [30]),
    ]
    for numero, (url, rota, precos) in enumerate(caronas):
        cabecalhos = fazer_login(url, f"motorista{numero}")
        resposta = requests.post(url + "/api/caronas", headers=cabecalhos, timeout=10, json={
            "rota": rota, "data": data, "horario": "08:00",
            "assentos": assentos, "precos": precos,
        })
        resposta.raise_for_status()


# --- Contagem dos resultados ---

class Estatisticas:
    def __init__(self):
        self.trava = threading.Lock()
        self.contagem = {}
        self.duracoes = []

    def registrar(self, resultado, segundos):
        with self.trava:
            self.contagem[resultado] = self.contagem.get(resultado, 0) + 1
            if segundos is not None:
                self.duracoes.append(segundos)

    def quantas(self, resultado):
        with self.trava:
            return self.contagem.get(resultado, 0)

    def resumo(self):
        with self.trava:
            contagem = dict(self.contagem)
            duracoes = list(self.duracoes)
        linhas = [f"tentativas de reserva: {sum(contagem.values())}"]
        for nome in sorted(contagem):
            linhas.append(f"  {nome}: {contagem[nome]}")
        if duracoes:
            media = sum(duracoes) / len(duracoes)
            linhas.append(f"tempo de uma reserva: media {media * 1000:.0f} ms, "
                          f"maximo {max(duracoes) * 1000:.0f} ms")
        return "\n".join(linhas)


# --- A simulação ---

def uma_busca_e_reserva(url, cabecalhos, aleatorio):
    origem, destino = aleatorio.choice(TRAJETOS)
    busca = buscar_itinerarios(url, cabecalhos, origem, destino)
    busca.raise_for_status()
    itinerarios = busca.json()["itinerarios"]
    if not itinerarios:
        return "sem itinerario", None

    escolhido = aleatorio.choice(itinerarios[:2])
    inicio = time.monotonic()
    resposta = pedir_reserva(url, cabecalhos, trechos_para_reservar(escolhido["trechos"]))
    resultado = RESULTADO_POR_CODIGO.get(resposta.status_code, f"erro {resposta.status_code}")
    return resultado, time.monotonic() - inicio


def passageiro_virtual(numero, urls, estatisticas, parar, aleatorio):
    url = urls[numero % len(urls)]
    cabecalhos = None
    while not parar.is_set():
        try:
            if cabecalhos is None:
                cabecalhos = fazer_login(url, f"passageiro{numero}")
            resultado, segundos = uma_busca_e_reserva(url, cabecalhos, aleatorio)
        except requests.RequestException:
            resultado, segundos = "empresa de origem inalcancavel", None
            cabecalhos = None
            time.sleep(0.2)
        estatisticas.registrar(resultado, segundos)
        parar.wait(aleatorio.uniform(0.0, 0.05))


def rodar_simulacao(urls, passageiros, duracao, parar=None, semente=1, estatisticas=None):
    parar = parar or threading.Event()
    estatisticas = estatisticas or Estatisticas()
    threads = []
    for numero in range(passageiros):
        aleatorio = random.Random(semente * 1000 + numero)
        thread = threading.Thread(target=passageiro_virtual, daemon=True,
                                  args=(numero, urls, estatisticas, parar, aleatorio))
        thread.start()
        threads.append(thread)

    parar.wait(duracao)
    parar.set()
    for thread in threads:
        thread.join(timeout=35)
    return estatisticas


def main():
    analisador = argparse.ArgumentParser(description="simulador de passageiros do consorcio")
    analisador.add_argument("--empresas", required=True, help="URLs separadas por virgula")
    analisador.add_argument("--passageiros", type=int, default=20)
    analisador.add_argument("--duracao", type=float, default=15)
    analisador.add_argument("--semear", type=int, default=0, help="publica caronas com N assentos")
    argumentos = analisador.parse_args()

    urls = [u.strip().rstrip("/") for u in argumentos.empresas.split(",")]
    if argumentos.semear:
        if len(urls) < 3:
            raise SystemExit("--semear precisa de 3 empresas")
        publicar_exemplos(urls, argumentos.semear)
        print(f"caronas publicadas com {argumentos.semear} assentos")

    print(f"{argumentos.passageiros} passageiros por {argumentos.duracao:.0f}s...")
    print(rodar_simulacao(urls, argumentos.passageiros, argumentos.duracao).resumo())


if __name__ == "__main__":
    main()
