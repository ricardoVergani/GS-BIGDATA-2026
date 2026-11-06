"""
GS 2026.2 · CitizenTech · Componente Dados
DAG de coleta do "Alerta de Chuva Forte e Alagamento na Grande SP".

Fontes:
  1. Open-Meteo (/v1/forecast)  -> chegada/clima/clima_<ds>.json      (real, sem chave)
  2. IBGE (API de agregados v3) -> chegada/ibge/ibge_<ds>.json        (real, sem chave)
  3. Relatos de alagamento      -> chegada/relatos/relatos_<ds>.json  (SIMULADO, gerador neste arquivo)

Formato dos arquivos: JSON Lines (um objeto JSON por linha), lido direto pelo Auto Loader.
Fluxo: inicio >> [coletar_clima, coletar_ibge] ; coletar_clima >> gerar_relatos ;
       [coletar_ibge, gerar_relatos] >> conferir_chegada
"""
from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pendulum
import requests
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG, Variable

CHEGADA = Path("/opt/airflow/chegada")  # pasta montada no container (docker-compose)

# Municípios da Grande SP monitorados: (código IBGE, nome, latitude, longitude)
MUNICIPIOS = [
    (3550308, "São Paulo", -23.5505, -46.6333),
    (3518800, "Guarulhos", -23.4538, -46.5333),
    (3534401, "Osasco", -23.5329, -46.7920),
    (3547809, "Santo André", -23.6639, -46.5383),
    (3548708, "São Bernardo do Campo", -23.6914, -46.5646),
    (3548807, "São Caetano do Sul", -23.6229, -46.5548),
    (3513801, "Diadema", -23.6813, -46.6205),
    (3529401, "Mauá", -23.6677, -46.4613),
    (3505708, "Barueri", -23.5057, -46.8790),
    (3552809, "Taboão da Serra", -23.6019, -46.7526),
]

VARIAVEIS_CLIMA = [
    "precipitation",          # chuva total na hora (mm)
    "temperature_2m",         # °C
    "relative_humidity_2m",   # %
    "wind_gusts_10m",         # rajada de vento (km/h)
    "weather_code",           # código WMO do tempo
]


# ----------------------------------------------------------------------------
# utilitários
# ----------------------------------------------------------------------------
def _gravar_jsonl(destino: Path, linhas: list[dict]) -> None:
    """Grava uma lista de objetos como JSON Lines. Mesmo nome de arquivo = sobrescreve (idempotente)."""
    if not linhas:
        raise ValueError(f"Nada para gravar em {destino}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for linha in linhas:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    tmp.replace(destino)  # troca atômica: o arquivo nunca fica pela metade
    print(f"Gravado {destino} com {len(linhas)} linhas")


def _ler_jsonl(caminho: Path) -> list[dict]:
    with caminho.open(encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ----------------------------------------------------------------------------
# fonte 1: Open-Meteo
# ----------------------------------------------------------------------------
def montar_linhas_clima(resposta, ds: str) -> list[dict]:
    """A Open-Meteo devolve uma lista (uma posição por coordenada, na mesma ordem pedida).
    Mantemos a resposta original e só acrescentamos o código IBGE para cruzar na Ouro."""
    if isinstance(resposta, dict):
        resposta = [resposta]
    if len(resposta) != len(MUNICIPIOS):
        raise ValueError(f"Esperava {len(MUNICIPIOS)} locais, veio {len(resposta)}")
    linhas = []
    for (codigo, nome, _, _), local in zip(MUNICIPIOS, resposta):
        linha = {"codigo_ibge": str(codigo), "municipio": nome, "data_coleta": ds}
        linha.update(local)
        linhas.append(linha)
    return linhas


def coletar_clima(ds, **_):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": ",".join(str(m[2]) for m in MUNICIPIOS),
            "longitude": ",".join(str(m[3]) for m in MUNICIPIOS),
            "hourly": ",".join(VARIAVEIS_CLIMA),
            "start_date": ds,
            "end_date": ds,
            "timezone": "America/Sao_Paulo",
        },
        timeout=60,
    )
    r.raise_for_status()
    _gravar_jsonl(CHEGADA / "clima" / f"clima_{ds}.json", montar_linhas_clima(r.json(), ds))


# ----------------------------------------------------------------------------
# fonte 2: IBGE (população do Censo 2022, agregado 4709, variável 93)
# ----------------------------------------------------------------------------
def montar_linhas_ibge(resposta: list, ds: str) -> list[dict]:
    """Abre a resposta do IBGE em uma linha por município, sem alterar os campos."""
    linhas = []
    for variavel in resposta:
        for resultado in variavel.get("resultados", []):
            for serie in resultado.get("series", []):
                linhas.append({
                    "variavel_id": variavel.get("id"),
                    "variavel": variavel.get("variavel"),
                    "unidade": variavel.get("unidade"),
                    "localidade": serie.get("localidade"),
                    "serie": serie.get("serie"),
                    "data_coleta": ds,
                })
    return linhas


def coletar_ibge(ds, **_):
    codigos = ",".join(str(m[0]) for m in MUNICIPIOS)
    r = requests.get(
        "https://servicodados.ibge.gov.br/api/v3/agregados/4709/periodos/2022/variaveis/93",
        params={"localidades": f"N6[{codigos}]"},
        timeout=60,
    )
    r.raise_for_status()
    _gravar_jsonl(CHEGADA / "ibge" / f"ibge_{ds}.json", montar_linhas_ibge(r.json(), ds))


# ----------------------------------------------------------------------------
# fonte 3: relatos de alagamento enviados pelos cidadãos (SIMULADO)
# ----------------------------------------------------------------------------
NOMES = ["Ana", "Bruno", "Carla", "Diego", "Eduarda", "Felipe", "Gabriela", "Henrique",
         "Isabela", "João", "Larissa", "Marcos", "Natália", "Otávio", "Paula", "Rafael",
         "Sabrina", "Thiago", "Vanessa", "Wagner"]
SOBRENOMES = ["Silva", "Santos", "Oliveira", "Souza", "Lima", "Pereira", "Costa",
              "Rodrigues", "Almeida", "Nascimento", "Ferreira", "Carvalho"]
NIVEIS = ["calcada", "canela", "joelho", "cintura"]


def gerar_linhas_relatos(clima: list[dict], ds: str, semente: str) -> list[dict]:
    """Gera relatos coerentes com a chuva do dia: mais chuva, mais relatos e água mais alta.
    - Semente fixa por dia: rodar de novo gera exatamente o mesmo arquivo (idempotente).
    - ~3% de registros com defeito proposital (simula bugs do app) para as regras de qualidade da Prata.
    - ~2% de envios duplicados (o app reenvia) para a deduplicação da Prata.
    Todos os dados pessoais são FICTÍCIOS (domínio .invalid, nomes aleatórios)."""
    rng = random.Random(semente)
    relatos = []
    for local in clima:
        horas = local["hourly"]["time"]
        chuvas = [c or 0.0 for c in local["hourly"]["precipitation"]]
        # cada município tem uma drenagem diferente (fixa entre os dias): alguns alagam bem mais
        fator_drenagem = random.Random(local["codigo_ibge"]).uniform(0.4, 2.2)
        for i, (hora, chuva) in enumerate(zip(horas, chuvas)):
            # a água demora a escoar: a chuva da hora anterior ainda gera relatos
            efetiva = chuva + 0.6 * (chuvas[i - 1] if i > 0 else 0.0)
            esperado = (efetiva * 1.2 * fator_drenagem * rng.uniform(0.5, 1.5)
                        if efetiva >= 0.5 else 0.03)  # relato "falso" raro sem chuva
            if not relatos and local is clima[-1] and hora == horas[-1]:
                esperado = max(esperado, 1.0)  # dia seco: garante 1 relato para o arquivo não ficar vazio
            n = int(esperado) + (1 if rng.random() < esperado - int(esperado) else 0)
            for _ in range(min(n, 30)):
                nome, sobrenome = rng.choice(NOMES), rng.choice(SOBRENOMES)
                inicio = datetime.fromisoformat(hora)
                if chuva >= 7.6:
                    nivel = rng.choices(NIVEIS, weights=[1, 3, 4, 2])[0]
                elif chuva >= 2.5:
                    nivel = rng.choices(NIVEIS, weights=[3, 4, 2, 0.3])[0]
                else:
                    nivel = rng.choices(NIVEIS, weights=[6, 3, 0.5, 0.1])[0]
                relato = {
                    "id_relato": str(uuid.UUID(int=rng.getrandbits(128))),
                    "data_hora": (inicio + timedelta(minutes=rng.randint(0, 59))).isoformat(timespec="minutes"),
                    "codigo_ibge": local["codigo_ibge"],
                    "nome": f"{nome} {sobrenome}",
                    "email": f"{nome.lower()}.{sobrenome.lower()}{rng.randint(1, 999)}@exemplo.invalid",
                    "telefone": f"(11) 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
                    "latitude": round(local["latitude"] + rng.uniform(-0.03, 0.03), 6),
                    "longitude": round(local["longitude"] + rng.uniform(-0.03, 0.03), 6),
                    "nivel_agua": nivel,
                    "data_coleta": ds,
                }
                defeito = rng.random()
                if defeito < 0.01:
                    relato["data_hora"] = None            # bug: sem data/hora
                elif defeito < 0.02:
                    relato["codigo_ibge"] = "9999999"     # bug: município inexistente
                elif defeito < 0.03:
                    relato["latitude"], relato["longitude"] = 0.0, 0.0  # bug: GPS zerado
                relatos.append(relato)
                if rng.random() < 0.02:
                    relatos.append(dict(relato))          # reenvio duplicado do app
    return relatos


def gerar_relatos(ds, **_):
    # Em produção esta tarefa buscaria os relatos na API do MVP com este token.
    # Lido aqui dentro (e não no topo do arquivo), como pede o enunciado.
    token = Variable.get("GS_TOKEN_API_RELATOS")
    print(f"Token da API de relatos carregado ({len(token)} caracteres, valor não exibido)")
    clima = _ler_jsonl(CHEGADA / "clima" / f"clima_{ds}.json")
    linhas = gerar_linhas_relatos(clima, ds, semente=f"relatos-{ds}")
    _gravar_jsonl(CHEGADA / "relatos" / f"relatos_{ds}.json", linhas)


# ----------------------------------------------------------------------------
# verificação e alerta de falha
# ----------------------------------------------------------------------------
def conferir_chegada(ds, **_):
    esperados = [CHEGADA / f / f"{f}_{ds}.json" for f in ("clima", "ibge", "relatos")]
    faltando = [str(p) for p in esperados if not p.exists() or p.stat().st_size == 0]
    if faltando:
        raise FileNotFoundError(f"Arquivos não chegaram ou estão vazios: {faltando}")
    for p in esperados:
        print(f"OK {p} ({len(_ler_jsonl(p))} linhas)")  # também valida que o JSON é legível


def avisar_falha(context):
    ti = context["task_instance"]
    print(f"[ALERTA GS] FALHA na tarefa {ti.task_id} do DAG {ti.dag_id} no dia {context['ds']}")


with DAG(
    dag_id="gs_coleta",
    description="Coleta diária: clima (Open-Meteo), população (IBGE) e relatos de alagamento",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 10, 1, tz="America/Sao_Paulo"),
    catchup=True,
    max_active_runs=3,
    default_args={
        "retries": 2,
        "retry_delay": timedelta(minutes=1),
        "on_failure_callback": avisar_falha,
    },
    tags=["gs", "citizentech"],
) as dag:
    inicio = EmptyOperator(task_id="inicio")
    clima = PythonOperator(task_id="coletar_clima", python_callable=coletar_clima)
    ibge = PythonOperator(task_id="coletar_ibge", python_callable=coletar_ibge)
    relatos = PythonOperator(task_id="gerar_relatos", python_callable=gerar_relatos)
    conferir = PythonOperator(task_id="conferir_chegada", python_callable=conferir_chegada)

    inicio >> [clima, ibge]
    clima >> relatos
    [ibge, relatos] >> conferir
