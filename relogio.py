# Relogio de Lamport.

import threading


def numero_ou_zero(texto):
    try:
        return int(texto)
    except (TypeError, ValueError):
        return 0


class Relogio:
    def __init__(self):
        self.valor = 0
        self.trava = threading.Lock()

    # ao enviar: soma 1
    def ao_enviar(self):
        with self.trava:
            self.valor += 1
            return self.valor

    # ao receber: maior entre o meu e o recebido, mais 1
    def ao_receber(self, valor_recebido):
        with self.trava:
            self.valor = max(self.valor, numero_ou_zero(valor_recebido)) + 1
            return self.valor

    def atual(self):
        with self.trava:
            return self.valor
