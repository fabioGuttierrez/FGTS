from django import forms
from empresas.models import Empresa
from funcionarios.models import Funcionario

class RelatorioCompetenciaForm(forms.Form):
    empresa = forms.ModelChoiceField(queryset=Empresa.objects.all(), label='Empresa')
    funcionario = forms.ModelChoiceField(queryset=Funcionario.objects.all(), label='Funcionário (opcional)', required=False)
    competencia = forms.CharField(label='Competência', required=False, help_text='MM/YYYY')
    competencias = forms.CharField(label='Múltiplas competências', required=False, help_text='Uma por linha no formato MM/YYYY', widget=forms.Textarea(attrs={'rows': 3}))
    data_pagamento = forms.DateField(label='Data de Pagamento', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
