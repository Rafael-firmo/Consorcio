# Tudo o que a empresa guarda, na memoria e no registro.jsonl.

import json
import os
import threading
import time

# --- Constantes ---

PRAZO_DA_RETENCAO = float(os.environ.get("PRAZO_RETENCAO", "8"))
ESPERA_MAX_NA_FILA = float(os.environ.get("ESPERA_MAX", "2"))

PREPARADO = "PREPARADO"
CONFIRMADO = "CONFIRMADO"
ABORTADO = "ABORTADO"
CANCELADO = "CANCELADO"

COMMIT = "COMMIT"
ABORT = "ABORT"
PENDENTE = "PENDENTE"


# --- Fichas ---

def ficha_da_dona(id_reserva, estado, trechos=(), coordenadora=None):
    return {
        "id_reserva": id_reserva,
        "estado": estado,
        "trechos": [tuple(trecho_id) for trecho_id in trechos],
        "coordenadora": coordenadora,
        "vence_em": time.monotonic() + PRAZO_DA_RETENCAO,
    }


def ficha_da_coordenadora(id_reserva, passageiro, itens, participantes):
    return {
        "id_reserva": id_reserva,
        "passageiro": passageiro,
        "itens": list(itens),
        "participantes": list(participantes),
        "decisao": None,
        "reserva": None,
        "cancelada": False,
        "falta_avisar": set(),
    }


def descrever_carona(carona):
    return f"{' -> '.join(carona['rota'])} em {carona['data']} as {carona['horario']}"


def descrever_trecho(trecho):
    return f"{trecho['origem']} -> {trecho['destino']} em {trecho['data']} as {trecho['horario']}"


class Armazem:
    # --- Construção e disco ---

    def __init__(self, empresa, pasta):
        self.empresa = empresa
        self.trava = threading.Condition()

        self.usuarios = {}
        self.caronas = {}
        self.trechos = {}
        self.reservas_recebidas = {}
        self.reservas_coordenadas = {}
        self.filas_dos_trechos = {}
        self.avisos = {}
        self.maior_relogio = 0

        os.makedirs(pasta, exist_ok=True)
        self.caminho = os.path.join(pasta, "registro.jsonl")
        self.ler_registro()
        self.arquivo = open(self.caminho, "a", encoding="utf-8")
        self.arquivo.write("\n")
        self.arquivo.flush()

    def ler_registro(self):
        if not os.path.exists(self.caminho):
            return
        with open(self.caminho, encoding="utf-8") as arquivo, self.trava:
            for linha in arquivo:
                try:
                    evento = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                self.aplicar_evento(evento)

    def escrever_registro(self, evento):
        self.arquivo.write(json.dumps(evento, ensure_ascii=False) + "\n")
        self.arquivo.flush()
        os.fsync(self.arquivo.fileno())

    # grava no arquivo primeiro, muda a memoria depois
    def gravar(self, evento):
        self.escrever_registro(evento)
        self.aplicar_evento(evento)

    def aplicar_evento(self, evento):
        tipo = evento["tipo"]
        id_reserva = evento.get("id_reserva")

        if tipo == "usuario":
            self.usuarios[evento["nome"]] = evento["senha"]
        elif tipo == "carona":
            self.montar_carona(evento)
        elif tipo == "carona_cancelada":
            self.desativar_carona(evento["id_carona"])
        elif tipo == "assentos_segurados":
            self.reter(evento["trechos"])
            self.reservas_recebidas[id_reserva] = ficha_da_dona(
                id_reserva, PREPARADO, evento["trechos"], evento["coordenadora"])
        elif tipo == "confirmou":
            self.vender_reserva(id_reserva)
        elif tipo == "abortou":
            self.soltar_reserva(id_reserva)
        elif tipo == "cancelou":
            self.devolver_reserva(id_reserva)
        elif tipo == "coordenacao_inicio":
            momento = id_reserva.split("-", 1)[0]
            if momento.isdigit():
                self.maior_relogio = max(self.maior_relogio, int(momento))
            self.reservas_coordenadas[id_reserva] = ficha_da_coordenadora(
                id_reserva, evento["passageiro"], evento["itens"], evento["participantes"])
        elif tipo == "coordenacao_decisao":
            coordenacao = self.reservas_coordenadas[id_reserva]
            coordenacao["decisao"] = evento["decisao"]
            coordenacao["reserva"] = evento["reserva"]
            coordenacao["falta_avisar"] = set(coordenacao["participantes"])
        elif tipo == "coordenacao_cancelada":
            self.marcar_cancelada(id_reserva, evento["motivo"])
        elif tipo == "coordenacao_fim":
            self.reservas_coordenadas[id_reserva]["falta_avisar"] = set()

    # --- Usuários e avisos ---

    def autenticar(self, nome, senha_cifrada):
        with self.trava:
            senha_salva = self.usuarios.get(nome)
            if senha_salva is None:
                self.gravar({"tipo": "usuario", "nome": nome, "senha": senha_cifrada})
                return True
            return senha_salva == senha_cifrada

    def deixar_aviso(self, nome, texto):
        self.avisos.setdefault(nome, []).append(texto)

    def avisos_de(self, nome):
        with self.trava:
            return list(self.avisos.get(nome, []))

    # --- Caronas e trechos ---

    def montar_carona(self, evento):
        self.caronas[evento["id_carona"]] = dict(evento, cancelada=False)
        rota = evento["rota"]
        for posicao in range(len(rota) - 1):
            self.trechos[(evento["id_carona"], posicao)] = {
                "empresa": self.empresa,
                "id_carona": evento["id_carona"],
                "posicao": posicao,
                "origem": rota[posicao],
                "destino": rota[posicao + 1],
                "data": evento["data"],
                "horario": evento["horario"],
                "preco": float(evento["precos"][posicao]),
                "assentos": evento["assentos"],
                "livres": evento["assentos"],
                "retidos": 0,
                "cancelada": False,
            }

    def desativar_carona(self, id_carona):
        self.caronas[id_carona]["cancelada"] = True
        for trecho in self.trechos.values():
            if trecho["id_carona"] == id_carona:
                trecho["cancelada"] = True
        self.trava.notify_all()

    def publicar_carona(self, id_carona, motorista, rota, data, horario, assentos, precos):
        with self.trava:
            self.gravar({
                "tipo": "carona", "id_carona": id_carona, "motorista": motorista,
                "rota": rota, "data": data, "horario": horario,
                "assentos": assentos, "precos": precos,
            })

    def cancelar_carona(self, id_carona, motorista):
        with self.trava:
            carona = self.caronas.get(id_carona)
            if carona is None or carona["motorista"] != motorista or carona["cancelada"]:
                return "carona nao encontrada"
            if any(trecho["retidos"] for trecho in self.trechos_da_carona(id_carona)):
                return "ha uma reserva em andamento nessa carona, tente de novo em instantes"
            self.gravar({"tipo": "carona_cancelada", "id_carona": id_carona})
            return None

    def caronas_do_motorista(self, motorista):
        with self.trava:
            minhas = []
            for carona in self.caronas.values():
                if carona["motorista"] != motorista or carona["cancelada"]:
                    continue
                minhas.append({
                    "id": carona["id_carona"],
                    "rota": carona["rota"],
                    "data": carona["data"],
                    "horario": carona["horario"],
                    "assentos": carona["assentos"],
                    "trechos": self.trechos_da_carona(carona["id_carona"]),
                })
            return minhas

    def trechos_da_carona(self, id_carona):
        return [dict(t) for t in self.trechos.values() if t["id_carona"] == id_carona]

    def trechos_com_vaga(self, data):
        with self.trava:
            return [dict(t) for t in self.trechos.values()
                    if t["data"] == data and t["livres"] > 0 and not t["cancelada"]]

    def resumo_do_trecho(self, trecho_id):
        trecho = self.trechos[tuple(trecho_id)]
        return {
            "empresa": self.empresa,
            "id_carona": trecho["id_carona"],
            "posicao": trecho["posicao"],
            "origem": trecho["origem"],
            "destino": trecho["destino"],
            "data": trecho["data"],
            "preco": trecho["preco"],
        }

    # --- Assentos e fila (Lamport e Ricart-Agrawala) ---

    def reter(self, trechos_ids):
        for trecho_id in trechos_ids:
            self.trechos[tuple(trecho_id)]["retidos"] += 1

    def soltar(self, trechos_ids):
        for trecho_id in trechos_ids:
            self.trechos[tuple(trecho_id)]["retidos"] -= 1
        self.trava.notify_all()

    def vender(self, trechos_ids):
        for trecho_id in trechos_ids:
            trecho = self.trechos[tuple(trecho_id)]
            trecho["retidos"] -= 1
            trecho["livres"] -= 1
        self.trava.notify_all()

    # fila do trecho: passa o pedido de menor [relogio, empresa]
    def esperar_vez(self, id_reserva, prioridade, trecho_id, prazo_final):
        trecho = self.trechos[trecho_id]
        fila = self.filas_dos_trechos.setdefault(trecho_id, [])
        minha_vez = (tuple(prioridade), id_reserva)
        fila.append(minha_vez)
        try:
            while True:
                if self.estado_da_reserva(id_reserva) == ABORTADO:
                    return False, "reserva ja foi abortada"
                if trecho["cancelada"]:
                    return False, "a carona foi cancelada pelo motorista"
                if trecho["livres"] <= 0:
                    return False, f"sem vaga no trecho {trecho['origem']} -> {trecho['destino']}"
                sobra_assento = trecho["livres"] - trecho["retidos"] > 0
                if sobra_assento and minha_vez == min(fila):
                    self.reter([trecho_id])
                    return True, None
                espera_restante = prazo_final - time.monotonic()
                if espera_restante <= 0:
                    return False, f"trecho {trecho['origem']} -> {trecho['destino']} muito disputado"
                self.trava.wait(espera_restante)
        finally:
            fila.remove(minha_vez)
            self.trava.notify_all()

    # --- Reservas como participante (assentos desta empresa) ---

    def estado_da_reserva(self, id_reserva):
        reserva = self.reservas_recebidas.get(id_reserva)
        return reserva["estado"] if reserva else None

    # fase 1 do 2PC: segura todos os trechos pedidos, ou nenhum
    def preparar(self, id_reserva, prioridade, coordenadora, itens):
        trechos_ids = sorted({(item["id_carona"], item["posicao"]) for item in itens})
        prazo_final = time.monotonic() + ESPERA_MAX_NA_FILA

        with self.trava:
            ja_conhecida = self.estado_da_reserva(id_reserva)
            if ja_conhecida == ABORTADO:
                return False, "reserva ja foi abortada"
            if ja_conhecida is not None:
                segurados = self.reservas_recebidas[id_reserva]["trechos"]
                return True, [self.resumo_do_trecho(t) for t in segurados]

            if any(trecho_id not in self.trechos for trecho_id in trechos_ids):
                return False, "trecho inexistente"

            segurados = []
            for trecho_id in trechos_ids:
                deu_certo, motivo = self.esperar_vez(
                    id_reserva, prioridade, trecho_id, prazo_final)
                if not deu_certo:
                    self.soltar(segurados)
                    return False, motivo
                segurados.append(trecho_id)

            self.escrever_registro({"tipo": "assentos_segurados", "id_reserva": id_reserva,
                                    "coordenadora": coordenadora,
                                    "trechos": [list(t) for t in segurados]})
            self.reservas_recebidas[id_reserva] = ficha_da_dona(
                id_reserva, PREPARADO, segurados, coordenadora)
            return True, [self.resumo_do_trecho(t) for t in segurados]

    def vender_reserva(self, id_reserva):
        reserva = self.reservas_recebidas.get(id_reserva)
        if reserva is None or reserva["estado"] != PREPARADO:
            return
        self.vender(reserva["trechos"])
        reserva["estado"] = CONFIRMADO

    def soltar_reserva(self, id_reserva):
        reserva = self.reservas_recebidas.get(id_reserva)
        if reserva is None:
            # marca para recusar um preparar que chegue atrasado
            self.reservas_recebidas[id_reserva] = ficha_da_dona(id_reserva, ABORTADO)
        elif reserva["estado"] == PREPARADO:
            self.soltar(reserva["trechos"])
            reserva["estado"] = ABORTADO
        self.trava.notify_all()

    def devolver_reserva(self, id_reserva):
        reserva = self.reservas_recebidas.get(id_reserva)
        if reserva is None or reserva["estado"] not in (PREPARADO, CONFIRMADO):
            return
        for trecho_id in reserva["trechos"]:
            trecho = self.trechos[trecho_id]
            if reserva["estado"] == CONFIRMADO:
                trecho["livres"] += 1
            else:
                trecho["retidos"] -= 1
            if not trecho["cancelada"]:
                motorista = self.caronas[trecho["id_carona"]]["motorista"]
                self.deixar_aviso(motorista, f"um passageiro cancelou {descrever_trecho(trecho)}. "
                                             f"vagas livres: {trecho['livres']} de {trecho['assentos']}")
        reserva["estado"] = CANCELADO
        self.trava.notify_all()

    def confirmar(self, id_reserva):
        with self.trava:
            if self.estado_da_reserva(id_reserva) == PREPARADO:
                self.gravar({"tipo": "confirmou", "id_reserva": id_reserva})
            return self.estado_da_reserva(id_reserva) == CONFIRMADO

    def abortar(self, id_reserva):
        with self.trava:
            estado = self.estado_da_reserva(id_reserva)
            if estado is None or estado == PREPARADO:
                self.gravar({"tipo": "abortou", "id_reserva": id_reserva})
            return self.estado_da_reserva(id_reserva) == ABORTADO

    def cancelar_assentos(self, id_reserva):
        with self.trava:
            if self.estado_da_reserva(id_reserva) in (PREPARADO, CONFIRMADO):
                self.gravar({"tipo": "cancelou", "id_reserva": id_reserva})

    def reservas_sem_carona(self):
        with self.trava:
            achadas = []
            for reserva in self.reservas_recebidas.values():
                if reserva["estado"] != CONFIRMADO:
                    continue
                for id_carona, _ in reserva["trechos"]:
                    carona = self.caronas[id_carona]
                    if carona["cancelada"]:
                        achadas.append((reserva["id_reserva"], reserva["coordenadora"],
                                        descrever_carona(carona)))
                        break
            return achadas

    def retencoes_vencidas(self):
        agora = time.monotonic()
        with self.trava:
            return [dict(r) for r in self.reservas_recebidas.values()
                    if r["estado"] == PREPARADO and r["vence_em"] <= agora]

    def adiar_vencimento(self, id_reserva):
        with self.trava:
            if self.estado_da_reserva(id_reserva) == PREPARADO:
                reserva = self.reservas_recebidas[id_reserva]
                reserva["vence_em"] = time.monotonic() + PRAZO_DA_RETENCAO

    # --- Reservas como coordenadora (as que esta empresa conduz) ---

    def iniciar_coordenacao(self, id_reserva, passageiro, itens, participantes):
        with self.trava:
            self.gravar({
                "tipo": "coordenacao_inicio", "id_reserva": id_reserva,
                "passageiro": passageiro, "itens": itens, "participantes": participantes,
            })

    # a decisao vai para o disco antes de avisar alguem, e nunca muda
    def decidir(self, id_reserva, decisao, reserva):
        with self.trava:
            coordenacao = self.reservas_coordenadas[id_reserva]
            if coordenacao["decisao"] is not None:
                return coordenacao["decisao"]
            self.gravar({"tipo": "coordenacao_decisao", "id_reserva": id_reserva,
                         "decisao": decisao, "reserva": reserva})
            return decisao

    def marcar_cancelada(self, id_reserva, motivo):
        coordenacao = self.reservas_coordenadas[id_reserva]
        coordenacao["cancelada"] = True
        coordenacao["falta_avisar"] = set(coordenacao["participantes"])
        if motivo:
            self.deixar_aviso(coordenacao["passageiro"],
                              f"sua reserva {id_reserva} foi cancelada: {motivo}")

    def cancelar_coordenacao(self, id_reserva, passageiro=None, motivo=None):
        with self.trava:
            coordenacao = self.reservas_coordenadas.get(id_reserva)
            if coordenacao is None or coordenacao["decisao"] != COMMIT:
                return "reserva nao encontrada"
            if passageiro is not None and coordenacao["passageiro"] != passageiro:
                return "reserva nao encontrada"
            if coordenacao["cancelada"]:
                return "reserva ja estava cancelada"
            self.gravar({"tipo": "coordenacao_cancelada", "id_reserva": id_reserva,
                         "motivo": motivo})
            return None

    def calcular_aviso(self, coordenacao):
        if coordenacao["decisao"] is None:
            return None
        if coordenacao["cancelada"]:
            return "cancelar"
        return "confirmar" if coordenacao["decisao"] == COMMIT else "abortar"

    def aviso_a_entregar(self, id_reserva):
        with self.trava:
            return self.calcular_aviso(self.reservas_coordenadas[id_reserva])

    def marcar_avisada(self, id_reserva, empresa, acao):
        with self.trava:
            coordenacao = self.reservas_coordenadas[id_reserva]
            # aviso de antes de um cancelamento nao conta
            if self.calcular_aviso(coordenacao) != acao:
                return
            if empresa not in coordenacao["falta_avisar"]:
                return
            coordenacao["falta_avisar"].discard(empresa)
            if not coordenacao["falta_avisar"]:
                self.gravar({"tipo": "coordenacao_fim", "id_reserva": id_reserva})

    def decisao_da_reserva(self, id_reserva):
        with self.trava:
            coordenacao = self.reservas_coordenadas.get(id_reserva)
            if coordenacao is None:
                return ABORT
            return coordenacao["decisao"] or PENDENTE

    def sem_decisao(self):
        with self.trava:
            return [c["id_reserva"] for c in self.reservas_coordenadas.values()
                    if c["decisao"] is None]

    def avisos_pendentes(self):
        with self.trava:
            return [(c["id_reserva"], sorted(c["falta_avisar"]))
                    for c in self.reservas_coordenadas.values()
                    if c["decisao"] is not None and c["falta_avisar"]]

    def quem_participa(self, id_reserva):
        with self.trava:
            return list(self.reservas_coordenadas[id_reserva]["participantes"])

    def reservas_ativas(self, passageiro):
        with self.trava:
            return [c["reserva"] for c in self.reservas_coordenadas.values()
                    if c["decisao"] == COMMIT and not c["cancelada"]
                    and c["passageiro"] == passageiro]

    # --- Para os testes ---

    def auditoria(self):
        with self.trava:
            return {
                "empresa": self.empresa,
                "trechos": [dict(t) for t in self.trechos.values()],
                "reservas_recebidas": {
                    id_reserva: r["estado"]
                    for id_reserva, r in self.reservas_recebidas.items()
                },
                "reservas_coordenadas": {
                    id_reserva: {
                        "decisao": c["decisao"],
                        "cancelada": c["cancelada"],
                        "participantes": c["participantes"],
                        "itens": c["itens"],
                        "falta_avisar": sorted(c["falta_avisar"]),
                    }
                    for id_reserva, c in self.reservas_coordenadas.items()
                },
            }
