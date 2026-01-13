# Generated migration for adding parcela_13 field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lancamentos', '0005_remove_lancamento_idx_lancamento_empresa_comp_pago_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='lancamento',
            name='parcela_13',
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(1, '13º Salário - 1ª Parcela'), (2, '13º Salário - 2ª Parcela')],
                help_text='Se preenchido, indica que é uma das 2 parcelas do 13º salário',
                null=True,
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterUniqueTogether(
                    name='lancamento',
                    unique_together={('funcionario', 'competencia', 'parcela_13')},
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE lancamentos_lancamento "
                        "DROP CONSTRAINT IF EXISTS lancamentos_lancamento_funcionario_id_competencia_key;"
                    ),
                    reverse_sql=(
                        "ALTER TABLE lancamentos_lancamento "
                        "ADD CONSTRAINT lancamentos_lancamento_funcionario_id_competencia_key "
                        "UNIQUE (funcionario_id, competencia);"
                    ),
                ),
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE lancamentos_lancamento "
                        "ADD CONSTRAINT "
                        "lancamentos_lancamento_funcionario_id_competencia_parcela_13_key "
                        "UNIQUE (funcionario_id, competencia, parcela_13);"
                    ),
                    reverse_sql=(
                        "ALTER TABLE lancamentos_lancamento "
                        "DROP CONSTRAINT IF EXISTS "
                        "lancamentos_lancamento_funcionario_id_competencia_parcela_13_key;"
                    ),
                ),
            ],
        ),
    ]
