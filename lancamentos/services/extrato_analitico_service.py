"""
Serviço de importação de Extrato Analítico FGTS (CEF).

Parseia o arquivo XLSX emitido pelo portal Conectividade Social e confirma
os depósitos na plataforma, marcando Lancamentos como pago=True com
fonte_confirmacao_pagamento='extrato_analitico'.

Suporta dois formatos do XLSX:
  - Aba "Tratada": tabela estruturada com empresa_id, matricula, competencia, valor, data_pg
  - Aba "Original": relatório em texto com blocos por trabalhador (CNPJ + PIS + HISTORICO)
"""

from __future__ import annotations

import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Callable, Dict, List, Optional, Tuple

from django.db import transaction

from empresas.models import Empresa
from empresas.models_grupo import FuncionarioVinculo
from funcionarios.models import Funcionario
from lancamentos.models import Lancamento


class ExtratoImportError(Exception):
    pass


MESES_PT = {
    'JANEIRO': '01', 'FEVEREIRO': '02', 'MARCO': '03', 'MARCO': '03',
    'ABRIL': '04', 'MAIO': '05', 'JUNHO': '06', 'JULHO': '07',
    'AGOSTO': '08', 'SETEMBRO': '09', 'OUTUBRO': '10',
    'NOVEMBRO': '11', 'DEZEMBRO': '12',
}

# "DEPOSITO [EM ATRASO] NOMEMES/ANO  valor"
_RE_DEPOSITO = re.compile(
    r'^DEPOSITO(?:\s+EM\s+ATRASO)?\s+([A-Z]+)/(\d{4})\s+([\d.,]+)',
    re.IGNORECASE,
)


def _extrair_deposito(linha: str) -> Optional[Tuple[str, Decimal, Optional[date]]]:
    data_pg = _parse_data(linha[:10])
    resto = linha[10:].strip()
    m = _RE_DEPOSITO.match(resto)
    if not m:
        return None
    mes_nome = m.group(1).upper().replace('Ç', 'C').replace('Ã', 'A')
    mes_num = MESES_PT.get(mes_nome)
    if not mes_num:
        return None
    valor = _parse_valor(m.group(3))
    if valor <= 0:
        return None
    return f'{mes_num}/{m.group(2)}', valor, data_pg


class RegistroExtrato:
    __slots__ = (
        'empresa_ref', 'matricula', 'pis', 'cnpj', 'nome',
        'competencia', 'data_pagamento', 'valor',
    )

    def __init__(
        self,
        competencia: str,
        data_pagamento: Optional[date],
        valor: Decimal,
        empresa_ref: Any = None,
        matricula: str = '',
        pis: str = '',
        cnpj: str = '',
        nome: str = '',
    ):
        self.empresa_ref = empresa_ref   # int (empresa.codigo) ou None
        self.matricula = matricula
        self.pis = pis
        self.cnpj = cnpj
        self.nome = nome
        self.competencia = competencia
        self.data_pagamento = data_pagamento
        self.valor = valor


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_data(s: str) -> Optional[date]:
    """Parseia DD/MM/YYYY."""
    try:
        return datetime.strptime(s.strip(), '%d/%m/%Y').date()
    except Exception:
        return None


def _parse_valor(s: str) -> Decimal:
    """Converte string BR (1.234,56) em Decimal."""
    try:
        limpo = str(s).strip().replace('.', '').replace(',', '.')
        return Decimal(limpo)
    except (InvalidOperation, ValueError):
        return Decimal('0.00')


def parse_tratada(ws) -> Tuple[List[RegistroExtrato], List[str]]:
    """
    Parseia a aba 'Tratada' do XLSX — formato tabular pré-processado.

    Colunas esperadas (índices 0-based):
      0: ID, 1: ignore, 2: empresa_codigo(int), 3: matricula,
      4: nome, 5: tipo, 6: data_pg(DD/MM/YYYY), 7: comp_texto,
      8: competencia(MM/YYYY), 9: valor(float), 10: matricula
    """
    registros: List[RegistroExtrato] = []
    erros: List[str] = []
    primeira_linha = True

    for row in ws.iter_rows(values_only=True):
        if primeira_linha:
            primeira_linha = False
            continue  # pula cabeçalho

        if not row or row[0] is None:
            continue

        try:
            empresa_id = int(row[2]) if row[2] is not None else None
            matricula = str(int(row[3])) if isinstance(row[3], (int, float)) else str(row[3] or '').strip()
            nome = str(row[4] or '').strip()
            data_pg_str = str(row[6] or '').strip()
            comp_raw = str(row[8] or '').strip()
            valor_raw = row[9]
        except Exception as exc:
            erros.append(f'Linha inválida: {exc}')
            continue

        # Competência: " 04/2018         " → "04/2018"
        comp = comp_raw.strip()
        if not re.match(r'^\d{2}/\d{4}$', comp):
            erros.append(f'Competência inválida: "{comp_raw}" — ignorada.')
            continue

        data_pg = _parse_data(data_pg_str)
        valor = _parse_valor(str(valor_raw)) if valor_raw is not None else Decimal('0.00')

        if valor <= 0:
            continue  # ignora estornos / JAM / saques

        registros.append(RegistroExtrato(
            empresa_ref=empresa_id,
            matricula=matricula,
            nome=nome,
            competencia=comp,
            data_pagamento=data_pg,
            valor=valor,
        ))

    return registros, erros


def parse_original(ws) -> Tuple[List[RegistroExtrato], List[str]]:
    """
    Parseia a aba 'Original' do XLSX — relatório em texto da CEF.

    Cada linha do XLSX pode ter conteúdo espalhado em várias colunas; todas são
    unidas com dois espaços para reconstruir a linha visual do relatório.

    Blocos por trabalhador:
      NOME DO TRABALHADOR → PIS/PASEP → INSCRICAO EMPREGADOR → HISTORICO DOS LANCAMENTOS
    """
    registros: List[RegistroExtrato] = []
    erros: List[str] = []

    # Une todas as células não-vazias de cada linha do XLSX
    linhas: List[str] = []
    for row in ws.iter_rows(values_only=True):
        partes = [str(c).strip() for c in row if c is not None and str(c).strip()]
        linhas.append('  '.join(partes))

    pis_atual = ''
    cnpj_atual = ''
    nome_atual = ''
    em_historico = False

    i = 0
    while i < len(linhas):
        linha = linhas[i]

        if linha.startswith('NOME DO TRABALHADOR') and 'NUM.CONTA' in linha:
            em_historico = False
            nome_linha = linhas[i + 1] if (i + 1) < len(linhas) else ''
            m_nome = re.match(r'^(.+?)\s{2,}\d{4,}', nome_linha)
            nome_atual = m_nome.group(1).strip() if m_nome else nome_linha.strip()
            i += 1

        elif 'PIS/PASEP' in linha and 'DTA.ADM' in linha:
            pis_linha = linhas[i + 1] if (i + 1) < len(linhas) else ''
            m_pis = re.match(r'^(\d{11})', pis_linha.replace(' ', ''))
            if m_pis:
                pis_atual = m_pis.group(1)
            i += 1

        elif 'INSCRICAO EMPREGADOR' in linha:
            emp_linha = linhas[i + 1] if (i + 1) < len(linhas) else ''
            m_cnpj = re.search(r'(\d{14})\s*$', emp_linha)
            if m_cnpj:
                cnpj_atual = m_cnpj.group(1)
            i += 1

        elif 'HISTORICO DOS LANCAMENTOS' in linha:
            em_historico = True

        elif em_historico and linha:
            # Encerra histórico em marcadores de fim de seção
            if linha.startswith('*') or linha.startswith('#') or linha.startswith('SALDO ATUAL'):
                em_historico = False

            elif re.match(r'^\d{2}/\d{2}/\d{4}', linha):
                resultado = _extrair_deposito(linha)
                if resultado and pis_atual and cnpj_atual:
                    comp, valor, data_pg = resultado
                    registros.append(RegistroExtrato(
                        pis=pis_atual,
                        cnpj=cnpj_atual,
                        nome=nome_atual,
                        competencia=comp,
                        data_pagamento=data_pg,
                        valor=valor,
                    ))

        i += 1

    return registros, erros


# ---------------------------------------------------------------------------
# Serviço principal
# ---------------------------------------------------------------------------

class ExtratoAnaliticoService:
    """
    Importador de Extrato Analítico da CEF.

    Detecta automaticamente se o XLSX contém a aba 'Tratada' (formato
    estruturado) ou se usa apenas a aba 'Original' (formato de relatório).
    """

    def __init__(self):
        self._empresa_cache: Dict[Any, Optional[Empresa]] = {}
        self._vinculo_cache: Dict[str, Optional[FuncionarioVinculo]] = {}

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def preview(
        self,
        xlsx_bytes: bytes,
        max_rows: int = 15,
    ) -> Dict[str, Any]:
        """Processa os primeiros max_rows registros sem gravar no banco."""
        registros, parse_erros = self._parse_xlsx(xlsx_bytes)
        total = len(registros)
        amostra = registros[:max_rows]

        rows = []
        for reg in amostra:
            empresa, vinculo, func, erro = self._resolver(reg)
            lancamento = None
            if vinculo and not erro:
                lancamento = Lancamento.objects.filter(
                    vinculo=vinculo,
                    competencia=reg.competencia,
                ).first()
                if not lancamento and func and empresa:
                    lancamento = Lancamento.objects.filter(
                        funcionario=func,
                        empresa=empresa,
                        competencia=reg.competencia,
                        vinculo__isnull=True,
                    ).first()

            rows.append({
                'pis': reg.pis,
                'cnpj': reg.cnpj,
                'matricula': reg.matricula,
                'nome': reg.nome,
                'competencia': reg.competencia,
                'data_pagamento': reg.data_pagamento.strftime('%d/%m/%Y') if reg.data_pagamento else '',
                'valor': str(reg.valor),
                'empresa_nome': empresa.nome if empresa else None,
                'funcionario_nome': func.nome if func else None,
                'lancamento_id': lancamento.pk if lancamento else None,
                'ja_confirmado_cef': (
                    lancamento.fonte_confirmacao_pagamento == 'extrato_analitico'
                    if lancamento else False
                ),
                'status': 'ok' if (lancamento and not erro) else 'error',
                'erro': erro or ('' if lancamento else 'Lançamento não encontrado na plataforma'),
            })

        linhas_ok = sum(1 for r in rows if r['status'] == 'ok')
        linhas_erro = sum(1 for r in rows if r['status'] == 'error')

        return {
            'total_registros': total,
            'linhas_amostradas': len(amostra),
            'linhas_ok': linhas_ok,
            'linhas_erro': linhas_erro,
            'rows': rows,
            'parse_erros': parse_erros[:10],
        }

    def importar(
        self,
        xlsx_bytes: bytes,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, Any]:
        """
        Confirma pagamentos em todos os registros do extrato.
        Marca: pago=True, fonte_confirmacao_pagamento='extrato_analitico'.
        """
        registros, parse_erros = self._parse_xlsx(xlsx_bytes)
        total = len(registros)

        if progress_callback:
            progress_callback(0, total)

        confirmados = 0
        nao_encontrados = 0
        ja_confirmados = 0
        erros: List[str] = list(parse_erros)
        avisos: List[str] = []

        for idx, reg in enumerate(registros, 1):
            empresa, vinculo, func, erro = self._resolver(reg)

            if erro or not empresa:
                erros.append(f'Reg {idx} ({reg.nome} / {reg.competencia}): {erro or "empresa não identificada"}')
                continue

            lancamento = self._buscar_lancamento(vinculo, func, empresa, reg.competencia)
            if not lancamento:
                nao_encontrados += 1
                avisos.append(
                    f'Reg {idx}: sem lançamento para '
                    f'{reg.nome} / {reg.competencia} — ignorado.'
                )
                continue

            if lancamento.fonte_confirmacao_pagamento == 'extrato_analitico':
                ja_confirmados += 1
                continue

            try:
                with transaction.atomic():
                    Lancamento.objects.filter(pk=lancamento.pk).update(
                        pago=True,
                        fonte_confirmacao_pagamento='extrato_analitico',
                        data_pagto=reg.data_pagamento or lancamento.data_pagto,
                        valor_pago=reg.valor if reg.valor > 0 else lancamento.valor_pago,
                    )
                confirmados += 1
            except Exception as exc:
                erros.append(f'Reg {idx}: erro ao salvar — {exc}')

            if progress_callback and idx % 50 == 0:
                progress_callback(idx, total)

        if progress_callback:
            progress_callback(total, total)

        return {
            'confirmados': confirmados,
            'nao_encontrados': nao_encontrados,
            'ja_confirmados': ja_confirmados,
            'erros': erros,
            'avisos': avisos,
            'total': total,
        }

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _parse_xlsx(self, xlsx_bytes: bytes) -> Tuple[List[RegistroExtrato], List[str]]:
        try:
            import openpyxl
        except ImportError:
            raise ExtratoImportError('A biblioteca openpyxl não está instalada.')

        try:
            wb = openpyxl.load_workbook(BytesIO(xlsx_bytes), read_only=True, data_only=True)
        except Exception as exc:
            raise ExtratoImportError(f'Não foi possível abrir o arquivo XLSX: {exc}')

        if 'Tratada' in wb.sheetnames:
            return parse_tratada(wb['Tratada'])

        # Tenta a primeira aba (Original)
        ws = wb.active
        return parse_original(ws)

    def _resolver(
        self, reg: RegistroExtrato
    ) -> Tuple[Optional[Empresa], Optional[FuncionarioVinculo], Optional[Funcionario], str]:
        """Resolve Empresa + FuncionarioVinculo + Funcionario para um registro."""
        empresa = self._resolver_empresa(reg)
        if not empresa:
            return None, None, None, 'Empresa não encontrada na plataforma.'

        vinculo, func = self._resolver_vinculo(reg, empresa)
        if not func:
            return empresa, None, None, f'Funcionário não encontrado (PIS:{reg.pis} / mat:{reg.matricula}).'

        return empresa, vinculo, func, ''

    def _resolver_empresa(self, reg: RegistroExtrato) -> Optional[Empresa]:
        # Aba Tratada: usa empresa_ref (empresa.codigo)
        if reg.empresa_ref is not None:
            key = f'id:{reg.empresa_ref}'
            if key not in self._empresa_cache:
                self._empresa_cache[key] = Empresa.objects.filter(codigo=reg.empresa_ref).first()
            return self._empresa_cache[key]

        # Aba Original: usa CNPJ
        cnpj_limpo = re.sub(r'\D', '', reg.cnpj)
        if cnpj_limpo not in self._empresa_cache:
            self._empresa_cache[cnpj_limpo] = Empresa.objects.filter(cnpj=cnpj_limpo).first()
        return self._empresa_cache[cnpj_limpo]

    def _resolver_vinculo(
        self, reg: RegistroExtrato, empresa: Empresa
    ) -> Tuple[Optional[FuncionarioVinculo], Optional[Funcionario]]:
        # Aba Tratada: usa matrícula
        if reg.matricula:
            key = f'{empresa.pk}:mat:{reg.matricula}'
            if key not in self._vinculo_cache:
                v = FuncionarioVinculo.objects.filter(
                    empresa=empresa,
                    matricula=reg.matricula,
                ).select_related('funcionario').first()
                self._vinculo_cache[key] = v
            vinculo = self._vinculo_cache[key]
            if vinculo:
                return vinculo, vinculo.funcionario

        # Aba Original (ou fallback): usa PIS
        if reg.pis:
            pis_limpo = re.sub(r'\D', '', reg.pis).zfill(11)
            key = f'{empresa.pk}:pis:{pis_limpo}'
            if key not in self._vinculo_cache:
                func = Funcionario.objects.filter(
                    pis=pis_limpo,
                    vinculos__empresa=empresa,
                ).first()
                if func:
                    v = FuncionarioVinculo.objects.filter(
                        funcionario=func,
                        empresa=empresa,
                    ).select_related('funcionario').order_by('-data_admissao').first()
                    self._vinculo_cache[key] = v
                else:
                    self._vinculo_cache[key] = None

            v = self._vinculo_cache[key]
            if v:
                return v, v.funcionario

        return None, None

    def _buscar_lancamento(
        self,
        vinculo: Optional[FuncionarioVinculo],
        func: Optional[Funcionario],
        empresa: Empresa,
        competencia: str,
    ) -> Optional[Lancamento]:
        """Busca Lancamento por vínculo (ou funcionário + empresa) + competência."""
        if vinculo:
            lanc = Lancamento.objects.filter(
                vinculo=vinculo,
                competencia=competencia,
            ).first()
            if lanc:
                return lanc

        if func:
            return Lancamento.objects.filter(
                funcionario=func,
                empresa=empresa,
                competencia=competencia,
            ).first()

        return None
