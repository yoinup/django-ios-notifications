# coding=utf-8

from django import forms
from models import Notification

class NotificationPushForm(forms.Form):
    notification = forms.ModelChoiceField(queryset=Notification.objects.all(), required=True)
