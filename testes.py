# Testes: sobem 3 empresas, derrubam algumas no meio e conferem as regras no fim.
# uso: python testes.py

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback

import requests

import simulador
from cliente import trechos_para_reservar

PASTA_DO_CODIGO = os.path.dirname(os.path.abspath(__file__))
NOMES = ["vaijunto", "empresab", "empresac"]


# --- O conjunto de empresas ---

class Cluster:
    def __init__(self, porta_base, prazo_da_retencao=3):
        self.prazo_da_retencao = prazo_da_retencao
        self.pasta = tempfile.mkdtemp(prefix="consorcio-")
        self.portas = {nome: porta_base + i for i, nome in enumerate(NOMES)}
        self.urls = {nome: f"http://127.0.0.1:{porta}" for nome, porta in self.portas.items()}
        self.processos = {}
        self.registros = []

    def lista_de_urls(self):
        return [self.urls[nome] for nome in NOMES]

    def subir(self, nome):
        outras = ",".join(f"{n}={self.urls[n]}" for n in NOMES if n != nome)
        ambiente = dict(os.environ,
                        EMPRESA=nome, PORTA=str(self.portas[nome]), PARES=outras,
                        DADOS=os.path.join(self.pasta, nome),
                        PRAZO_RETENCAO=str(self.prazo_da_retencao), PERMITIR_INJECAO="1",
                        PYTHONUNBUFFERED="1")
        registro = open(os.path.join(self.pasta, f"{nome}.log"), "a")
        self.registros.append(registro)
        self.processos[nome] = subprocess.Popen(
            [sys.executable, "servidor.py"], cwd=PASTA_DO_CODIGO, env=ambiente,
            stdout=registro, stderr=subprocess.STDOUT)
        esperar_ate(lambda: self.esta_no_ar(nome), 15, f"{nome} subir")

    def subir_todas(self):
        for nome in NOMES:
            self.subir(nome)

    def esta_no_ar(self, nome):
        try:
            return requests.get(self.urls[nome] + "/consorcio/auditoria", timeout=1).ok
        except requests.RequestException:
            return False

    # derruba sem aviso, como uma queda de energia
    def matar(self, nome):
        processo = self.processos[nome]
        if processo.poll() is None:
            processo.send_signal(signal.SIGKILL)
        processo.wait()

    def esta_vivo(self, nome):
        return self.processos[nome].poll() is None

    def auditoria(self, nome):
        try:
            return requests.get(self.urls[nome] + "/consorcio/auditoria", timeout=3).json()
        except requests.RequestException:
            return None

    def encerrar(self):
        for processo in self.processos.values():
            if processo.poll() is None:
                processo.kill()
                processo.wait()
        for registro in self.registros:
            registro.close()
        shutil.rmtree(self.pasta, ignore_errors=True)


@contextlib.contextmanager
def tres_empresas(porta_base, assentos):
    cluster = Cluster(porta_base)
    try:
        cluster.subir_todas()
        simulador.publicar_exemplos(cluster.lista_de_urls(), assentos)
        yield cluster
    finally:
        cluster.encerrar()


# --- Ajudas dos testes ---

def esperar_ate(condicao, limite, descricao):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        if condicao():
            return
        time.sleep(0.2)
    raise AssertionError(f"nao aconteceu em {limite}s: {descricao}")


def itinerario_com(url, usuario, empresas, origem="Salvador", destino="Montes Claros"):
    cabecalhos = simulador.fazer_login(url, usuario)
    busca = simulador.buscar_itinerarios(url, cabecalhos, origem, destino).json()
    for itinerario in busca["itinerarios"]:
        if {t["empresa"] for t in itinerario["trechos"]} == set(empresas):
            return cabecalhos, trechos_para_reservar(itinerario["trechos"])
    raise AssertionError(f"nenhum itinerario com {empresas}")


def reservar(url, cabecalhos, trechos):
    return simulador.pedir_reserva(url, cabecalhos, trechos)


def reservar_e_derrubar(cluster, nome, cabecalhos, trechos, momento):
    try:
        simulador.pedir_reserva(cluster.urls[nome], cabecalhos, trechos, {"X-Injetar": momento})
    except requests.RequestException:
        pass
    esperar_ate(lambda: not cluster.esta_vivo(nome), 10, f"{nome} cair")


def reservas_de(url, usuario):
    cabecalhos = simulador.fazer_login(url, usuario)
    return requests.get(url + "/api/reservas", headers=cabecalhos, timeout=10).json()["reservas"]


def avisos_de(url, usuario):
    cabecalhos = simulador.fazer_login(url, usuario)
    return requests.get(url + "/api/avisos", headers=cabecalhos, timeout=10).json()["avisos"]


def cancelar(url, usuario, caminho):
    cabecalhos = simulador.fazer_login(url, usuario)
    return requests.post(url + caminho, headers=cabecalhos, timeout=30)


def id_da_carona_de(url, motorista):
    cabecalhos = simulador.fazer_login(url, motorista)
    caronas = requests.get(url + "/api/caronas", headers=cabecalhos, timeout=10).json()["caronas"]
    return caronas[0]["id"]


def assentos_retidos_em(cluster, nome):
    auditoria = cluster.auditoria(nome)
    if auditoria is None:
        return -1
    return sum(trecho["retidos"] for trecho in auditoria["trechos"])


def estados_das_reservas(cluster, nome):
    return list(cluster.auditoria(nome)["reservas_recebidas"].values())


# --- A conferência das regras ---

def o_que_falta_terminar(cluster):
    for nome in NOMES:
        auditoria = cluster.auditoria(nome)
        if auditoria is None:
            return f"{nome} fora do ar"
        if any(trecho["retidos"] for trecho in auditoria["trechos"]):
            return f"{nome} ainda tem assento retido"
        if "PREPARADO" in auditoria["reservas_recebidas"].values():
            return f"{nome} ainda tem reserva so preparada"
        for id_reserva, c in auditoria["reservas_coordenadas"].items():
            if c["decisao"] is None or c["falta_avisar"]:
                return f"{nome} ainda nao entregou a decisao de {id_reserva}"
    return None


def esperar_calmaria(cluster, limite=40):
    fim = time.monotonic() + limite
    falta = None
    while time.monotonic() < fim:
        falta = o_que_falta_terminar(cluster)
        if falta is None:
            return
        time.sleep(0.5)
    raise AssertionError(f"nao se acalmou em {limite}s: {falta}")


def violacoes(cluster):
    auditorias = {nome: cluster.auditoria(nome) for nome in NOMES}
    erros = []
    vendidos_pelas_reservas = {}

    for auditoria in auditorias.values():
        for id_reserva, c in auditoria["reservas_coordenadas"].items():
            estados = {p: auditorias[p]["reservas_recebidas"].get(id_reserva)
                       for p in c["participantes"]}
            if c["decisao"] == "COMMIT" and c["cancelada"]:
                for participante, estado in estados.items():
                    if estado != "CANCELADO":
                        erros.append(f"reserva {id_reserva} cancelada, "
                                     f"mas {participante} esta {estado}")
            elif c["decisao"] == "COMMIT":
                for item in c["itens"]:
                    trecho_id = (item["empresa"], item["id_carona"], item["posicao"])
                    vendidos_pelas_reservas[trecho_id] = vendidos_pelas_reservas.get(trecho_id, 0) + 1
                for participante, estado in estados.items():
                    if estado != "CONFIRMADO":
                        erros.append(f"reserva {id_reserva} confirmada, "
                                     f"mas {participante} esta {estado}")
            elif c["decisao"] == "ABORT":
                for participante, estado in estados.items():
                    if estado == "CONFIRMADO":
                        erros.append(f"reserva {id_reserva} abortada, "
                                     f"mas {participante} confirmou")

    for nome, auditoria in auditorias.items():
        for trecho in auditoria["trechos"]:
            trecho_id = (nome, trecho["id_carona"], trecho["posicao"])
            vendidos = trecho["assentos"] - trecho["livres"]
            esperados = vendidos_pelas_reservas.get(trecho_id, 0)
            if trecho["livres"] < 0:
                erros.append(f"{trecho_id} com assentos negativos")
            if vendidos != esperados:
                erros.append(f"{trecho_id}: {vendidos} assentos vendidos, {esperados} reservas")
            if trecho["retidos"]:
                erros.append(f"{trecho_id} com {trecho['retidos']} assento(s) retido(s)")
    return erros


def exigir_regras(cluster):
    esperar_calmaria(cluster)
    erros = violacoes(cluster)
    if erros:
        raise AssertionError("regras violadas:\n  " + "\n  ".join(erros[:10]))


# --- Carga ---

def rodar_carga_em_fundo(cluster, passageiros, duracao, semente):
    estatisticas = simulador.Estatisticas()
    parar = threading.Event()
    carga = threading.Thread(target=simulador.rodar_simulacao, daemon=True, kwargs={
        "urls": cluster.lista_de_urls(), "passageiros": passageiros,
        "duracao": duracao, "parar": parar, "semente": semente,
        "estatisticas": estatisticas,
    })
    carga.start()
    return estatisticas, parar, carga


def encerrar_carga(estatisticas, parar, carga):
    parar.set()
    carga.join(timeout=60)
    print("      " + estatisticas.resumo().replace("\n", "\n      "))


# --- Os testes ---

def teste_reserva_entre_tres_empresas():
    with tres_empresas(5900, assentos=5) as cluster:
        url = cluster.urls["vaijunto"]
        cabecalhos, trechos = itinerario_com(url, "ana", NOMES)

        resposta = reservar(url, cabecalhos, trechos)
        assert resposta.status_code == 201, resposta.text
        assert len(resposta.json()["trechos"]) == 3
        assert len(reservas_de(url, "ana")) == 1

        exigir_regras(cluster)
        for nome in NOMES:
            assert estados_das_reservas(cluster, nome) == ["CONFIRMADO"]


def teste_ultimo_assento_disputado_por_varias_empresas():
    with tres_empresas(5910, assentos=1) as cluster:
        disputantes = 12
        resultados = []
        largada = threading.Barrier(disputantes)

        def tentar(numero):
            url = cluster.lista_de_urls()[numero % 3]
            cabecalhos = simulador.fazer_login(url, f"p{numero}")
            itinerarios = simulador.buscar_itinerarios(
                url, cabecalhos, "Salvador", "Montes Claros").json()["itinerarios"]
            escolhido = itinerarios[numero % len(itinerarios)]
            trechos = trechos_para_reservar(escolhido["trechos"])
            largada.wait()
            resultados.append(reservar(url, cabecalhos, trechos).status_code)

        threads = [threading.Thread(target=tentar, args=(n,)) for n in range(disputantes)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert resultados.count(201) == 1, f"deveria haver 1 vencedor: {sorted(resultados)}"
        assert resultados.count(409) == disputantes - 1, sorted(resultados)
        exigir_regras(cluster)


def teste_coordenadora_cai_antes_da_decisao():
    with tres_empresas(5920, assentos=5) as cluster:
        url_a = cluster.urls["vaijunto"]
        cabecalhos, trechos = itinerario_com(url_a, "ana", NOMES)

        reservar_e_derrubar(cluster, "vaijunto", cabecalhos, trechos, "apos_preparo")
        esperar_ate(lambda: assentos_retidos_em(cluster, "empresab") == 1
                    and assentos_retidos_em(cluster, "empresac") >= 1,
                    10, "B e C segurarem o assento")

        url_c = cluster.urls["empresac"]
        cab_c, trechos_c = itinerario_com(url_c, "bia", ["empresac"],
                                          "Vitoria da Conquista", "Montes Claros")
        assert reservar(url_c, cab_c, trechos_c).status_code == 201

        cluster.subir("vaijunto")
        exigir_regras(cluster)
        assert reservas_de(url_a, "ana") == []


def teste_coordenadora_cai_depois_da_decisao():
    with tres_empresas(5930, assentos=5) as cluster:
        url_a = cluster.urls["vaijunto"]
        cabecalhos, trechos = itinerario_com(url_a, "ana", NOMES)

        reservar_e_derrubar(cluster, "vaijunto", cabecalhos, trechos, "apos_decisao")
        assert assentos_retidos_em(cluster, "empresab") == 1

        cluster.subir("vaijunto")
        exigir_regras(cluster)
        assert len(reservas_de(url_a, "ana")) == 1
        for nome in NOMES:
            assert estados_das_reservas(cluster, nome) == ["CONFIRMADO"]


def teste_carga_com_queda_de_participante():
    with tres_empresas(5940, assentos=5000) as cluster:
        estatisticas, parar, carga = rodar_carga_em_fundo(
            cluster, passageiros=24, duracao=18, semente=7)

        time.sleep(4)
        cluster.matar("empresab")
        antes = estatisticas.quantas(simulador.RESERVOU)
        time.sleep(5)
        durante = estatisticas.quantas(simulador.RESERVOU)
        cluster.subir("empresab")
        time.sleep(4)
        encerrar_carga(estatisticas, parar, carga)

        assert durante > antes, "as outras empresas pararam de reservar enquanto B estava fora"
        assert estatisticas.quantas(simulador.RESERVOU) > durante, \
            "nada foi reservado depois que B voltou"
        exigir_regras(cluster)


def teste_carga_com_queda_da_coordenadora_no_meio():
    with tres_empresas(5950, assentos=5000) as cluster:
        estatisticas, parar, carga = rodar_carga_em_fundo(
            cluster, passageiros=24, duracao=16, semente=11)

        for nome in ["vaijunto", "empresac"]:
            time.sleep(3)
            cluster.matar(nome)
            time.sleep(2)
            cluster.subir(nome)
        time.sleep(3)
        encerrar_carga(estatisticas, parar, carga)

        exigir_regras(cluster)


# motorista0: vaijunto, motorista1: empresab, motorista2: empresac

def teste_passageiro_cancela_reserva():
    with tres_empresas(5960, assentos=5) as cluster:
        url = cluster.urls["vaijunto"]
        cabecalhos, trechos = itinerario_com(url, "ana", NOMES)
        reserva = reservar(url, cabecalhos, trechos).json()

        resposta = cancelar(url, "ana", f"/api/reservas/{reserva['id']}/cancelar")
        assert resposta.status_code == 200, resposta.text
        assert reservas_de(url, "ana") == []
        segunda_vez = cancelar(url, "ana", f"/api/reservas/{reserva['id']}/cancelar")
        assert segunda_vez.status_code == 409

        exigir_regras(cluster)
        for nome in NOMES:
            assert estados_das_reservas(cluster, nome) == ["CANCELADO"]
            assert all(t["livres"] == 5 for t in cluster.auditoria(nome)["trechos"])

        for nome, motorista in [("vaijunto", "motorista0"), ("empresab", "motorista1"),
                                ("empresac", "motorista2")]:
            avisos = avisos_de(cluster.urls[nome], motorista)
            assert len(avisos) == 1 and "cancelou" in avisos[0], avisos


def teste_motorista_cancela_carona():
    with tres_empresas(5970, assentos=5) as cluster:
        url_a = cluster.urls["vaijunto"]
        url_b = cluster.urls["empresab"]
        cabecalhos, trechos = itinerario_com(url_a, "ana", NOMES)
        assert reservar(url_a, cabecalhos, trechos).status_code == 201

        id_carona = id_da_carona_de(url_b, "motorista1")
        resposta = cancelar(url_b, "motorista1", f"/api/caronas/{id_carona}/cancelar")
        assert resposta.status_code == 200, resposta.text

        esperar_ate(lambda: reservas_de(url_a, "ana") == [], 10, "a reserva da ana sumir")
        exigir_regras(cluster)

        avisos_da_ana = avisos_de(url_a, "ana")
        assert len(avisos_da_ana) == 1 and "motorista cancelou" in avisos_da_ana[0], avisos_da_ana
        assert len(avisos_de(url_a, "motorista0")) == 1
        assert len(avisos_de(cluster.urls["empresac"], "motorista2")) == 1
        assert avisos_de(url_b, "motorista1") == []

        busca = simulador.buscar_itinerarios(url_a, cabecalhos, "Salvador", "Montes Claros").json()
        for itinerario in busca["itinerarios"]:
            assert all(t["id_carona"] != id_carona for t in itinerario["trechos"])
        cab_b = simulador.fazer_login(url_b, "motorista1")
        assert requests.get(url_b + "/api/caronas", headers=cab_b, timeout=10).json()["caronas"] == []


def teste_carona_cancelada_com_coordenadora_fora_do_ar():
    with tres_empresas(5980, assentos=5) as cluster:
        url_a = cluster.urls["vaijunto"]
        url_b = cluster.urls["empresab"]
        cabecalhos, trechos = itinerario_com(url_a, "ana", NOMES)
        assert reservar(url_a, cabecalhos, trechos).status_code == 201

        cluster.matar("vaijunto")
        id_carona = id_da_carona_de(url_b, "motorista1")
        resposta = cancelar(url_b, "motorista1", f"/api/caronas/{id_carona}/cancelar")
        assert resposta.status_code == 200, resposta.text

        cluster.subir("vaijunto")
        esperar_ate(lambda: reservas_de(url_a, "ana") == [], 15, "a reserva da ana sumir")
        exigir_regras(cluster)
        assert len(avisos_de(url_a, "ana")) == 1


# --- Rodar tudo ---

def main():
    testes = [(nome, funcao) for nome, funcao in sorted(globals().items())
              if nome.startswith("teste_") and callable(funcao)]
    falhas = 0
    for nome, funcao in testes:
        inicio = time.monotonic()
        try:
            funcao()
            print(f"PASSOU  {nome}  ({time.monotonic() - inicio:.1f}s)")
        except Exception:
            falhas += 1
            print(f"FALHOU  {nome}")
            traceback.print_exc()
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
