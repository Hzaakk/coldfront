# Generated by Django 3.2.5 on 2022-02-09 17:27

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
        ('user', '0008_identitylinkingrequest_identitylinkingrequeststatuschoice'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='billing_activity',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='billing.billingactivity'),
        ),
    ]
