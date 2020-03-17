# Generated by Django 2.2.3 on 2019-11-09 23:55

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0062_hackathonevent_show_results'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='match_profiles',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=25), blank=True, default=list, size=None),
        ),
        migrations.AddField(
            model_name='profile',
            name='related_profiles',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.CharField(max_length=25), blank=True, default=list, size=None),
        ),
    ]
