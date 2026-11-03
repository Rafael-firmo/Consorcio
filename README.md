# Consórcio de caronas (VaiJunto, Problema 2)

Cada empresa do consórcio roda o seu próprio servidor. Os servidores se falam por
API REST e confirmam itinerários que misturam empresas em duas fases (2PC), sem
servidor central, sem coordenador fixo e sem banco compartilhado.

A especificação da API e o diagrama de sequência estão em [docs/API.md](docs/API.md).

## Requisitos

- **Docker** (jeito recomendado), ou
- **Python 3.10+** e as bibliotecas do `requirements.txt` (Flask e requests):

```bash
pip install -r requirements.txt
```

## 1. Três empresas numa máquina só

Com Docker:

```bash
docker compose up --build
```

As empresas ficam em `http://localhost:5001` (vaijunto), `:5002` (empresab) e
`:5003` (empresac). Os dados de cada uma ficam na pasta `dados/`.

Sem Docker, em três terminais (Linux e macOS):

```bash
EMPRESA=vaijunto PORTA=5001 PARES=empresab=http://127.0.0.1:5002,empresac=http://127.0.0.1:5003 python servidor.py
EMPRESA=empresab PORTA=5002 PARES=vaijunto=http://127.0.0.1:5001,empresac=http://127.0.0.1:5003 python servidor.py
EMPRESA=empresac PORTA=5003 PARES=vaijunto=http://127.0.0.1:5001,empresab=http://127.0.0.1:5002 python servidor.py
```

No Windows (PowerShell), um terminal por empresa:

```powershell
$env:EMPRESA="vaijunto"; $env:PORTA="5001"; $env:PARES="empresab=http://127.0.0.1:5002,empresac=http://127.0.0.1:5003"; python servidor.py
```

(troque os valores nas outras duas, como nas linhas acima).

## 2. Uma empresa por computador (laboratório)

Cada empresa roda em um contêiner, em um computador diferente.

**Antes de começar**, nos três computadores:

1. Descubra o IP de cada um (`hostname -I` no Linux, `ipconfig` no Windows) e anote.
2. Libere a **porta 5001** no firewall de cada um.
3. Copie esta pasta para os três e construa a imagem:

```bash
docker build -t consorcio .
```

**Computador da vaijunto** (troque `IP_B` e `IP_C` pelos IPs reais):

```bash
docker run --name vaijunto -p 5001:5001 -v vaijunto_dados:/dados \
  -e EMPRESA=vaijunto \
  -e PARES=empresab=http://IP_B:5001,empresac=http://IP_C:5001 \
  consorcio
```

**Computador da empresab:**

```bash
docker run --name empresab -p 5001:5001 -v empresab_dados:/dados \
  -e EMPRESA=empresab \
  -e PARES=vaijunto=http://IP_VAIJUNTO:5001,empresac=http://IP_C:5001 \
  consorcio
```

**Computador da empresac:**

```bash
docker run --name empresac -p 5001:5001 -v empresac_dados:/dados \
  -e EMPRESA=empresac \
  -e PARES=vaijunto=http://IP_VAIJUNTO:5001,empresab=http://IP_B:5001 \
  consorcio
```

O volume (`-v ..._dados:/dados`) guarda o registro da empresa. Com ele, os dados
voltam mesmo se o contêiner for apagado e criado de novo.

Para conferir a rede, a partir de qualquer computador:

```bash
curl http://IP_DA_EMPRESA:5001/consorcio/auditoria
```

Se não responder, o problema é de rede (IP errado ou firewall), não do sistema.

### Derrubar e recuperar uma empresa (durante a apresentação)

```bash
docker kill empresab      # queda abrupta, sem aviso
docker start empresab     # volta e relê o próprio registro
```

`docker stop` e `docker rm` também funcionam; o volume mantém os dados.

## 3. Clientes (motorista e passageiro)

Cada cliente fala só com a própria empresa. Troque a URL para escolher a empresa:

```bash
EMPRESA_URL=http://IP_VAIJUNTO:5001 python motorista.py
EMPRESA_URL=http://IP_VAIJUNTO:5001 python passageiro.py
```

No PowerShell: `$env:EMPRESA_URL="http://IP_VAIJUNTO:5001"; python passageiro.py`.

Com Docker (o `-it` é obrigatório para o menu receber o teclado):

```bash
docker run -it --rm -e EMPRESA_URL=http://IP_VAIJUNTO:5001 consorcio python motorista.py
docker run -it --rm -e EMPRESA_URL=http://IP_VAIJUNTO:5001 consorcio python passageiro.py
```

O primeiro login de um nome cadastra o usuário.

## 4. Simulador de passageiros (carga)

```bash
python simulador.py --empresas http://IP_VAIJUNTO:5001,http://IP_B:5001,http://IP_C:5001 \
  --semear 5000 --passageiros 30 --duracao 20
```

`--semear N` publica caronas de exemplo com N assentos antes de começar
(Salvador → Feira de Santana, Feira de Santana → Vitória da Conquista,
Vitória da Conquista → Montes Claros). Ao final mostra quantas reservas deram
certo, quantas foram recusadas e o tempo de uma reserva.

## 5. Testes automatizados

Sobem três empresas sozinhos (processos locais, portas 5900 em diante), geram
carga, derrubam empresas no meio das operações e conferem ao final que nenhum
assento foi vendido duas vezes, nenhuma reserva ficou pela metade e nenhum
assento ficou bloqueado:

```bash
python testes.py
```

Ou em contêiner:

```bash
docker run --rm consorcio python testes.py
```

## Variáveis de ambiente

| Variável | Padrão | Para que serve |
|---|---|---|
| `EMPRESA` | `vaijunto` | nome desta empresa |
| `PORTA` | `5001` | porta do servidor |
| `PARES` | (vazio) | as outras empresas: `nome=http://ip:porta,nome=http://ip:porta` |
| `DADOS` | `./dados/<empresa>` (`/dados` no Docker) | pasta do registro em disco |
| `EMPRESA_URL` | `http://127.0.0.1:5001` | empresa a que o cliente se conecta |
| `PRAZO_RETENCAO` | `8` | segundos até uma empresa perguntar à coordenadora sobre um assento segurado |
| `ESPERA_MAX` | `2` | segundos de espera na fila de um trecho disputado |
| `PERMITIR_INJECAO` | (desligado) | `1` deixa os testes derrubarem o servidor de propósito |

## Erros comuns

| Erro | Solução |
|---|---|
| `nao consegui falar com http://...` | Empresa fora do ar, IP errado ou firewall bloqueando a porta |
| A busca mostra `empresas_fora_do_ar` | A outra empresa não respondeu no prazo; a busca segue sem ela |
| `401` / "o servidor reiniciou, entre de novo" | O login fica só na memória; entre outra vez |
| O menu do cliente não recebe o teclado no Docker | Falta `-it` no `docker run` |
| `address already in use` | Já há algo na porta; mude `PORTA` |
| `docker: command not found` / permissão negada | No Linux, use `sudo` na frente do comando |
