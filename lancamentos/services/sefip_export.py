from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable, List

from empresas.models import Empresa
from funcionarios.models import Funcionario
from lancamentos.models import Lancamento


@dataclass
class SefipFilters:
    empresa: Empresa
    competencia: str  # MM/YYYY
    funcionario_de: int
    funcionario_ate: int


def _clean_text(value: str) -> str:
    """Replica a fncTiraAcentoEspacoCaracteres do legado de forma simplificada.

    - Remove acentos/caracteres especiais específicos
    - Mantém espaços (não removemos "de/do/da" etc. porque SEFIP aceita)
    """
    if not value:
        return ""

    # Mapeamento baseado em CAcento/SAcento do VB6
    c_acento = "àáâãäèéêëìíîïòóôõöùúûüÀÁÂÃÄÈÉÊËÌÍÎÒÓÔÕÖÙÚÛÜçÇñÑ/\\?!;:.,[]{}=+-_*><@#%&|ºª()"
    s_acento = "aaaaaeeeeiiiiooooouuuuAAAAAEEEEIIIOOOOOUUUUcCnN                            "

    out_chars: List[str] = []
    for ch in value:
        try:
            idx = c_acento.index(ch)
            out_chars.append(s_acento[idx])
        except ValueError:
            out_chars.append(ch)
    texto = "".join(out_chars)

    # Colapsar letras triplicadas (AAA -> AA) em A-Z
    for code in range(ord("A"), ord("Z") + 1):
        triplo = chr(code) * 3
        duplo = chr(code) * 2
        texto = texto.replace(triplo, duplo)

    return texto


def _pad(value: str, length: int) -> str:
    value = (value or "")[:length]
    return value + " " * (length - len(value))


def _left_zero(number_str: str, length: int) -> str:
    number_str = (number_str or "").strip()
    if not number_str:
        return "0" * length
    digits = "".join(ch for ch in number_str if ch.isdigit())
    return digits.rjust(length, "0")[:length]


def gerar_sefip_conteudo(filtros: SefipFilters) -> str:
    """Gera o conteúdo do arquivo SEFIP.RE conforme rotina VB fncSEFIP.

    - Registro 00: dados da empresa
    - Registro 10: dados complementares da empresa
    - Registros 30 ("301"): um por funcionário da competência
    - Registro 90: trailer fixo
    """
    empresa = filtros.empresa
    competencia_dt = datetime.strptime(filtros.competencia, "%m/%Y")
    comp_yyyymm = competencia_dt.strftime("%Y%m")
    comp_mmyyyy = competencia_dt.strftime("%m%Y")

    linhas: List[str] = []

    # Campos comuns
    cnpj_digits = _left_zero(empresa.cnpj, 14)
    razao = _clean_text(getattr(empresa, "nome", ""))
    endereco = _clean_text(f"{empresa.endereco or ''} {empresa.numero or ''}")
    bairro = _clean_text(empresa.bairro or "")
    cidade = _clean_text(empresa.cidade or "")
    cep_digits = _left_zero(empresa.cep, 8)
    fone_digits = _left_zero(empresa.fone_contato, 12)

    # ----- REGISTRO 00 -----
    # Estrutura espelhada da string VB (comprimentos por contagem visual)
    reg00 = (
        "00"  # tipo
        + " " * 51
        + "11"
        + _pad(cnpj_digits, 14)
        + _pad(razao[:30], 30)
        + "DEPTO PESSOAL" + " " * 7
        + _pad(endereco[:50], 50)
        + _pad(bairro[:20], 20)
        + cep_digits
        + _pad(cidade[:20], 20)
        + (empresa.uf or "  ")[:2]
        + _pad(fone_digits, 12)
        + " " * 60
        + (comp_yyyymm if competencia_dt.month != 13 else competencia_dt.strftime("%Y13"))
        + "1151"
        + " " * 9
        + "1"  # tipo de guia
        + " " * 15
        + "1"  # indicador de centralizadora
        + _pad(cnpj_digits, 14)
        + " " * 18
        + "*"
    )
    linhas.append(reg00)

    # ----- REGISTRO 10 -----
    # RAT / Outras Entidades / Código GPS replicando lógica VB
    if comp_yyyymm < "199810":
        rat = "  "
        terceiros = "    "
        cod_gps = "    "
    else:
        rat_val = int(empresa.percentual_rat or 0)
        rat = f"{rat_val:01d}0"  # ex: 1 -> "10"
        terceiros = _left_zero(empresa.outras_entidades, 4)
        cod_gps = "2100"

    simples_code = str(getattr(empresa, "optante_simples", 1))  # 1/2, igual VB porém vindo do Django
    fpas = _left_zero(empresa.fpas, 3)

    reg10 = (
        "10"
        + "1"  # tipo de inscrição = CNPJ
        + _pad(cnpj_digits, 14)
        + "0" * 39  # campos de inscrição centralizadora/filial em branco
        + _pad(razao[:40], 40)
        + _pad(endereco[:50], 50)
        + _pad(bairro[:20], 20)
        + cep_digits
        + _pad(cidade[:20], 20)
        + (empresa.uf or "  ")[:2]
        + _pad(fone_digits, 12)
        + "N"  # indicador de responsabilidade
        + _pad(empresa.cnae or "", 7)
        + "P"
        + rat
        + "0"  # tipo de processo
        + simples_code
        + fpas
        + terceiros
        + cod_gps
        + " " * 5
        + "0" * 15  # vários totais zerados (como no VB)
        + "0" * 15
        + "0" * 30
        + " " * 16
        + "0" * 45
        + " " * 4
        + "*"
    )
    linhas.append(reg10)

    # ----- REGISTROS 30 (301) -----
    funcionarios_qs: Iterable[Funcionario] = (
        Funcionario.objects
        .filter(
            empresa=empresa,
            id__gte=filtros.funcionario_de,
            id__lte=filtros.funcionario_ate,
        )
        .order_by("pis", "data_admissao")
    )

    lancs_qs = (
        Lancamento.objects
        .filter(
            empresa=empresa,
            funcionario__in=funcionarios_qs,
            competencia=filtros.competencia,
        )
        .select_related("funcionario")
        .order_by("funcionario__pis", "funcionario__data_admissao")
    )

    for lanc in lancs_qs:
        f = lanc.funcionario
        pis = _left_zero(f.pis, 11)
        carteira = _left_zero(f.carteira_profissional, 7)
        serie = _left_zero(f.serie_carteira or "1", 5)
        data_adm = f.data_admissao.strftime("%d%m%Y") if f.data_admissao else "00000000"
        data_nasc = f.data_nascimento.strftime("%d%m%Y") if f.data_nascimento else "00000000"
        cbo = _left_zero(f.cbo, 4)

        nome = _clean_text(f.nome or "")
        nome = _pad(nome[:70], 70)

        # ID interno como no legado (FuncionarioID, até 11 posições)
        fid = str(f.id)
        fid = fid[:11]
        fid = " " * (11 - len(fid)) + fid

        base_str = f"{lanc.base_fgts:015.2f}".replace(",", "")

        reg30 = (
            "301"
            + _pad(cnpj_digits, 14)
            + " " * 15
            + pis
            + data_adm
            + "01"  # categoria (fixa como no VB)
            + nome
            + fid
            + carteira
            + serie
            + data_adm
            + data_nasc
            + "0"  # indicador de alteração salarial
            + cbo
            + base_str
            + "000000000000000"  # remunerações adicionais zeradas
            + " 05000000000000000000000000000000000000000000000000000000000000"  # sequência fixa espelhada
            + " " * 98
            + "*"
        )
        linhas.append(reg30)

    # ----- REGISTRO 90 (trailer) -----
    reg90 = (
        "909" + "9" * 53 + " " * 238 + "*"
    )
    linhas.append(reg90)

    return "\r\n".join(linhas) + "\r\n"
