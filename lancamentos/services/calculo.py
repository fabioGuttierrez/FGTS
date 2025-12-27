from datetime import date
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


def calcular_fgts_atualizado(valor_fgts: Decimal,
                              competencia: date,
                              pagamento: date,
                              indices: Iterable[Tuple[date, Decimal]],
                              jam_coef: Decimal,
                              **kwargs) -> dict:
    """Cálculo FGTS simplificado:
    O índice já encapsula correção, juros e multa.
    
    - Valor Corrigido = Valor FGTS × Índice (sem arredondar o índice, apenas o resultado)
    - JAM = Valor FGTS × Coeficiente JAM
    - Total = Valor Corrigido + JAM
    """
    # Busca o índice para a combinação de competência e data de pagamento
    # O índice mantém toda sua precisão (não é arredondado)
    indice = acumulado_indices(indices, competencia, pagamento)
    
    # Multiplica sem perder precisão do índice, arredonda apenas o resultado final
    valor_corrigido = (valor_fgts * indice).quantize(Decimal('0.01'))
    valor_jam = aplicar_jam(valor_fgts, jam_coef)
    total = (valor_corrigido + valor_jam).quantize(Decimal('0.01'))
    
    return {
        'indice': indice,
        'valor_corrigido': valor_corrigido,
        'valor_jam': valor_jam,
        'total': total,
    }
