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


class LancamentoImportService:
    """Serviço para gerenciar importação e exportação de lançamentos FGTS em XLSX"""
    
    REQUIRED_COLUMNS = [
        'CPF_FUNCIONARIO', 'NOME_FUNCIONARIO', 'COMPETENCIA', 'BASE_FGTS'
    ]
    
    OPTIONAL_COLUMNS = [
        'VALOR_FGTS', 'PAGO', 'DATA_PAGTO', 'VALOR_PAGO'
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
            '280.00',               # VALOR_FGTS (8% da base)
            'NÃO',                  # PAGO (SIM/NÃO)
            '',                     # DATA_PAGTO (dd/mm/yyyy)
            '',                     # VALOR_PAGO
        ]
        
        for col_idx, value in enumerate(example_data, 1):
            cell = ws.cell(row=2, column=col_idx)
            cell.value = value
            cell.fill = example_fill
            cell.border = border
            cell.alignment = Alignment(horizontal='left', vertical='center')
        
        # Instruções
        ws.merge_cells('A4:H4')
        instructions = ws['A4']
        instructions.value = "INSTRUÇÕES DE PREENCHIMENTO"
        instructions.font = Font(bold=True, size=12, color="667eea")
        instructions.alignment = Alignment(horizontal='left')
        
        instructions_text = [
            "1. CPF_FUNCIONARIO: CPF do colaborador (apenas números)",
            "2. NOME_FUNCIONARIO: Nome completo do colaborador (para conferência)",
            "3. COMPETENCIA: Mês/Ano no formato MM/YYYY (ex: 01/2026 para Janeiro de 2026)",
            "4. BASE_FGTS: Valor da base de cálculo do FGTS (salário bruto)",
            "5. VALOR_FGTS: (Opcional) Valor do FGTS - se não informar, será calculado 8% da base",
            "6. PAGO: (Opcional) Se o FGTS foi pago (SIM ou NÃO)",
            "7. DATA_PAGTO: (Opcional) Data do pagamento no formato dd/mm/yyyy",
            "8. VALOR_PAGO: (Opcional) Valor efetivamente pago",
            "",
            "⚠️ IMPORTANTE:",
            "• O colaborador deve estar cadastrado no sistema",
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
        ws.merge_cells(f'A5:H{4+len(instructions_text)}')
        
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
        
        # Validar permissões da empresa (billing)
        if not is_empresa_allowed(user, empresa.codigo):
            raise ValueError(
                f"Empresa '{empresa.nome}' não possui permissão para importar lançamentos. "
                f"Verifique o status do plano."
            )
        
        # Validar billing e plano
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
        
        # Processar arquivo
        try:
            wb = openpyxl.load_workbook(file, data_only=True)
            ws = wb.active
        except Exception as e:
            raise ValueError(f"Erro ao ler arquivo: {str(e)}")
        
        # Validar headers
        headers = [cell.value for cell in ws[1]]
        headers_upper = [h.upper().strip() if h else '' for h in headers]
        
        missing_columns = [col for col in LancamentoImportService.REQUIRED_COLUMNS if col not in headers_upper]
        if missing_columns:
            raise ValueError(f"Colunas obrigatórias faltando: {', '.join(missing_columns)}")
        
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
        
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            # Pular linhas vazias
            if not any(row):
                continue
            
            try:
                lancamento_data = LancamentoImportService._process_row(
                    row, column_indices, empresa, row_idx
                )
                
                if lancamento_data:
                    # Verificar se já existe lançamento para esta competência
                    existing = Lancamento.objects.filter(
                        empresa=empresa,
                        funcionario=lancamento_data['funcionario'],
                        competencia=lancamento_data['competencia']
                    ).first()
                    
                    if existing:
                        # Atualizar
                        for key, value in lancamento_data.items():
                            if key != 'funcionario':  # Não atualizar funcionario
                                setattr(existing, key, value)
                        existing.save()
                        result['updated'] += 1
                    else:
                        # Criar novo
                        Lancamento.objects.create(**lancamento_data)
                        result['created'] += 1
                    
                    result['success'] += 1
                else:
                    result['skipped'] += 1
                    
            except Exception as e:
                result['errors'].append({
                    'row': row_idx,
                    'error': str(e)
                })
        
        return result
    
    @staticmethod
    def _process_row(row, column_indices, empresa, row_idx):
        """Processa uma linha do arquivo e retorna dados do lançamento"""
        
        # Extrair CPF
        cpf_idx = column_indices.get('CPF_FUNCIONARIO')
        cpf = str(row[cpf_idx]).strip() if row[cpf_idx] else ''
        cpf = ''.join(filter(str.isdigit, cpf))  # Remover formatação
        
        if not cpf:
            raise ValueError(f"CPF não informado")
        
        # Buscar funcionário
        try:
            funcionario = Funcionario.objects.get(cpf=cpf, empresa=empresa)
        except Funcionario.DoesNotExist:
            raise ValueError(f"Colaborador com CPF {cpf} não encontrado na empresa")
        
        # Extrair competência
        competencia_idx = column_indices.get('COMPETENCIA')
        competencia = str(row[competencia_idx]).strip() if row[competencia_idx] else ''
        
        if not competencia:
            raise ValueError(f"Competência não informada")
        
        # Validar formato MM/YYYY
        try:
            if '/' not in competencia:
                raise ValueError("Formato inválido")
            mes, ano = competencia.split('/')
            mes = int(mes)
            ano = int(ano)
            if mes < 1 or mes > 12:
                raise ValueError("Mês inválido")
            if ano < 1900 or ano > 2100:
                raise ValueError("Ano inválido")
            competencia = f"{mes:02d}/{ano}"
        except Exception:
            raise ValueError(f"Competência inválida: {competencia}. Use formato MM/YYYY")
        
        # Extrair base FGTS
        base_fgts_idx = column_indices.get('BASE_FGTS')
        base_fgts_value = row[base_fgts_idx]
        
        try:
            if isinstance(base_fgts_value, (int, float)):
                base_fgts = Decimal(str(base_fgts_value))
            else:
                base_fgts_str = str(base_fgts_value).strip().replace(',', '.')
                base_fgts = Decimal(base_fgts_str)
        except (InvalidOperation, ValueError):
            raise ValueError(f"Base FGTS inválida: {base_fgts_value}")
        
        if base_fgts < 0:
            raise ValueError(f"Base FGTS não pode ser negativa")
        
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
            'empresa': empresa,
            'funcionario': funcionario,
            'competencia': competencia,
            'base_fgts': base_fgts,
            'valor_fgts': valor_fgts,
            'pago': False,
            'data_pagto': None,
            'valor_pago': None,
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
        
        return lancamento_data
