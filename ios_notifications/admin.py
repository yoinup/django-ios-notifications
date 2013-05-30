# -*- coding: utf-8 -*-

from django.contrib import admin
from django.conf.urls.defaults import patterns, url
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404
from django.conf import settings
from django.http import HttpResponseBadRequest

from ios_notifications.models import (
    Device, Notification, APNService, FeedbackService, AndroidDevice,
    GCMService)
from forms import NotificationPushForm


class DeviceAdmin(admin.ModelAdmin):
    fields = (
        'user', 'token', 'is_active',
        'added_at', 'deactivated_at', 'last_notified_at')
    readonly_fields = ('added_at', 'deactivated_at', 'last_notified_at')
    list_display = (
        'user', 'token', 'is_active', 'last_notified_at',)
    change_form_template = 'admin/ios_notifications/device/change_form.html'

    def get_urls(self):
        urls = super(DeviceAdmin, self).get_urls()
        notification_urls = patterns(
            '',
            url(r'^(?P<id>\d+)/push-notification/$',
                self.admin_site.admin_view(self.admin_push_notification),
                name='admin_device_push_notification'),)
        return notification_urls + urls

    def change_view(self, request, object_id, form_url='', extra_context=None):
        if not hasattr(extra_context, 'update'):
            extra_context = {}
        extra_context.update({'notifications': NotificationPushForm()})
        return super(DeviceAdmin, self).change_view(
            request, object_id, form_url=form_url, extra_context=extra_context)

    def admin_push_notification(self, request, **kwargs):
        device = get_object_or_404(Device, **kwargs)
        if request.method == 'POST':
            form = NotificationPushForm(request.POST)
            if form.is_valid():
                service = APNService()
                sent = service.push_notification_to_devices(
                    form.cleaned_data['notification'],
                    [device.token])
            else:
                return TemplateResponse(
                    request,
                    'admin/ios_notifications/device/push_notification.html',
                    {'success': False},
                    current_app='ios_notifications')
        else:
            return HttpResponseBadRequest()
        return TemplateResponse(
            request,
            'admin/ios_notifications/device/push_notification.html',
            {'notification': form.cleaned_data['notification'],
                'sent': sent,
                'success': True},
            current_app='ios_notifications')


class AndroidDeviceAdmin(admin.ModelAdmin):
    fields = (
        'user', 'token', 'is_active',
        'added_at', 'deactivated_at', 'last_notified_at')
    readonly_fields = ('added_at', 'deactivated_at', 'last_notified_at')
    list_display = ('user', 'token', 'is_active')
    change_form_template = \
        'admin/ios_notifications/device/change_form_android.html'

    def get_urls(self):
        urls = super(AndroidDeviceAdmin, self).get_urls()
        notification_urls = patterns(
            '',
            url(r'^(?P<id>\d+)/push-notification/$',
                self.admin_site.admin_view(self.admin_push_notification),
            name='admin_android_device_push_notification'),)
        return notification_urls + urls

    def change_view(self, request, object_id, form_url='', extra_context=None):
        if not hasattr(extra_context, 'update'):
            extra_context = {}
        extra_context.update({'notifications': NotificationPushForm()})
        return super(AndroidDeviceAdmin, self).change_view(
            request, object_id, form_url=form_url, extra_context=extra_context)

    def admin_push_notification(self, request, **kwargs):
        device = get_object_or_404(AndroidDevice, **kwargs)
        if request.method == 'POST':
            form = NotificationPushForm(request.POST)
            if form.is_valid():
                sent = GCMService().push_notification_to_devices(
                    form.cleaned_data['notification'], [device.token])
            else:
                return TemplateResponse(
                    request,
                    'admin/ios_notifications/device/push_notification.html',
                    {'success': False},
                    current_app='ios_notifications')
        else:
            return HttpResponseBadRequest()
        return TemplateResponse(
            request,
            'admin/ios_notifications/device/push_notification.html',
            {'notification': form.cleaned_data['notification'],
                'sent': sent,
                'success': True},
            current_app='ios_notifications')


class NotificationAdmin(admin.ModelAdmin):
    exclude = ('last_sent_at',)
    list_display = ('message', 'badge', 'sound', 'created_at', 'last_sent_at')
    change_form_template = \
        'admin/ios_notifications/notification/change_form.html'

    def get_urls(self):
        urls = super(NotificationAdmin, self).get_urls()
        notification_urls = patterns(
            '',
            url(r'^(?P<id>\d+)/push-notification/$',
                self.admin_site.admin_view(self.admin_push_notification),
                name='admin_push_notification'),
            url(r'^(?P<id>\d+)/android-notification/$',
                self.admin_site.admin_view(
                    self.admin_android_push_notification),
                name='admin_android_notification'),)
        return notification_urls + urls

    def admin_push_notification(self, request, **kwargs):
        notification = get_object_or_404(Notification, **kwargs)
        num_devices = 0
        if request.method == 'POST':
            service = APNService()
            devices = Device.objects.filter(
                is_active=True).values_list('token', flat=True)
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

    def admin_android_push_notification(self, request, **kwargs):
        notification = get_object_or_404(Notification, **kwargs)
        num_devices = 0
        if request.method == 'POST':
            num_devices = GCMService().push_notification_to_devices(
                notification)
        return TemplateResponse(
            request,
            'admin/ios_notifications/notification/push_notification.html',
            {'notification': notification,
                'num_devices': num_devices,
                'sent': request.method == 'POST'},
            current_app='ios_notifications')


admin.site.register(Device, DeviceAdmin)
admin.site.register(AndroidDevice, AndroidDeviceAdmin)
admin.site.register(Notification, NotificationAdmin)
