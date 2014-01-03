# coding=utf-8

import xadmin

from xadmin import views
from xadmin.plugins import batch

from django.conf.urls.defaults import patterns, url
from django.template.response import TemplateResponse
from django.shortcuts import get_object_or_404
from django.http import HttpResponseBadRequest
from django.core.urlresolvers import reverse

from models import (
    Device, Notification, APNService, AndroidDevice, GCMService)
from forms import NotificationPushForm


class DeviceAdmin(object):
    fields = (
        'user', 'token', 'is_active',
        'added_at', 'deactivated_at', 'last_notified_at')
    readonly_fields = ('added_at', 'deactivated_at', 'last_notified_at')
    list_display = (
        'user', 'token', 'is_active', 'last_notified_at',)
    actions = [batch.BatchChangeAction, ]
    batch_fields = ('is_active', )

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
                notification = form.cleaned_data['notification']
                setattr(notification, '_uri', reverse(
                    'api_dispatch_detail',
                    kwargs={
                        'resource_name': 'notification',
                        'pk': str(form.cleaned_data['id']),
                        'api_name': 'v1'}))
                sent = service.push_notification_to_devices(
                    notification, [device.token])
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


class AndroidDeviceAdmin(object):
    fields = (
        'user', 'token', 'is_active',
        'added_at', 'deactivated_at', 'last_notified_at')
    readonly_fields = ('added_at', 'deactivated_at', 'last_notified_at')
    list_display = ('user', 'token', 'is_active')
    actions = [batch.BatchChangeAction, ]
    batch_fields = ('is_active', )

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
                notification = form.cleaned_data['notification']
                setattr(notification, '_uri', reverse(
                    'api_dispatch_detail',
                    kwargs={
                        'resource_name': 'notification',
                        'pk': str(form.cleaned_data['id']),
                        'api_name': 'v1'}))
                sent = GCMService().push_notification_to_devices(
                    notification, [device.token])
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


class NotificationAdmin(views.ModelAdminView):
    exclude = ('last_sent_at', 'square_picture_mobile', 'picture_mobile')
    list_display = ('message', 'badge', 'sound', 'created_at', 'last_sent_at')
    model = Notification

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


xadmin.site.register(Device, DeviceAdmin)
xadmin.site.register(AndroidDevice, AndroidDeviceAdmin)
xadmin.site.register(Notification, NotificationAdmin)
