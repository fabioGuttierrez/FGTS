from django import forms
from decimal import Decimal
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
            'data_nascimento': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
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
            widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
        )
        self.fields['data_demissao'] = forms.DateField(
            required=False,
            label='Data de Demissão',
            widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
        )
        # Django 5+ usa dict normal, não OrderedDict; não há garantia de ordem, mas não quebra o form
        # Se quiser garantir ordem, reordene manualmente ou ajuste o template

    def clean(self):
        cleaned_data = super().clean()
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
        # Cria vínculo se não existir para este período
        if not funcionario.vinculos.filter(empresa=empresa, data_admissao=data_admissao).exists():
            FuncionarioVinculo.objects.create(
                funcionario=funcionario,
                empresa=empresa,
                data_admissao=data_admissao,
                data_demissao=data_demissao,
                salario=salario or None
            )
        return funcionario
