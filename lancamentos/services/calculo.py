from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from typing import Iterable, Tuple

from configuracoes.models import Configuracao


def get_config_numeric(key: str, default: Decimal) -> Decimal:
    try:
        cfg = Configuracao.objects.get(chave=key)
        return Decimal(str(cfg.valor))
    except Exception:
        return default


def get_config_str(key: str, default: str) -> str:
    try:
        cfg = Configuracao.objects.get(chave=key)
        return str(cfg.valor)
    except Exception:
        return default


def acumulado_indices(indices: Iterable[Tuple[date, Decimal]], competencia: date, pagamento: date) -> Decimal:
    """Busca o índice correspondente à combinação de competência + data de pagamento.
    O índice deve estar entre a data da competência e a data de pagamento.
    Se houver múltiplos, usa o mais recente (maior índice).
    Retorna o índice ou 1.0 se não encontrar (sem correção).
    """
    indices_list = list(indices)
    # Ordena por data DESC para pegar o maior índice disponível
    indices_list.sort(key=lambda x: x[0], reverse=True)
    
    for d, v in indices_list:
        # Busca índice que está entre a competência e a data de pagamento
        if competencia <= d <= pagamento:
            return v
    
    # Se não encontrar no intervalo, retorna o mais próximo da data de pagamento
    for d, v in indices_list:
        if d <= pagamento:
            return v
    
    # Se não encontrar nada, retorna 1.0 (sem correção)
    return Decimal('1.0')


def aplicar_jam(valor_fgts: Decimal, jam_coef: Decimal) -> Decimal:
    return (valor_fgts * jam_coef).quantize(Decimal('0.01'))


def calcular_jam_composto(acumulado_anterior: Decimal, valor_fgts: Decimal, jam_coef: Decimal) -> tuple[Decimal, Decimal]:
    """Replica o comportamento legado do JAM (cálculo composto).

    - Se não houver jam_coef, retorna jam=0 e acumula apenas o FGTS do mês.
    - Caso haja jam_coef, aplica sobre o acumulado anterior e soma o FGTS do mês.
    Retorna (valor_jam, novo_acumulado).
    """
    jam_coef = jam_coef or Decimal('0')
    if acumulado_anterior is None:
        # Primeiro mês do funcionário: JAM zerado, inicia o acumulador
        return Decimal('0.00'), valor_fgts
    jam_val = (acumulado_anterior * jam_coef).quantize(Decimal('0.01'))
    novo_acumulado = acumulado_anterior + jam_val + valor_fgts
    return jam_val, novo_acumulado


def calcular_jam_periodo(valor_fgts: Decimal, competencia_start: date, data_pagamento: date, data_admissao: date) -> Decimal:
    """Calcula JAM para UMA competência específica.
    
    Regra oficial: 
    - A competência de admissão (mês de admissão) = JAM zerado (nenhum acúmulo anterior)
    - Competências posteriores à admissão = JAM com acúmulo desde a admissão
    
    Args:
        valor_fgts: Valor FGTS da competência
        competencia_start: Competência específica (primeiro dia)
        data_pagamento: Data final (data de pagamento)
        data_admissao: Data de admissão do funcionário
    
    Returns:
        JAM calculado para essa competência
    """
    from coefjam.models import CoefJam
    
    # Se a competência é a de admissão, retorna JAM zerado
    competencia_admissao = date(data_admissao.year, data_admissao.month, 1)
    if competencia_start == competencia_admissao:
        return Decimal('0.00')
    
    # Se a competência é anterior à admissão, não há FGTS (retorna 0)
    if competencia_start < competencia_admissao:
        return Decimal('0.00')
    
    # Para competências posteriores à admissão, calcula JAM
    # JAM = Acumulado anterior × Coeficiente JAM da competência
    # O acumulado é: valor_fgts × quantidade de meses desde admissão
    
    # Conta quantos meses completos passaram desde admissão até a competência
    meses_passados = (competencia_start.year - competencia_admissao.year) * 12 + (competencia_start.month - competencia_admissao.month)
    
    # Acumulado = FGTS do mês × número de meses anteriores
    # (isto é, na competência anterior, tínhamos FGTS × (meses_passados - 1))
    acumulado_anterior = valor_fgts * Decimal(meses_passados - 1)
    
    # Busca coeficiente JAM da competência anterior
    competencia_anterior = competencia_start - relativedelta(months=1)
    competencia_anterior_str = competencia_anterior.strftime('%m/%Y')
    
    jam_coef = CoefJam.objects.filter(competencia=competencia_anterior_str).first()
    
    if not jam_coef:
        # Se não houver coeficiente, JAM = 0
        return Decimal('0.00')
    
    # JAM = Acumulado anterior × Coeficiente
    jam_valor = (acumulado_anterior * jam_coef.valor).quantize(Decimal('0.01'))
    
    return jam_valor if jam_valor > 0 else Decimal('0.00')


def calcular_fgts_atualizado(valor_fgts: Decimal,
                              competencia: date,
                              pagamento: date,
                              indice: Decimal,
                              jam_coef: Decimal,
                              valor_jam_override: Decimal | None = None,
                              **kwargs) -> dict:
    """Cálculo FGTS simplificado:
    O índice já encapsula correção, juros e multa.
    
    - Valor Corrigido = Valor FGTS × Índice (sem arredondar o índice, apenas o resultado)
    - JAM = Valor FGTS × Coeficiente JAM
    - Total = Valor Corrigido + JAM
    """
    # Usa o índice específico para competencia + data_pagamento
    # Se não houver índice, usa 1.0 (sem correção)
    indice_final = indice if indice is not None else Decimal('1.0')
    
    # Multiplica sem perder precisão do índice, arredonda apenas o resultado final
    valor_corrigido = (valor_fgts * indice_final).quantize(Decimal('0.01'))

    # Se vier um JAM pré-calculado (modo composto), usa-o; caso contrário, calcula simples
    if valor_jam_override is not None:
        valor_jam = valor_jam_override.quantize(Decimal('0.01'))
    else:
        valor_jam = aplicar_jam(valor_fgts, jam_coef)
    total = (valor_corrigido + valor_jam).quantize(Decimal('0.01'))
    
    return {
        'indice': indice_final,
        'valor_corrigido': valor_corrigido,
        'valor_jam': valor_jam,
        'total': total,
    }


def gerar_memoria_calculo(funcionario_nome: str, funcionario_cpf: str, data_admissao: date,
                         valor_fgts: Decimal, competencia_str: str, data_pagamento: date,
                         indice: Decimal, valor_jam: Decimal, valor_corrigido: Decimal, 
                         total: Decimal, data_admissao_mes: str) -> str:
    """Gera memória de cálculo detalhada em formato texto.
    
    Args:
        funcionario_nome: Nome do funcionário
        funcionario_cpf: CPF do funcionário
        data_admissao: Data completa de admissão
        valor_fgts: Valor FGTS do mês
        competencia_str: Competência analisada (MM/YYYY)
        data_pagamento: Data de pagamento
        indice: Índice FGTS utilizado
        valor_jam: Valor JAM calculado
        valor_corrigido: Valor corrigido (FGTS × Índice)
        total: Total final
        data_admissao_mes: Competência de admissão (MM/YYYY)
    
    Returns:
        String com a memória de cálculo formatada
    """
    
    memoria = []
    memoria.append("=" * 80)
    memoria.append("MEMÓRIA DE CÁLCULO - FGTS COM JAM")
    memoria.append("=" * 80)
    memoria.append("")
    
    # Seção 1: Identificação
    memoria.append("1. IDENTIFICAÇÃO")
    memoria.append("-" * 80)
    memoria.append(f"   Funcionário: {funcionario_nome}")
    memoria.append(f"   CPF: {funcionario_cpf}")
    memoria.append(f"   Data de Admissão: {data_admissao.strftime('%d/%m/%Y')} (Competência: {data_admissao_mes})")
    memoria.append(f"   Competência Analisada: {competencia_str}")
    memoria.append(f"   Data de Pagamento: {data_pagamento.strftime('%d/%m/%Y')}")
    memoria.append("")
    
    # Seção 2: Dados Base
    memoria.append("2. DADOS BASE")
    memoria.append("-" * 80)
    memoria.append(f"   Valor FGTS (Mês): R$ {valor_fgts:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
    memoria.append("")
    
    # Seção 3: Cálculo do FGTS Corrigido
    memoria.append("3. CÁLCULO DO FGTS CORRIGIDO")
    memoria.append("-" * 80)
    memoria.append(f"   Fórmula: Valor FGTS × Índice FGTS")
    memoria.append(f"   Índice FGTS (Tabela): {indice}")
    memoria.append(f"   Cálculo: R$ {valor_fgts:,.2f} × {indice} = R$ {valor_corrigido:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
    memoria.append("")
    
    # Seção 4: Cálculo do JAM (Juros da Mora)
    memoria.append("4. CÁLCULO DO JAM (JUROS DA MORA)")
    memoria.append("-" * 80)
    
    # Verifica se é competência de admissão
    if competencia_str == data_admissao_mes:
        memoria.append(f"   ⚠️  Competência de Admissão: {competencia_str}")
        memoria.append(f"   Regra: JAM ZERADO (sem acúmulo anterior de FGTS)")
        memoria.append(f"   JAM = R$ 0,00")
    else:
        memoria.append(f"   Regra: JAM acumulado do período ({data_admissao_mes} até {competencia_str})")
        memoria.append(f"   O JAM é calculado mês a mês com acúmulo de juros sobre o saldo anterior")
        memoria.append(f"   JAM Total do Período = R$ {valor_jam:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
    
    memoria.append("")
    
    # Seção 5: Resultado Final
    memoria.append("5. RESULTADO FINAL")
    memoria.append("-" * 80)
    memoria.append(f"   Valor FGTS Corrigido: R$ {valor_corrigido:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
    memoria.append(f"   JAM (Juros da Mora):  R$ {valor_jam:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
    memoria.append(f"   " + "-" * 76)
    memoria.append(f"   TOTAL:                 R$ {total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.'))
    memoria.append("")
    
    # Rodapé
    memoria.append("=" * 80)
    memoria.append("Data de Geração: " + date.today().strftime("%d/%m/%Y às %H:%M:%S"))
    memoria.append("Sistema: FGTS Web - Cálculo Automático")
    memoria.append("=" * 80)
    
    return "\n".join(memoria)

