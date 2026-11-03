# VaiJunto Consórcio · Problema 2 (TEC502)

Sistema distribuído de caronas compartilhadas entre três empresas. Cada empresa
roda o seu próprio servidor, e os servidores se comunicam por API REST. Um
itinerário pode misturar trechos de várias empresas, e a reserva é confirmada em
todas elas ou em nenhuma, pelo protocolo de duas fases (2PC). Não há servidor
central, coordenador fixo nem banco de dados compartilhado.

A especificação da API e o diagrama de sequência estão em [docs/API.md](docs/API.md).

---

## Sumário

1. [Arquivos do projeto](#1-arquivos-do-projeto)
2. [Requisitos](#2-requisitos)
3. [Três empresas em um computador](#3-três-empresas-em-um-computador)
4. [Uma empresa por computador](#4-uma-empresa-por-computador)
5. [Clientes: motorista e passageiro](#5-clientes-motorista-e-passageiro)
6. [Simulador de carga](#6-simulador-de-carga)
7. [Derrubar e recuperar uma empresa](#7-derrubar-e-recuperar-uma-empresa)
8. [Testes automatizados](#8-testes-automatizados)
9. [Registro em disco](#9-registro-em-disco)
10. [Variáveis de ambiente](#10-variáveis-de-ambiente)
11. [Erros comuns](#11-erros-comuns)

---

## 1. Arquivos do projeto

| Arquivo | O que faz |
|---|---|
| `servidor.py` | Servidor de uma empresa: rotas `/api` (clientes) e `/consorcio` (outras empresas) |
| `armazem.py` | Estado da empresa (usuários, caronas, reservas), fila dos assentos e registro em disco |
| `reservas.py` | Coordenação do 2PC, recuperação ao ligar, entregador de avisos e vigia de assentos retidos |
| `outras_empresas.py` | Envio das requisições HTTP às outras empresas, com prazo e relógio |
| `relogio.py` | Relógio lógico de Lamport |
| `grafo.py` | Busca de itinerários (veio do Problema 1) |
| `validacao.py` | Validação dos dados recebidos pela API |
| `cliente.py` | Base dos clientes de terminal: conexão, login e menu |
| `motorista.py` · `passageiro.py` | Clientes de terminal |
| `simulador.py` | Passageiros automáticos para gerar carga |
| `testes.py` | 9 testes automatizados com carga e quedas |
| `Dockerfile` · `docker-compose.yml` | Imagem do sistema e as três empresas em uma máquina |
| `docs/API.md` | Especificação da API e diagrama de sequência |

---

## 2. Requisitos

- **Docker** (recomendado). Todos os comandos abaixo usam Docker.
- Opcional, para rodar sem Docker: **Python 3.10+** e `pip install -r requirements.txt`.

No Linux, se o Docker pedir permissão, coloque `sudo` na frente dos comandos.

Construa a imagem uma vez, dentro da pasta do projeto, em cada computador que for usar:

```bash
docker build -t consorcio .
```

---

## 3. Três empresas em um computador

```bash
docker compose up --build
```

| Empresa | Endereço |
|---|---|
| vaijunto | `http://127.0.0.1:5001` |
| empresab | `http://127.0.0.1:5002` |
| empresac | `http://127.0.0.1:5003` |

Para desligar: `Ctrl + C` e depois `docker compose down`.

<details>
<summary>Sem Docker (três terminais)</summary>

Linux:

```bash
EMPRESA=vaijunto PORTA=5001 PARES=empresab=http://127.0.0.1:5002,empresac=http://127.0.0.1:5003 python3 servidor.py
EMPRESA=empresab PORTA=5002 PARES=vaijunto=http://127.0.0.1:5001,empresac=http://127.0.0.1:5003 python3 servidor.py
EMPRESA=empresac PORTA=5003 PARES=vaijunto=http://127.0.0.1:5001,empresab=http://127.0.0.1:5002 python3 servidor.py
```

Windows (PowerShell), exemplo da vaijunto:

```powershell
$env:EMPRESA="vaijunto"; $env:PORTA="5001"; $env:PARES="empresab=http://127.0.0.1:5002,empresac=http://127.0.0.1:5003"; python servidor.py
```

</details>

---

## 4. Uma empresa por computador

Cada computador roda uma empresa em um contêiner.

**Passo 1. Em cada computador**, entre na pasta do projeto, construa a imagem e anote o IP:

```bash
docker build -t consorcio .
hostname -I
```

O IP é o primeiro número mostrado (os endereços `172.17...`, `172.18...` e
`172.19...` são redes internas do Docker).

**Passo 2. Ligue a empresa de cada computador.** Troque `IP_VAIJUNTO`, `IP_B` e
`IP_C` pelos IPs anotados. Em cada um, `PARES` lista as **outras duas** empresas.

Computador da **vaijunto**:

```bash
docker run --name vaijunto -p 5001:5001 -v "$(pwd)/dados/vaijunto:/dados" -e EMPRESA=vaijunto -e PARES=empresab=http://IP_B:5001,empresac=http://IP_C:5001 consorcio
```

Computador da **empresab**:

```bash
docker run --name empresab -p 5001:5001 -v "$(pwd)/dados/empresab:/dados" -e EMPRESA=empresab -e PARES=vaijunto=http://IP_VAIJUNTO:5001,empresac=http://IP_C:5001 consorcio
```

Computador da **empresac**:

```bash
docker run --name empresac -p 5001:5001 -v "$(pwd)/dados/empresac:/dados" -e EMPRESA=empresac -e PARES=vaijunto=http://IP_VAIJUNTO:5001,empresab=http://IP_B:5001 consorcio
```

Ao ligar, a empresa mostra quem ela conhece. Confira:

```
empresa empresab na porta 5001, outras: ['vaijunto', 'empresac']
```

**Passo 3. Confira a rede** a partir de qualquer computador:

```bash
curl http://IP_B:5001/consorcio/auditoria
```

Se não responder, o problema é de rede (IP errado ou firewall). No Linux, libere a
porta com `sudo ufw allow 5001`.

---

## 5. Clientes: motorista e passageiro

Cada cliente fala apenas com a própria empresa. O primeiro login com um nome
novo cadastra o usuário.

**No mesmo computador da empresa** (funciona em qualquer um dos dois modos):

```bash
docker run -it --rm --network host -e EMPRESA_URL=http://127.0.0.1:5001 consorcio python motorista.py
docker run -it --rm --network host -e EMPRESA_URL=http://127.0.0.1:5001 consorcio python passageiro.py
```

No modo de um computador só, a porta escolhe a empresa: `5001` vaijunto,
`5002` empresab, `5003` empresac.

**De outro computador**, use o IP da empresa:

```bash
docker run -it --rm -e EMPRESA_URL=http://IP_B:5001 consorcio python motorista.py
```

O endereço leva **um** `http://` só, e o `-it` é obrigatório para o menu
receber o teclado. Não use as setas do teclado no login.

---

## 6. Simulador de carga

Vários passageiros automáticos, cada um em uma thread, buscando e reservando
sem parar nas três empresas. É um cliente: só fala com as empresas pelo `/api`.

Uma empresa por computador:

```bash
docker run --rm consorcio python simulador.py --empresas http://IP_VAIJUNTO:5001,http://IP_B:5001,http://IP_C:5001 --semear 5000 --passageiros 30 --duracao 120
```

Três empresas em um computador:

```bash
docker run --rm --network host consorcio python simulador.py --empresas http://127.0.0.1:5001,http://127.0.0.1:5002,http://127.0.0.1:5003 --semear 5000 --passageiros 30 --duracao 120
```

| Opção | Significado |
|---|---|
| `--empresas` | URLs das empresas, separadas por vírgula |
| `--semear N` | Publica antes caronas encadeadas com N assentos: Salvador → Feira de Santana → Vitória da Conquista → Montes Claros |
| `--passageiros` | Quantos passageiros simultâneos (padrão 20) |
| `--duracao` | Segundos de carga (padrão 15) |

Ao final, mostra quantas reservas deram certo, quantas foram recusadas e o tempo
médio de uma reserva.

---

## 7. Derrubar e recuperar uma empresa

No computador da empresa, com o simulador rodando:

```bash
docker kill empresab
```

`docker kill` é uma queda abrupta, sem aviso. As outras empresas continuam
operando; só os trechos da empresa fora do ar ficam indisponíveis.

Para religar:

```bash
docker start -a empresab
```

Ao subir, a empresa relê o seu registro, dá ABORT nas reservas que coordenava e
que ficaram sem decisão, retoma os avisos pendentes e volta a atender.

No modo de um computador só, o compose dá aos contêineres nomes como
`<pasta>-empresab-1`, em que `<pasta>` é o nome da pasta do projeto. Confira o
nome exato com `docker ps`.

---

## 8. Testes automatizados

```bash
docker run --rm consorcio python testes.py
```

Os testes sobem três empresas sozinhos dentro do contêiner (portas 5900 em
diante), por isso funcionam em qualquer computador, sem depender das empresas
já ligadas.

| Grupo | Testes |
|---|---|
| Funcionamento normal | Reserva entre três empresas · passageiro cancela · motorista cancela a carona |
| Disputa | Vários passageiros, em várias empresas, pelo último assento: só um consegue |
| Quedas | Coordenadora cai antes da decisão · coordenadora cai depois da decisão · carga com queda de participante · carga com queda da coordenadora · cancelamento com a coordenadora fora do ar |

Ao final de cada teste, a auditoria das três empresas confere que nenhum assento
foi vendido duas vezes, nenhuma reserva ficou confirmada em uma empresa e
abortada em outra, e nenhum assento ficou retido.

---

## 9. Registro em disco

Cada empresa grava tudo o que acontece em `registro.jsonl`, uma linha por evento,
antes de responder. É esse arquivo que ela relê ao voltar de uma queda.

| Como a empresa foi ligada | Onde fica o registro |
|---|---|
| `docker run` com `-v "$(pwd)/dados/<empresa>:/dados"` | `dados/<empresa>/registro.jsonl` na pasta do projeto |
| `docker compose up` | `dados/<empresa>/registro.jsonl` na pasta do projeto |
| Sem Docker | `dados/<empresa>/registro.jsonl` na pasta do projeto |

O arquivo só aparece depois do primeiro evento daquela empresa (login, carona
publicada ou reserva). Para acompanhar ao vivo:

```bash
tail -f dados/empresab/registro.jsonl
```

Para começar do zero, desligue a empresa e apague a pasta `dados/<empresa>`.

---

## 10. Variáveis de ambiente

| Variável | Padrão | Para que serve |
|---|---|---|
| `EMPRESA` | `vaijunto` | Nome desta empresa |
| `PORTA` | `5001` | Porta do servidor |
| `PARES` | (vazio) | As outras empresas: `nome=http://ip:porta,nome=http://ip:porta` |
| `DADOS` | `./dados/<empresa>` (`/dados` no Docker) | Pasta do registro em disco |
| `EMPRESA_URL` | `http://127.0.0.1:5001` | Empresa a que o cliente se conecta |
| `PRAZO_RETENCAO` | `8` | Segundos sem notícia até a empresa perguntar à coordenadora sobre um assento segurado |
| `ESPERA_MAX` | `2` | Segundos máximos de espera na fila de um trecho disputado |
| `PERMITIR_INJECAO` | (desligado) | `1` permite que os testes derrubem o servidor de propósito |

---

## 11. Erros comuns

| Erro | Causa e solução |
|---|---|
| `nao consegui falar com http://...` | Empresa fora do ar, IP errado ou firewall. Confira com `curl .../consorcio/auditoria` |
| `nao consegui falar com http://http://...` | `http://` repetido no endereço; deixe um só |
| `nao consegui falar com http://127.0.0.1:...` em contêiner | Faltou `--network host` no `docker run` do cliente |
| `outras:` mostra nome errado ao ligar | Erro de digitação em `PARES`; apague o contêiner e rode o comando de novo |
| Duas empresas com o mesmo nome | Cada computador deve rodar uma empresa diferente; confira o `--name` e o `EMPRESA` |
| `name already in use` | Já existe um contêiner com esse nome: `docker rm -f <nome>` |
| `port is already allocated` | Algo já usa a porta (por exemplo, o compose): `docker compose down` ou `docker rm -f <nome>` |
| `^[[200~` antes do comando colado | Lixo da colagem; apague esses caracteres antes de apertar Enter |
| O menu do cliente não recebe o teclado | Faltou `-it` no `docker run` |
| `401` / "o servidor reiniciou, entre de novo" | O login fica só na memória; entre outra vez |
| A busca mostra `empresas_fora_do_ar` | Uma empresa não respondeu no prazo; a busca segue sem ela |
| `python: comando não encontrado` | Use os comandos com Docker, ou `python3` |
| `docker: permissão negada` | No Linux, use `sudo` na frente do comando |
