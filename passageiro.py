# Cliente do passageiro.

import cliente


def mostrar_itinerario(numero, itinerario):
    print(f"  [{numero}] R$ {itinerario['preco_total']:.2f}, {itinerario['conexoes']} trecho(s)")
    for trecho in itinerario["trechos"]:
        print(f"        {trecho['origem']} -> {trecho['destino']}  "
              f"({trecho['empresa']}, {trecho['horario']}, {trecho['livres']} livres)")


def buscar_e_reservar(conexao):
    origem = input("origem: ").strip()
    destino = input("destino: ").strip()
    data = input("data (DD/MM/AAAA): ").strip()
    resultado = conexao.pedir("GET", "/api/itinerarios",
                              params={"origem": origem, "destino": destino, "data": data})

    if resultado["empresas_fora_do_ar"]:
        print(f"  aviso: sem resposta de {', '.join(resultado['empresas_fora_do_ar'])}")
    itinerarios = resultado["itinerarios"]
    if not itinerarios:
        print("  nenhum itinerario encontrado")
        return
    for numero, itinerario in enumerate(itinerarios, 1):
        mostrar_itinerario(numero, itinerario)

    escolhido = cliente.escolher(itinerarios, "reservar qual? (enter para voltar): ")
    if escolhido is None:
        return
    corpo = {"trechos": cliente.trechos_para_reservar(escolhido["trechos"])}
    reserva = conexao.pedir("POST", "/api/reservas", corpo)
    print(f"  reserva confirmada: {reserva['id']}  total R$ {reserva['preco_total']:.2f}")


def listar_minhas_reservas(conexao):
    reservas = conexao.pedir("GET", "/api/reservas")["reservas"]
    if not reservas:
        print("  nenhuma reserva")
    for numero, reserva in enumerate(reservas, 1):
        print(f"  [{numero}] {reserva['id']}  R$ {reserva['preco_total']:.2f}")
        for trecho in reserva["trechos"]:
            print(f"        {trecho['origem']} -> {trecho['destino']}  ({trecho['empresa']})")
    return reservas


def cancelar_reserva(conexao):
    reservas = listar_minhas_reservas(conexao)
    if not reservas:
        return
    reserva = cliente.escolher(reservas, "cancelar qual? (enter para voltar): ")
    if reserva is None:
        return
    resposta = conexao.pedir("POST", f"/api/reservas/{reserva['id']}/cancelar")
    print(f"  {resposta['mensagem']}")


if __name__ == "__main__":
    cliente.iniciar_cliente([
        ("buscar e reservar", buscar_e_reservar),
        ("minhas reservas", listar_minhas_reservas),
        ("cancelar reserva", cancelar_reserva),
    ])
