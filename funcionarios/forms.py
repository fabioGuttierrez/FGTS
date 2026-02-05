from django import forms
from decimal import Decimal

from fgtsweb.utils.validators import digits_only, normalize_upper_ascii, validate_cpf
from .models import Funcionario
from empresas.models import Empresa
from empresas.models_grupo import FuncionarioVinculo
from .forms_transferencia import TransferenciaFuncionarioForm

class FuncionarioForm(forms.ModelForm):
    salario_inicial = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        label='Salário Inicial (Base FGTS)',
        help_text='Se informado, será criado automaticamente o primeiro lançamento de FGTS na competência de admissão',
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ex: 3500.00',
            'step': '0.01'
        })
    )
    
    class Meta:
        model = Funcionario
        fields = ['nome', 'pis', 'cpf', 'cbo', 'carteira_profissional', 
                  'serie_carteira', 'data_nascimento', 'observacao']
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control'}),
            'pis': forms.TextInput(attrs={'class': 'form-control'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control'}),
            'cbo': forms.TextInput(attrs={'class': 'form-control'}),
            'carteira_profissional': forms.TextInput(attrs={'class': 'form-control'}),
            'serie_carteira': forms.TextInput(attrs={'class': 'form-control'}),
            # Inputs HTML5 type="date" exigem valor no formato ISO (YYYY-MM-DD)
            'data_nascimento': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Campos extras para vínculo
        self.fields['empresa'] = forms.ModelChoiceField(
            queryset=Empresa.objects.all(),
            required=True,
            label='Empresa',
            widget=forms.Select(attrs={'class': 'form-select'})
        )
        self.fields['data_admissao'] = forms.DateField(
            required=True,
            label='Data de Admissão',
            widget=forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'})
        )
        self.fields['data_demissao'] = forms.DateField(
            required=False,
            label='Data de Demissão',
            widget=forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'})
        )
        # Pré-popula dados do vínculo atual ao editar
        instance = getattr(self, 'instance', None)
        if instance and getattr(instance, 'pk', None):
            vinculo = instance.vinculo_atual()
            if vinculo:
                self.fields['empresa'].initial = vinculo.empresa
                self.fields['data_admissao'].initial = vinculo.data_admissao
                self.fields['data_demissao'].initial = vinculo.data_demissao
                if vinculo.salario:
                    self.fields['salario_inicial'].initial = vinculo.salario
        # Django 5+ usa dict normal, não OrderedDict; não há garantia de ordem, mas não quebra o form
        # Se quiser garantir ordem, reordene manualmente ou ajuste o template

    def clean_nome(self):
        nome = self.cleaned_data.get('nome')
        return normalize_upper_ascii(nome, allow_digits=False)

    def clean_cpf(self):
        cpf = self.cleaned_data.get('cpf')
        return validate_cpf(cpf) if cpf else ''

    def clean_pis(self):
        # Regra atual permite CPF no lugar do PIS; portanto não validamos DV.
        # Normalizamos para somente dígitos para manter consistência de armazenamento.
        pis = digits_only(self.cleaned_data.get('pis'))
        if not pis:
            return ''
        if len(pis) > 15:
            raise forms.ValidationError('PIS muito longo. Informe no máximo 15 dígitos.')
        return pis

    def clean(self):
        cleaned_data = super().clean()
        # Normalização dos demais campos textuais
        cleaned_data['cbo'] = normalize_upper_ascii(cleaned_data.get('cbo'), allow_digits=True)
        cleaned_data['carteira_profissional'] = normalize_upper_ascii(cleaned_data.get('carteira_profissional'), allow_digits=True)
        cleaned_data['serie_carteira'] = normalize_upper_ascii(cleaned_data.get('serie_carteira'), allow_digits=True)
        if cleaned_data.get('observacao'):
            cleaned_data['observacao'] = normalize_upper_ascii(cleaned_data.get('observacao'), allow_digits=True)
        # Deixa o model.clean enxergar a empresa/datas antes de salvar
        self.instance._empresa_override = cleaned_data.get('empresa')
        self.instance._data_admissao_override = cleaned_data.get('data_admissao')
        self.instance._data_demissao_override = cleaned_data.get('data_demissao')
        return cleaned_data

    def save(self, commit=True):
        funcionario = super().save(commit=commit)
        empresa = self.cleaned_data['empresa']
        data_admissao = self.cleaned_data['data_admissao']
        data_demissao = self.cleaned_data.get('data_demissao')
        salario = self.cleaned_data.get('salario_inicial')
        # Atualiza vínculo atual (mesma empresa) ou cria novo se necessário
        vinculo = funcionario.vinculo_atual()
        if vinculo and vinculo.empresa == empresa:
            vinculo.data_admissao = data_admissao
            vinculo.data_demissao = data_demissao
            vinculo.salario = salario or None
            vinculo.save()
        elif not funcionario.vinculos.filter(empresa=empresa, data_admissao=data_admissao).exists():
            FuncionarioVinculo.objects.create(
                funcionario=funcionario,
                empresa=empresa,
                data_admissao=data_admissao,
                data_demissao=data_demissao,
                salario=salario or None
            )
        return funcionario
