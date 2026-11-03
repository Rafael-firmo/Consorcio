# Busca de itinerarios: cidades sao nos, trechos sao arestas.

MAX_CONEXOES = 4


def saidas_por_cidade(trechos):
    saidas = {}
    for trecho in trechos:
        saidas.setdefault(trecho["origem"], []).append(trecho)
    return saidas


def custo(caminho):
    return (len(caminho), sum(t["preco"] for t in caminho))


# DFS sem repetir cidade; mais curtos e mais baratos primeiro
def buscar_itinerarios(trechos, origem, destino):
    if origem == destino:
        return []

    saidas = saidas_por_cidade(trechos)
    achados = []

    def explorar(cidade, caminho, visitadas):
        if cidade == destino:
            achados.append(list(caminho))
            return
        if len(caminho) >= MAX_CONEXOES:
            return
        for trecho in saidas.get(cidade, []):
            proxima = trecho["destino"]
            if proxima in visitadas:
                continue
            caminho.append(trecho)
            visitadas.add(proxima)
            explorar(proxima, caminho, visitadas)
            visitadas.remove(proxima)
            caminho.pop()

    explorar(origem, [], {origem})
    achados.sort(key=custo)
    return achados
