# Generated by Django 3.2.24 on 2025-03-23 08:47

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jifen', '0004_pointrule_checkin_points_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='pointrule',
            name='points_enabled',
            field=models.BooleanField(default=True, help_text='总积分功能开关，控制所有积分功能'),
        ),
    ]
