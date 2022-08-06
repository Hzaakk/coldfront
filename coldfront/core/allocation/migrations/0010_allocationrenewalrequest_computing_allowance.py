# Generated by Django 3.2.5 on 2022-07-31 19:12

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('resource', '0003_add_resource_is_unique_per_project'),
        ('allocation', '0009_securedirrequest_securedirrequeststatuschoice'),
    ]

    operations = [
        migrations.AddField(
            model_name='allocationrenewalrequest',
            name='computing_allowance',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='renewal_computing_allowance', to='resource.resource'),
        ),
    ]