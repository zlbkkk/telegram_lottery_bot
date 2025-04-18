# Generated by Django 3.2.24 on 2025-03-29 14:17

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('jifen', '0006_auto_20250323_1656'),
        ('choujiang', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='lottery',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, verbose_name='创建时间'),
        ),
        migrations.AlterField(
            model_name='lottery',
            name='creator',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='jifen.user', verbose_name='创建者'),
        ),
        migrations.AlterField(
            model_name='lottery',
            name='description',
            field=models.TextField(blank=True, null=True, verbose_name='描述'),
        ),
        migrations.AlterField(
            model_name='lottery',
            name='draw_time',
            field=models.DateTimeField(blank=True, null=True, verbose_name='开奖时间'),
        ),
        migrations.AlterField(
            model_name='lottery',
            name='group',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='jifen.group', verbose_name='群组'),
        ),
        migrations.AlterField(
            model_name='lottery',
            name='lottery_type',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='choujiang.lotterytype', verbose_name='抽奖类型'),
        ),
        migrations.AlterField(
            model_name='lottery',
            name='notify_winners_privately',
            field=models.BooleanField(default=True, verbose_name='私信通知中奖者'),
        ),
        migrations.AlterField(
            model_name='lottery',
            name='signup_deadline',
            field=models.DateTimeField(blank=True, null=True, verbose_name='报名截止时间'),
        ),
        migrations.AlterField(
            model_name='lottery',
            name='status',
            field=models.CharField(choices=[('DRAFT', '草稿'), ('ACTIVE', '进行中'), ('PAUSED', '已暂停'), ('ENDED', '已结束'), ('CANCELLED', '已取消')], default='DRAFT', max_length=20, verbose_name='状态'),
        ),
        migrations.AlterField(
            model_name='lottery',
            name='title',
            field=models.CharField(max_length=100, verbose_name='标题'),
        ),
        migrations.AlterField(
            model_name='lottery',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, verbose_name='更新时间'),
        ),
    ]
