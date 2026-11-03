# VaiJunto Consórcio · Problema 2

Cada empresa roda o seu próprio servidor. Os servidores se comunicam por API REST
e confirmam as reservas entre empresas com o protocolo de duas fases (2PC).

A especificação da API está em [docs/API.md](docs/API.md).

## 1. Montar a imagem

Em cada computador, dentro da pasta do projeto:

```bash
docker build -t consorcio .
```

## 2. Subir as empresas

Uma empresa por computador. Descubra o IP de cada máquina com `hostname -I`
(o primeiro número mostrado).

Nos comandos abaixo, troque:

- `IP_VAIJUNTO` pelo IP da máquina da vaijunto
- `IP_B` pelo IP da máquina da empresab
- `IP_C` pelo IP da máquina da empresac

**Máquina da vaijunto:**

```bash
docker run --name vaijunto -p 5001:5001 -v vaijunto_dados:/dados -e EMPRESA=vaijunto -e PARES=empresab=http://IP_B:5001,empresac=http://IP_C:5001 consorcio
```

**Máquina da empresab:**

```bash
docker run --name empresab -p 5001:5001 -v empresab_dados:/dados -e EMPRESA=empresab -e PARES=vaijunto=http://IP_VAIJUNTO:5001,empresac=http://IP_C:5001 consorcio
```

**Máquina da empresac:**

```bash
docker run --name empresac -p 5001:5001 -v empresac_dados:/dados -e EMPRESA=empresac -e PARES=vaijunto=http://IP_VAIJUNTO:5001,empresab=http://IP_B:5001 consorcio
```

Para testar as três empresas em uma máquina só:

```bash
docker compose up --build
```

## 3. Clientes

Troque `IP_DA_EMPRESA` pelo IP da máquina da empresa à qual o cliente vai se conectar.

```bash
docker run -it --rm -e EMPRESA_URL=http://IP_DA_EMPRESA:5001 consorcio python motorista.py
docker run -it --rm -e EMPRESA_URL=http://IP_DA_EMPRESA:5001 consorcio python passageiro.py
```

O primeiro login com um nome novo cadastra o usuário.

## 4. Simulador de carga

```bash
docker run --rm consorcio python simulador.py --empresas http://IP_VAIJUNTO:5001,http://IP_B:5001,http://IP_C:5001 --semear 5000 --passageiros 30 --duracao 120
```

## 5. Derrubar e religar um servidor

Na máquina da empresa (exemplo com a empresab):

```bash
docker kill empresab
docker start -a empresab
```

`docker kill` derruba o servidor sem aviso. Ao religar, ele relê o próprio registro
e volta com os dados que tinha.

## 6. Testes

```bash
docker run --rm consorcio python testes.py
```
