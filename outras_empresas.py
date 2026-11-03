# Pedidos HTTP desta empresa para as outras.

import requests

PRAZO_PADRAO = 3.0


# a outra nao respondeu: caiu, esta lenta ou a rede falhou
class NaoRespondeu(Exception):
    pass


class OutrasEmpresas:
    def __init__(self, relogio, enderecos):
        self.relogio = relogio
        self.enderecos = enderecos

    def nomes(self):
        return list(self.enderecos)

    def pedir(self, empresa, metodo, caminho, corpo=None, params=None, prazo=PRAZO_PADRAO):
        url = self.enderecos[empresa] + caminho
        cabecalhos = {"X-Relogio": str(self.relogio.ao_enviar())}
        try:
            resposta = requests.request(metodo, url, json=corpo, params=params,
                                        headers=cabecalhos, timeout=prazo)
        except requests.RequestException as erro:
            raise NaoRespondeu(f"{empresa}: {erro}")

        self.relogio.ao_receber(resposta.headers.get("X-Relogio"))
        try:
            return resposta.status_code, resposta.json()
        except ValueError:
            return resposta.status_code, {}
