import os
import time
import uuid

from armazem import ABORT, COMMIT, ESPERA_MAX_NA_FILA, PENDENTE
from outras_empresas import NaoRespondeu

PRAZO_DO_PREPARO = ESPERA_MAX_NA_FILA + 3.0
PRAZO_DO_AVISO = 2.0
PAUSA_ENTRE_RONDAS = 0.5


# --- Apoio ---

def agrupar_por_empresa(itens):
    grupos = {}
    for item in itens:
        so_o_trecho = {"id_carona": item["id_carona"], "posicao": item["posicao"]}
        grupos.setdefault(item["empresa"], []).append(so_o_trecho)
    return grupos


def identificar_trecho(item):
    return (item["empresa"], item["id_carona"], item["posicao"])


def montar_reserva(id_reserva, passageiro, itens, resumos):
    trechos = [resumos[identificar_trecho(item)] for item in itens]
    return {
        "id": id_reserva,
        "passageiro": passageiro,
        "trechos": trechos,
        "preco_total": sum(t["preco"] for t in trechos),
        "situacao": "CONFIRMADA",
    }


# derruba o servidor de proposito, para os testes de falha
def derrubar_se_pedido(injecao, momento_atual):
    if injecao == momento_atual:
        os._exit(1)


class Reservas:
    # --- Construção ---

    def __init__(self, armazem, outras, relogio):
        self.armazem = armazem
        self.outras = outras
        self.relogio = relogio
        self.empresa = armazem.empresa

    def anotar(self, texto):
        print(f"[{self.empresa}] {texto}", flush=True)

    def criar_id_reserva(self):
        momento = self.relogio.ao_enviar()
        return momento, f"{momento:08d}-{self.empresa}-{uuid.uuid4().hex[:6]}"

    # --- Reservar (2PC) ---

    def reservar(self, passageiro, itens, injecao=None):
        momento, id_reserva = self.criar_id_reserva()
        prioridade = [momento, self.empresa]
        trechos_por_empresa = agrupar_por_empresa(itens)
        participantes = sorted(trechos_por_empresa)
        self.armazem.iniciar_coordenacao(id_reserva, passageiro, itens, participantes)

        resumos = {}
        motivo_da_recusa = None
        alguma_fora_do_ar = False

        # fase 1 (um erro inesperado vira recusa)
        reserva = None
        try:
            for empresa in participantes:
                deu_certo, resposta, alguma_fora_do_ar = self.pedir_preparo(
                    empresa, id_reserva, prioridade, trechos_por_empresa[empresa])
                if not deu_certo:
                    motivo_da_recusa = resposta
                    break
                for resumo in resposta:
                    resumos[identificar_trecho(resumo)] = resumo
            if motivo_da_recusa is None:
                reserva = montar_reserva(id_reserva, passageiro, itens, resumos)
        except Exception as erro:
            self.anotar(f"erro na fase 1 da reserva {id_reserva}: {erro!r}")
            motivo_da_recusa = "erro inesperado ao segurar os assentos"

        # decisao
        if motivo_da_recusa is None:
            derrubar_se_pedido(injecao, "apos_preparo")
            decisao = self.armazem.decidir(id_reserva, COMMIT, reserva)
        else:
            decisao = self.armazem.decidir(id_reserva, ABORT, None)

        # fase 2
        derrubar_se_pedido(injecao, "apos_decisao")
        self.avisar_empresas(id_reserva, participantes)

        if decisao == COMMIT:
            return True, reserva, False
        return False, motivo_da_recusa or "reserva cancelada", alguma_fora_do_ar

    def pedir_preparo(self, empresa, id_reserva, prioridade, trechos):
        if empresa == self.empresa:
            deu_certo, resposta = self.armazem.preparar(id_reserva, prioridade, self.empresa, trechos)
            return deu_certo, resposta, False

        corpo = {"prioridade": prioridade, "coordenadora": self.empresa, "trechos": trechos}
        try:
            codigo, resposta = self.outras.pedir(
                empresa, "POST", f"/consorcio/reservas/{id_reserva}/preparar", corpo,
                prazo=PRAZO_DO_PREPARO)
        except NaoRespondeu:
            return False, f"a empresa {empresa} nao respondeu", True

        if codigo == 200:
            return True, resposta["trechos"], False
        return False, resposta.get("erro", f"{empresa} recusou"), False

    def avisar_empresas(self, id_reserva, empresas):
        for empresa in empresas:
            self.avisar_uma_empresa(id_reserva, empresa)

    def avisar_uma_empresa(self, id_reserva, empresa):
        acao = self.armazem.aviso_a_entregar(id_reserva)
        if acao is None:
            return

        if empresa == self.empresa:
            self.fazer_aqui(id_reserva, acao)
        else:
            try:
                codigo, _ = self.outras.pedir(
                    empresa, "POST", f"/consorcio/reservas/{id_reserva}/{acao}",
                    prazo=PRAZO_DO_AVISO)
            except NaoRespondeu:
                return
            if codigo >= 500:
                return
            if codigo == 409:
                self.anotar(f"AVISO: {empresa} nao aceitou {acao} na reserva {id_reserva}")

        self.armazem.marcar_avisada(id_reserva, empresa, acao)

    def fazer_aqui(self, id_reserva, acao):
        if acao == "confirmar":
            self.armazem.confirmar(id_reserva)
        elif acao == "abortar":
            self.armazem.abortar(id_reserva)
        elif acao == "cancelar":
            self.armazem.cancelar_assentos(id_reserva)

    # --- Cancelamentos ---

    def cancelar_reserva(self, id_reserva, passageiro=None, motivo=None):
        problema = self.armazem.cancelar_coordenacao(id_reserva, passageiro, motivo)
        if problema:
            return problema
        self.anotar(f"reserva {id_reserva} cancelada ({motivo or 'pelo passageiro'})")
        self.avisar_empresas(id_reserva, self.armazem.quem_participa(id_reserva))
        return None

    def cancelar_carona(self, id_carona, motorista):
        problema = self.armazem.cancelar_carona(id_carona, motorista)
        if problema:
            return problema
        self.anotar(f"carona {id_carona} cancelada pelo motorista {motorista}")
        self.avisar_coordenadoras()
        return None

    def avisar_coordenadoras(self):
        for id_reserva, coordenadora, carona in self.armazem.reservas_sem_carona():
            motivo = f"o motorista cancelou a carona {carona}"
            if coordenadora == self.empresa:
                self.cancelar_reserva(id_reserva, motivo=motivo)
                continue
            try:
                self.outras.pedir(
                    coordenadora, "POST", f"/consorcio/reservas/{id_reserva}/carona_cancelada",
                    {"motivo": motivo}, prazo=PRAZO_DO_AVISO)
            except NaoRespondeu:
                pass

    # --- Recuperação e tarefas de fundo ---

    # ao subir: reserva sem decisao vira ABORT
    def abortar_sem_decisao(self):
        for id_reserva in self.armazem.sem_decisao():
            self.armazem.decidir(id_reserva, ABORT, None)

    def repetir_para_sempre(self, nome, tarefa):
        while True:
            try:
                tarefa()
            except Exception as erro:
                self.anotar(f"{nome}: {erro}")
            time.sleep(PAUSA_ENTRE_RONDAS)

    # thread 1: o entregador
    def rodar_entregador(self):
        self.repetir_para_sempre("entregador", self.reenviar_avisos)

    def reenviar_avisos(self):
        for id_reserva, faltam in self.armazem.avisos_pendentes():
            self.avisar_empresas(id_reserva, faltam)
        self.avisar_coordenadoras()

    # thread 2: o vigia
    def rodar_vigia(self):
        self.repetir_para_sempre("vigia", self.vigiar)

    def vigiar(self):
        for reserva in self.armazem.retencoes_vencidas():
            id_reserva = reserva["id_reserva"]
            decisao = self.perguntar_decisao(id_reserva, reserva["coordenadora"])
            if decisao == COMMIT:
                self.armazem.confirmar(id_reserva)
            elif decisao == ABORT:
                self.armazem.abortar(id_reserva)
            else:
                self.armazem.adiar_vencimento(id_reserva)

    def perguntar_decisao(self, id_reserva, coordenadora):
        if coordenadora == self.empresa:
            return self.armazem.decisao_da_reserva(id_reserva)
        try:
            codigo, resposta = self.outras.pedir(
                coordenadora, "GET", f"/consorcio/reservas/{id_reserva}/decisao",
                prazo=PRAZO_DO_AVISO)
        except NaoRespondeu:
            return None
        if codigo != 200:
            return None
        return resposta.get("decisao", PENDENTE)
