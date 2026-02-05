from datetime import datetime
from io import BytesIO
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from django.utils.timezone import make_aware
from django.core.exceptions import ValidationError
from decimal import Decimal, InvalidOperation
from lancamentos.models import Lancamento
from empresas.models import Empresa
from funcionarios.models import Funcionario
from billing.models import BillingCustomer
from fgtsweb.mixins import is_empresa_allowed
from empresas.models_grupo import FuncionarioVinculo


class LancamentoImportService:
    """Serviço para gerenciar importação e exportação de lançamentos FGTS em XLSX"""
    
    REQUIRED_COLUMNS = [
        'CPF_FUNCIONARIO', 'NOME_FUNCIONARIO', 'COMPETENCIA', 'BASE_FGTS'
    ]
    
    OPTIONAL_COLUMNS = [
        # EMPRESA é opcional, mas recomendado para grupos com múltiplos vínculos ativos.
        # Quando informado, deve ser o código da empresa (mesmo usado no sistema).
        'EMPRESA',
        'VALOR_FGTS', 'PAGO', 'DATA_PAGTO', 'VALOR_PAGO', 'PARCELA_13'
    ]
    
    @staticmethod
    def generate_template_xlsx():
        """Gera um arquivo XLSX com o modelo para importação de lançamentos"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Lançamentos FGTS"
        
        # Definir estilos
        header_fill = PatternFill(start_color="667eea", end_color="667eea", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=11)
        example_fill = PatternFill(start_color="E7E9FF", end_color="E7E9FF", fill_type="solid")
        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Headers com colunas obrigatórias e opcionais
        all_columns = LancamentoImportService.REQUIRED_COLUMNS + LancamentoImportService.OPTIONAL_COLUMNS
        
        for col_idx, column_name in enumerate(all_columns, 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.value = column_name
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = border
            ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = 18
        
        # Linha de exemplo
        example_data = [
            '12345678901',           # CPF_FUNCIONARIO
            'João da Silva',         # NOME_FUNCIONARIO
            '01/2026',              # COMPETENCIA (MM/YYYY)
            '3500.00',              # BASE_FGTS
            '1',                    # EMPRESA (código)
            '280.00',               # VALOR_FGTS (8% da base)
            'NÃO',                  # PAGO (SIM/NÃO)
            '',                     # DATA_PAGTO (dd/mm/yyyy)
            '',                     # VALOR_PAGO
            '',                     # PARCELA_13
        ]
        
        for col_idx, value in enumerate(example_data, 1):
            cell = ws.cell(row=2, column=col_idx)
            cell.value = value
            cell.fill = example_fill
            cell.border = border
            cell.alignment = Alignment(horizontal='left', vertical='center')
        
        # Instruções
        ws.merge_cells('A4:J4')
        instructions = ws['A4']
        instructions.value = "INSTRUÇÕES DE PREENCHIMENTO"
        instructions.font = Font(bold=True, size=12, color="667eea")
        instructions.alignment = Alignment(horizontal='left')
        
        instructions_text = [
            "1. CPF_FUNCIONARIO: CPF do colaborador (apenas números)",
            "2. NOME_FUNCIONARIO: Nome completo do colaborador (para conferência)",
            "3. COMPETENCIA: Mês/Ano no formato MM/YYYY (ex: 01/2026 para Janeiro de 2026)",
            "4. BASE_FGTS: Valor da base de cálculo do FGTS (salário bruto)",
            "5. EMPRESA: (Opcional) Código da empresa do vínculo para esta linha (recomendado em grupos com múltiplos vínculos)",
            "6. VALOR_FGTS: (Opcional) Valor do FGTS - se não informar, será calculado 8% da base",
            "7. PAGO: (Opcional) Se o FGTS foi pago (SIM ou NÃO)",
            "8. DATA_PAGTO: (Opcional) Data do pagamento no formato dd/mm/yyyy",
            "9. VALOR_PAGO: (Opcional) Valor efetivamente pago",
            "10. PARCELA_13: (Opcional) Use 1 para 13º 1ª parcela, 2 para 13º 2ª parcela; deixe em branco para mês normal",
            "",
            "⚠️ IMPORTANTE:",
            "• O colaborador deve estar cadastrado no sistema",
            "• O lançamento será vinculado ao vínculo do colaborador na empresa selecionada (ou na coluna EMPRESA) e na competência informada",
            "• Se não existir vínculo ativo na competência, a linha será rejeitada (mais seguro)",
            "• A competência deve estar no formato MM/YYYY",
            "• Valores devem usar ponto como separador decimal (ex: 3500.00)",
            "• Delete a linha de exemplo antes de importar",
        ]
        
        for idx, text in enumerate(instructions_text, 5):
            cell = ws.cell(row=idx, column=1)
            cell.value = text
            if text.startswith("⚠️"):
                cell.font = Font(bold=True, color="e53e3e")
            else:
                cell.font = Font(size=10)
        
        # Ajustar largura da coluna de instruções
        ws.merge_cells(f'A5:J{4+len(instructions_text)}')
        
        # Retornar bytes do arquivo
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer.getvalue()
    
    @staticmethod
    def import_lancamentos_from_file(file, empresa, user):
        """
        Importa lançamentos de um arquivo XLSX para uma empresa específica
        
        Args:
            file: Arquivo XLSX
            empresa: Instância de Empresa
            user: Usuário que está fazendo a importação
            
        Returns:
            dict: Resultado da importação com estatísticas e erros
        """
        
        # Nota: empresa pode ser None quando o XLSX traz a coluna EMPRESA por linha.
        
        # Processar arquivo
        try:
            wb = openpyxl.load_workbook(file, data_only=True)
            ws = wb.active
        except openpyxl.utils.exceptions.InvalidFileException:
            raise ValueError("❌ Arquivo inválido. Por favor, envie um arquivo XLSX válido.")
        except Exception as e:
            raise ValueError(f"❌ Erro ao ler arquivo: {str(e)}. Verifique se o arquivo não está corrompido.")
        
        # Validar se planilha tem dados
        if ws.max_row < 2:
            raise ValueError("❌ Arquivo vazio. O arquivo deve conter pelo menos uma linha de dados além do cabeçalho.")
        
        # Validar headers
        headers = [cell.value for cell in ws[1]]
        headers_upper = [h.upper().strip() if h else '' for h in headers]

        has_empresa_column = 'EMPRESA' in headers_upper

        if not has_empresa_column and not empresa:
            raise ValueError(
                "❌ Selecione uma empresa para importar ou preencha a coluna EMPRESA no arquivo."
            )

        # Se não houver coluna EMPRESA, preserva o comportamento antigo (importação para uma empresa específica)
        if not has_empresa_column and empresa:
            if not is_empresa_allowed(user, empresa.codigo):
                raise ValueError(
                    f"Empresa '{empresa.nome}' não possui permissão para importar lançamentos. "
                    f"Verifique o status do plano."
                )

            try:
                billing_customer = BillingCustomer.objects.get(empresa=empresa)
            except BillingCustomer.DoesNotExist:
                raise ValueError(
                    f"Empresa '{empresa.nome}' não possui billing configurado. "
                    f"Entre em contato com o administrador."
                )

            if billing_customer.status not in ['active', 'trial']:
                raise ValueError(
                    f"Empresa '{empresa.nome}' não possui plano ativo. "
                    f"Status atual: {billing_customer.get_status_display()}"
                )

            if not billing_customer.plan:
                raise ValueError(
                    f"Empresa '{empresa.nome}' não possui plano configurado. "
                    f"Entre em contato com o administrador."
                )
        
        missing_columns = [col for col in LancamentoImportService.REQUIRED_COLUMNS if col not in headers_upper]
        if missing_columns:
            raise ValueError(
                f"❌ Colunas obrigatórias faltando no arquivo: {', '.join(missing_columns)}. "
                f"Por favor, baixe o modelo atualizado e preencha corretamente."
            )
        
        # Criar mapeamento de índices
        column_indices = {col: headers_upper.index(col) for col in LancamentoImportService.REQUIRED_COLUMNS}
        for col in LancamentoImportService.OPTIONAL_COLUMNS:
            if col in headers_upper:
                column_indices[col] = headers_upper.index(col)
        
        # Processar linhas
        result = {
            'success': 0,
            'errors': [],
            'warnings': [],
            'created': 0,
            'updated': 0,
            'skipped': 0
        }
        
        linhas_processadas = 0
        
        billing_cache = {}

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            # Pular linhas vazias
            if not any(row):
                continue
            
            linhas_processadas += 1
            
            try:
                lancamento_data = LancamentoImportService._process_row(
                    row, column_indices, empresa, user, row_idx, billing_cache
                )
                
                if lancamento_data:
                    # Verificar se já existe lançamento para esta competência/parcela
                    existing = Lancamento.objects.filter(
                        empresa=lancamento_data['empresa'],
                        funcionario=lancamento_data['funcionario'],
                        competencia=lancamento_data['competencia'],
                        parcela_13=lancamento_data.get('parcela_13')
                    ).first()
                    
                    if existing:
                        # Atualizar
                        for key, value in lancamento_data.items():
                            if key != 'funcionario':  # Não atualizar funcionario
                                setattr(existing, key, value)
                        existing.full_clean()
                        existing.save()
                        result['updated'] += 1
                    else:
                        # Criar novo
                        novo = Lancamento(**lancamento_data)
                        novo.full_clean()
                        novo.save()
                        result['created'] += 1
                    
                    result['success'] += 1
                else:
                    result['skipped'] += 1
                    
            except Exception as e:
                result['errors'].append({
                    'row': row_idx,
                    'error': str(e)
                })
        
        # Validar se alguma linha foi processada
        if linhas_processadas == 0:
            raise ValueError(
                "❌ Nenhuma linha de dados encontrada no arquivo. "
                "Verifique se você preencheu o arquivo corretamente e removeu a linha de exemplo."
            )
        
        return result
    
    @staticmethod
    def _process_row(row, column_indices, empresa, user, row_idx, billing_cache):
        """Processa uma linha do arquivo e retorna dados do lançamento"""
        
        # Extrair CPF
        cpf_idx = column_indices.get('CPF_FUNCIONARIO')
        cpf = str(row[cpf_idx]).strip() if row[cpf_idx] else ''
        cpf = ''.join(filter(str.isdigit, cpf))  # Remover formatação
        
        if not cpf:
            raise ValueError(f"CPF do funcionário não informado ou inválido")
        
        if len(cpf) != 11:
            raise ValueError(f"CPF inválido: {cpf}. O CPF deve conter 11 dígitos")
        
        # Resolver empresa (por linha) - se existir coluna EMPRESA, ela sobrescreve a seleção do formulário
        empresa_row = empresa
        empresa_idx = column_indices.get('EMPRESA')
        if empresa_idx is not None and row[empresa_idx] not in [None, '']:
            raw = row[empresa_idx]
            if isinstance(raw, (int, float)):
                codigo = str(int(raw))
            else:
                codigo = str(raw).strip()
                if codigo.endswith('.0') and codigo.replace('.', '', 1).isdigit():
                    codigo = str(int(float(codigo)))
            if codigo:
                try:
                    empresa_row = Empresa.objects.get(codigo=codigo)
                except Empresa.DoesNotExist:
                    raise ValueError(f"Empresa '{codigo}' não encontrada")

        if not empresa_row:
            raise ValueError('Empresa não informada. Selecione uma empresa ou preencha a coluna EMPRESA.')

        if not is_empresa_allowed(user, empresa_row.codigo):
            raise ValueError('Você não tem permissão para importar lançamentos para a empresa informada.')

        LancamentoImportService._validate_billing_for_empresa(empresa_row, billing_cache)

        # Extrair competência
        competencia_idx = column_indices.get('COMPETENCIA')
        competencia = str(row[competencia_idx]).strip() if row[competencia_idx] else ''
        
        if not competencia:
            raise ValueError(f"Competência não informada. Use o formato MM/YYYY (ex: 01/2026)")
        
        # Validar formato MM/YYYY
        try:
            if '/' not in competencia:
                raise ValueError("Formato inválido")
            mes, ano = competencia.split('/')
            mes = int(mes)
            ano = int(ano)
            if mes < 1 or mes > 12:
                raise ValueError("Mês deve estar entre 01 e 12")
            if ano < 1900 or ano > 2100:
                raise ValueError("Ano inválido")
            competencia = f"{mes:02d}/{ano}"
        except ValueError as ve:
            raise ValueError(f"Competência inválida: '{competencia}'. Use o formato MM/YYYY (ex: 01/2026). {str(ve)}")
        except Exception:
            raise ValueError(f"Competência inválida: '{competencia}'. Use o formato MM/YYYY (ex: 01/2026)")

        # Resolver funcionário pelo vínculo (empresa + competência)
        funcionario = LancamentoImportService._resolve_funcionario_for_empresa_competencia(
            cpf=cpf,
            empresa=empresa_row,
            competencia=competencia,
        )
        
        # Extrair base FGTS
        base_fgts_idx = column_indices.get('BASE_FGTS')
        base_fgts_value = row[base_fgts_idx]
        
        try:
            if isinstance(base_fgts_value, (int, float)):
                base_fgts = Decimal(str(base_fgts_value))
            else:
                base_fgts_str = str(base_fgts_value).strip().replace(',', '.')
                base_fgts = Decimal(base_fgts_str)
        except (InvalidOperation, ValueError, AttributeError):
            raise ValueError(f"Base FGTS inválida: '{base_fgts_value}'. Use valores numéricos com ponto decimal (ex: 3500.00)")
        
        if base_fgts < 0:
            raise ValueError(f"Base FGTS não pode ser negativa: {base_fgts}")
        
        # Calcular ou extrair valor FGTS
        valor_fgts_idx = column_indices.get('VALOR_FGTS')
        if valor_fgts_idx is not None and row[valor_fgts_idx]:
            try:
                valor_fgts_value = row[valor_fgts_idx]
                if isinstance(valor_fgts_value, (int, float)):
                    valor_fgts = Decimal(str(valor_fgts_value))
                else:
                    valor_fgts_str = str(valor_fgts_value).strip().replace(',', '.')
                    valor_fgts = Decimal(valor_fgts_str)
            except (InvalidOperation, ValueError):
                valor_fgts = base_fgts * Decimal('0.08')
        else:
            valor_fgts = base_fgts * Decimal('0.08')
        
        # Dados do lançamento
        lancamento_data = {
            'empresa': empresa_row,
            'funcionario': funcionario,
            'competencia': competencia,
            'base_fgts': base_fgts,
            'valor_fgts': valor_fgts,
            'pago': False,
            'data_pagto': None,
            'valor_pago': None,
            'parcela_13': None,
        }
        
        # Processar campo PAGO (opcional)
        pago_idx = column_indices.get('PAGO')
        if pago_idx is not None and row[pago_idx]:
            pago_value = str(row[pago_idx]).strip().upper()
            lancamento_data['pago'] = pago_value in ['SIM', 'S', 'TRUE', '1', 'YES']
        
        # Processar DATA_PAGTO (opcional)
        data_pagto_idx = column_indices.get('DATA_PAGTO')
        if data_pagto_idx is not None and row[data_pagto_idx]:
            try:
                data_value = row[data_pagto_idx]
                if isinstance(data_value, datetime):
                    lancamento_data['data_pagto'] = data_value.date()
                else:
                    # Tentar parsear dd/mm/yyyy
                    data_str = str(data_value).strip()
                    lancamento_data['data_pagto'] = datetime.strptime(data_str, '%d/%m/%Y').date()
            except Exception:
                pass  # Ignorar data inválida
        
        # Processar VALOR_PAGO (opcional)
        valor_pago_idx = column_indices.get('VALOR_PAGO')
        if valor_pago_idx is not None and row[valor_pago_idx]:
            try:
                valor_pago_value = row[valor_pago_idx]
                if isinstance(valor_pago_value, (int, float)):
                    lancamento_data['valor_pago'] = Decimal(str(valor_pago_value))
                else:
                    valor_pago_str = str(valor_pago_value).strip().replace(',', '.')
                    lancamento_data['valor_pago'] = Decimal(valor_pago_str)
            except (InvalidOperation, ValueError):
                pass  # Ignorar valor inválido
        
        # Processar PARCELA_13 (opcional)
        # Aceita valores: 1, 2, "1", "2", "SIM" (= 1), "PRIMEIRA" (= 1), "SEGUNDA" (= 2), etc.
        parcela_13_idx = column_indices.get('PARCELA_13')
        if parcela_13_idx is not None and row[parcela_13_idx]:
            try:
                parcela_value = str(row[parcela_13_idx]).strip().upper()
                if parcela_value in ['1', 'PRIMEIRA', 'ADIANTAMENTO', 'SIM']:
                    lancamento_data['parcela_13'] = 1
                elif parcela_value in ['2', 'SEGUNDA', 'DEZEMBRO']:
                    lancamento_data['parcela_13'] = 2
                # Caso contrário deixa None (competência normal)
            except Exception:
                pass  # Ignorar valor inválido
        
        return lancamento_data

    @staticmethod
    def _validate_billing_for_empresa(empresa: Empresa, billing_cache: dict) -> None:
        """Valida billing para uma empresa, com cache simples por código."""
        key = str(getattr(empresa, 'codigo', empresa.pk))
        cached = billing_cache.get(key)
        if cached is True:
            return
        if isinstance(cached, str):
            raise ValueError(cached)

        try:
            billing_customer = BillingCustomer.objects.get(empresa=empresa)
        except BillingCustomer.DoesNotExist:
            msg = (
                f"Empresa '{empresa.nome}' não possui billing configurado. "
                f"Entre em contato com o administrador."
            )
            billing_cache[key] = msg
            raise ValueError(msg)

        if billing_customer.status not in ['active', 'trial']:
            msg = (
                f"Empresa '{empresa.nome}' não possui plano ativo. "
                f"Status atual: {billing_customer.get_status_display()}"
            )
            billing_cache[key] = msg
            raise ValueError(msg)

        if not billing_customer.plan:
            msg = (
                f"Empresa '{empresa.nome}' não possui plano configurado. "
                f"Entre em contato com o administrador."
            )
            billing_cache[key] = msg
            raise ValueError(msg)

        billing_cache[key] = True

    @staticmethod
    def _resolve_funcionario_for_empresa_competencia(*, cpf: str, empresa: Empresa, competencia: str) -> Funcionario:
        """Resolve qual registro de Funcionario usar, considerando vínculos por empresa e competência.

        Um CPF pode ter múltiplos registros de Funcionário (multi-vínculo). Como a planilha de lançamentos
        não informa o vínculo, usamos a empresa selecionada para importação e a competência do lançamento.
        """

        vinculos = FuncionarioVinculo.objects.filter(
            empresa=empresa,
            funcionario__cpf=cpf,
        ).select_related('funcionario').order_by('-data_admissao', '-id')

        if not vinculos.exists():
            raise ValueError(
                f"Colaborador com CPF {cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]} não encontrado na empresa '{empresa.nome}'. "
                f"Certifique-se de que o colaborador está cadastrado e vinculado a esta empresa antes de importar seus lançamentos."
            )

        # Exige vínculo ativo na competência (mais seguro; evita lançar no vínculo errado)
        ativos = []
        for v in vinculos:
            try:
                if v.is_ativo_em_competencia(competencia):
                    ativos.append(v)
            except Exception:
                continue

        if len(ativos) == 1:
            return ativos[0].funcionario

        cpf_fmt = f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else cpf

        if len(ativos) == 0:
            raise ValueError(
                f"Nenhum vínculo ativo encontrado para o CPF {cpf_fmt} na empresa '{empresa.nome}' "
                f"na competência {competencia}. Verifique a competência, a empresa (coluna EMPRESA) e as datas de admissão/demissão do vínculo."
            )

        # Situação rara, mas possível em caso de dados inconsistentes
        raise ValueError(
            f"Vínculo ambíguo: existem múltiplos vínculos ativos para o CPF {cpf_fmt} na empresa '{empresa.nome}' "
            f"na competência {competencia}. Corrija os vínculos antes de importar."
        )
