# -*- coding: utf-8 -*-

from django.contrib import admin
from django.conf.urls.defaults import patterns, url
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404
from django.conf import settings

from ios_notifications.models import (
    Device, Notification, APNService, FeedbackService)


class APNServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'hostname')


class DeviceAdmin(admin.ModelAdmin):
    fields = ('user', 'token', 'is_active', 'service')
    list_display = (
        'user', 'token', 'is_active', 'service', 'last_notified_at',
        'platform', 'display', 'os_version')


class NotificationAdmin(admin.ModelAdmin):
    exclude = ('last_sent_at',)
    list_display = ('message', 'badge', 'sound', 'created_at', 'last_sent_at')

    def get_urls(self):
        urls = super(NotificationAdmin, self).get_urls()
        notification_urls = patterns('',
            url(r'^(?P<id>\d+)/push-notification/$', self.admin_site.admin_view(self.admin_push_notification),
            name='admin_push_notification'),)
        return notification_urls + urls

    def admin_push_notification(self, request, **kwargs):
        notification = get_object_or_404(Notification, **kwargs)
        num_devices = 0
        if request.method == 'POST':
            service = APNService.objects.get(pk=settings.IOS_SERVICE_ID)
            devices = service.device_set.filter(is_active=True)
            service.push_notification_to_devices(
                notification,
                devices)
            num_devices = len(devices)
        return TemplateResponse(
            request,
            'admin/ios_notifications/notification/push_notification.html',
            {'notification': notification,
                'num_devices': num_devices,
                'sent': request.method == 'POST'},
            current_app='ios_notifications')

admin.site.register(Device, DeviceAdmin)
admin.site.register(Notification, NotificationAdmin)
admin.site.register(APNService, APNServiceAdmin)
admin.site.register(FeedbackService)
