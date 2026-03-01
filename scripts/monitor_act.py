#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import csv
import json
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CSV_IN = DATA_DIR / "tbl_instrumentos.csv"
OUT_LOG = DATA_DIR / "resumo_execucao.json"

# (opcional) se você quiser manter arquivos de apoio internos:
OUT_ALERTA_180 = DATA_DIR / "alertas_180.csv"
OUT_ALERTA_60 = DATA_DIR / "alertas_60.csv"

DATE_COLS_END = ["vigencia_termino", "VIGÊNCIA - TÉRMINO", "vencimento", "Vencimento", "vigencia_fim", "vigência_término"]
DATE_COLS_START = ["vigencia_inicio", "VIGÊNCIA - INÍCIO", "inicio", "Inicio", "vigência_início"]

ID_COLS = ["identificacao", "Identificação", "identificação", "numero", "número", "instrumento", "Instrumento"]

def norm(s: str) -> str:
    return (s or "").strip()

def first(row: Dict[str, str], keys: List[str]) -> str:
    for k in keys:
        if k in row and norm(row.get(k, "")) != "":
            return row[k]
    return ""

def parse_date_any(raw: str) -> Optional[date]:
    raw = norm(raw)
    if not raw:
        return None

    # dd/mm/yyyy ou dd-mm-yyyy
    for sep in ["/", "-"]:
        parts = raw.split(sep)
        if len(parts) == 3 and len(parts[2]) == 4:
            try:
                dd = int(parts[0]); mm = int(parts[1]); yy = int(parts[2])
                return date(yy, mm, dd)
            except Exception:
                pass

    # yyyy-mm-dd
    if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
        try:
            yy = int(raw[0:4]); mm = int(raw[5:7]); dd = int(raw[8:10])
            return date(yy, mm, dd)
        except Exception:
            pass

    # fallback ISO
    try:
        return datetime.fromisoformat(raw[:10]).date()
    except Exception:
        return None

def days_to(d: Optional[date], today: date) -> Optional[int]:
    if d is None:
        return None
    return (d - today).days

def is_arquivado(row: Dict[str, str]) -> bool:
    v = (first(row, ["arquivado", "Arquivado", "status_geral", "Status Geral", "status"]) or "").strip().upper()
    return v in {"SIM", "S", "1", "TRUE"} or ("ARQUIV" in v)

def is_concluido(row: Dict[str, str]) -> bool:
    v = (first(row, ["status_execucao", "status_execução", "situacao_execucao", "situação_execucao", "andamento", "execucao", "execução"]) or "").strip().upper()
    return ("CONCL" in v) or ("FINALIZ" in v)

def read_csv_any_delim(path: Path) -> Tuple[List[Dict[str, str]], List[str], str]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        delim = dialect.delimiter
    except Exception:
        delim = ";"

    rows: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=delim)
        headers = reader.fieldnames or []
        for r in reader:
            if not any(norm(str(v)) for v in (r.values() if r else [])):
                continue
            rows.append({k: (v if v is not None else "") for k, v in r.items()})
    return rows, headers, delim

def write_csv(path: Path, rows: List[Dict[str, str]], headers: List[str], delim: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=headers, delimiter=delim)
        w.writeheader()
        for r in rows:
            w.writerow({h: r.get(h, "") for h in headers})

def main() -> int:
    today = date.today()

    if not CSV_IN.exists():
        print(f"[ERRO] CSV não encontrado: {CSV_IN}", file=sys.stderr)
        return 1

    rows, headers, delim = read_csv_any_delim(CSV_IN)

    total_base = 0
    ignorados_arquivados = 0
    concluidos = 0

    # faixas que você pediu:
    confortavel_acima_180 = 0   # 🟢
    atencao_61_180 = 0          # 🟡
    critica_ate_60 = 0          # 🔴
    sem_data = 0
    vencido = 0

    min_dias: Optional[int] = None
    min_id: str = "Identificação não informada"

    alertas_180_rows: List[Dict[str, str]] = []
    alertas_60_rows: List[Dict[str, str]] = []

    for r in rows:
        if is_arquivado(r):
            ignorados_arquivados += 1
            continue

        total_base += 1
        if is_concluido(r):
            concluidos += 1

        fim_raw = first(r, DATE_COLS_END)
        fim = parse_date_any(fim_raw)
        dias = days_to(fim, today)

        ident = norm(first(r, ID_COLS)) or "Identificação não informada"

        if dias is None:
            sem_data += 1
            continue

        if min_dias is None or dias < min_dias:
            min_dias = dias
            min_id = ident

        if dias < 0:
            vencido += 1
            continue

        # classificação conforme seu modelo
        if dias <= 60:
            critica_ate_60 += 1
            alertas_60_rows.append(r)
        elif dias <= 180:
            atencao_61_180 += 1
            alertas_180_rows.append(r)
        else:
            confortavel_acima_180 += 1

    # salva um resumo “contratual” (o e-mail depende disso)
    resumo = {
        "data_execucao": today.isoformat(),
        "total_base_painel": total_base,
        "ignorados_arquivados": ignorados_arquivados,
        "concluidos": concluidos,
        "faixas": {
            "confortavel_acima_180": confortavel_acima_180,
            "atencao_61_180": atencao_61_180,
            "critica_ate_60": critica_ate_60,
            "sem_data": sem_data,
            "vencido": vencido,
        },
        "menor_prazo": {
            "dias": (min_dias if min_dias is not None else None),
            "identificacao": min_id,
        },
    }
    OUT_LOG.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")

    # (opcional) mantém csvs internos de apoio
    # Só se você quiser manter para auditoria interna (não vai por e-mail).
    if headers:
        write_csv(OUT_ALERTA_180, alertas_180_rows, headers, delim)
        write_csv(OUT_ALERTA_60, alertas_60_rows, headers, delim)

    print("[OK] Monitoramento concluído:", json.dumps(resumo, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
