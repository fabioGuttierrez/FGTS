from django import template

register = template.Library()

@register.simple_tag
def get_vinculo_for_competencia(vinculos, empresa, competencia):
    """
    Retorna o vínculo do funcionário para a empresa e competência informada.
    - vinculos: queryset de vínculos do funcionário
    - empresa: empresa do lançamento
    - competencia: string MM/YYYY
    """
    if not vinculos or not empresa or not competencia:
        return None
    try:
        mes, ano = competencia.split('/')
        mes = int(mes)
        ano = int(ano)
    except Exception:
        return None
    for v in vinculos:
        if v.empresa_id == empresa.pk:
            # Admissão até a competência e (demissão não ocorreu ou após a competência)
            if v.data_admissao and (v.data_admissao.year < ano or (v.data_admissao.year == ano and v.data_admissao.month <= mes)):
                if not v.data_demissao or (v.data_demissao.year > ano or (v.data_demissao.year == ano and v.data_demissao.month >= mes)):
                    return v
    return None
