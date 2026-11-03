# Cliente do motorista.

import cliente


def ler_lista(pergunta):
    return [parte.strip() for parte in input(pergunta).split(",") if parte.strip()]


def publicar_carona(conexao):
    rota = ler_lista("rota (cidades separadas por virgula): ")
    data = input("data (DD/MM/AAAA): ").strip()
    horario = input("horario (HH:MM): ").strip()
    try:
        assentos = int(input("assentos: "))
        precos = [float(p) for p in ler_lista("preco de cada trecho (separados por virgula): ")]
    except ValueError:
        print("  numero invalido")
        return

    dados = conexao.pedir("POST", "/api/caronas", {
        "rota": rota, "data": data, "horario": horario,
        "assentos": assentos, "precos": precos,
    })
    print(f"  carona publicada: {dados['id']}")


def listar_minhas_caronas(conexao):
    caronas = conexao.pedir("GET", "/api/caronas")["caronas"]
    if not caronas:
        print("  voce nao tem caronas")
    for numero, carona in enumerate(caronas, 1):
        print(f"  [{numero}] {' -> '.join(carona['rota'])}  {carona['data']} {carona['horario']}")
        for trecho in carona["trechos"]:
            print(f"        {trecho['origem']} -> {trecho['destino']}: "
                  f"{trecho['livres']}/{trecho['assentos']} livres, R$ {trecho['preco']:.2f}")
    return caronas


def cancelar_carona(conexao):
    caronas = listar_minhas_caronas(conexao)
    if not caronas:
        return
    carona = cliente.escolher(caronas, "cancelar qual? (enter para voltar): ")
    if carona is None:
        return
    resposta = conexao.pedir("POST", f"/api/caronas/{carona['id']}/cancelar")
    print(f"  {resposta['mensagem']}")


if __name__ == "__main__":
    cliente.iniciar_cliente([
        ("publicar carona", publicar_carona),
        ("minhas caronas", listar_minhas_caronas),
        ("cancelar carona", cancelar_carona),
    ])
