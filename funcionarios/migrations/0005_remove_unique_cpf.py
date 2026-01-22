from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('funcionarios', '0004_alter_funcionario_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='funcionario',
            name='cpf',
            field=models.CharField(max_length=14, verbose_name='CPF'),
        ),
        migrations.RunSQL(
            sql='''
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_type = 'UNIQUE'
                        AND table_name = 'funcionarios_funcionario'
                        AND constraint_name = 'funcionarios_funcionario_cpf_key'
                    ) THEN
                        ALTER TABLE funcionarios_funcionario DROP CONSTRAINT funcionarios_funcionario_cpf_key;
                    END IF;
                END$$;
            ''',
            reverse_sql='ALTER TABLE funcionarios_funcionario ADD CONSTRAINT funcionarios_funcionario_cpf_key UNIQUE (cpf);',
        ),
    ]
