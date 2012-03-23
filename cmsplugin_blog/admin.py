from cms.forms.widgets import PlaceholderPluginEditorWidget
from cms.models.pluginmodel import CMSPlugin
from cms.utils import get_language_from_request
from cmsplugin_blog.models import Entry, EntryTitle
from cmsplugin_blog.widgets import AutoCompleteTagInput
from django import forms
from django.contrib import admin
from django.conf import settings
from django.forms import CharField, BooleanField
from django.http import HttpResponse
from django.template.defaultfilters import title
from django.utils.text import capfirst
from django.utils.translation import ugettext_lazy as _
from simple_translation.admin import PlaceholderTranslationAdmin
from simple_translation.forms import TranslationModelForm
from simple_translation.utils import get_translation_queryset

from django.shortcuts import render, redirect
from django.core.urlresolvers import reverse

class EntryForm(TranslationModelForm):
    publish_on_facebook = BooleanField(required=False)

    class Meta:
        model = Entry
        widgets = {'tags': AutoCompleteTagInput}

    def __init__(self, *args, **kwargs):
        super(EntryForm, self).__init__(*args, **kwargs)
        instance = kwargs.pop('instance', None)
        if instance:
          self.fields['publish_on_facebook'].initial = instance.facebook_published != None

    def save(self, force_insert=False, force_update=False, commit=True):
        fb_publ = None
        if ('entry' in self.initial and self.initial['entry'] > 0):
          fb_publ = Entry.objects.get(pk=self.initial['entry']).facebook_published
        instance = super(TranslationModelForm, self).save(commit)
        instance.facebook_published = fb_publ
        instance.save()
        instance.publish_on_facebook = False
        if not instance.facebook_published and self.cleaned_data['publish_on_facebook']:
          instance.publish_on_facebook = True
        return instance
        
class M2MPlaceholderAdmin(PlaceholderTranslationAdmin):
    
    def get_form(self, request, obj=None, **kwargs):
        """
        Get PageForm for the Page model and modify its fields depending on
        the request.
        """
        form = super(M2MPlaceholderAdmin, self).get_form(request, obj, **kwargs)
        
        if obj:        
            
            for placeholder_name in obj._meta.get_field('placeholders').placeholders:
                
                placeholder, created = obj.placeholders.get_or_create(slot=placeholder_name)
                
                defaults = {'label': capfirst(placeholder_name), 'help_text': ''}
                defaults.update(kwargs)
                
                widget = PlaceholderPluginEditorWidget(request, self.placeholder_plugin_filter)
                widget.choices = []
                
                form.base_fields[placeholder.slot] = CharField(widget=widget, required=False)   
                form.base_fields[placeholder.slot].initial = placeholder.pk
                
        return form
        
    def get_fieldsets(self, request, obj=None):
        """
        Add fieldsets of placeholders to the list of already existing
        fieldsets.
        """
        given_fieldsets = super(M2MPlaceholderAdmin, self).get_fieldsets(request, obj=None)

        if obj: # edit
            for placeholder_name in obj._meta.get_field('placeholders').placeholders:
                given_fieldsets += [(title(placeholder_name), {'fields':[placeholder_name], 'classes':['plugin-holder']})]

        return given_fieldsets
            
    def move_plugin(self, request): # pragma: no cover
        
        def get_placeholder(plugin, request):
            
            return plugin.placeholder
            
        if request.method == "POST":    
            if 'plugin_id' in request.POST:
                plugin = CMSPlugin.objects.get(pk=int(request.POST['plugin_id']))
                if "placeholder" in request.POST:
                    obj = plugin.placeholder._get_attached_model().objects.get(placeholders__cmsplugin=plugin)
                    placeholder = obj.placeholders.get(slot=request.POST["placeholder"])
                else:
                    placeholder = plugin.placeholder
                # plugin positions are 0 based, so just using count here should give us 'last_position + 1'
                position = CMSPlugin.objects.filter(placeholder=placeholder).count()
                plugin.placeholder = placeholder
                plugin.position = position
                plugin.save()
            pos = 0
            if 'ids' in request.POST:
                for id in request.POST['ids'].split("_"):
                    plugin = CMSPlugin.objects.get(pk=id)
                    if plugin.position != pos:
                        plugin.position = pos
                        plugin.save()
                    pos += 1
            else:
                HttpResponse(str("error"))
            return HttpResponse(str("ok"))
        else:
            return HttpResponse(str("error"))        
                
class BaseEntryAdmin(M2MPlaceholderAdmin):
    
    form = EntryForm
    
    # needed because of admin validation
    prepopulated_fields = not settings.DEBUG and {'slug': ('title',)} or {}
    
    search_fields = ('entrytitle__title', 'tags')
    list_display = ('title', 'languages', 'author', 'is_published', 'pub_date')
    list_editable = ('is_published',)
    list_filter = ('is_published', 'pub_date')
    date_hierarchy = 'pub_date'

    def author(self, obj):
        return get_translation_queryset(obj)[0].author
    author.short_description = _('author')
    author.admin_order_field = 'entrytitle__author'

    def title(self, obj):
        return get_translation_queryset(obj)[0].title
    title.short_description = _('title')
    title.admin_order_field = 'entrytitle__title'
    
    # needed because of admin validation
    def get_fieldsets(self, request, obj=None):
        fieldsets = super(BaseEntryAdmin, self).get_fieldsets(request, obj=obj)
        fieldsets[0] = (None, {'fields': (
            'language',
            'is_published',
            'pub_date',
            'author',
            'title',
            'slug',
            'tags'
        )})
        if settings.CMS_BLOG_FACEBOOK:
          fieldsets[0][1]['fields'] = fieldsets[0][1]['fields'] + ('publish_on_facebook',)
        return fieldsets
        
    def save_translated_model(self, request, obj, translation_obj, form, change):
        if not translation_obj.author:
            translation_obj.author=request.user
        super(BaseEntryAdmin, self).save_translated_model(request, obj, translation_obj, form, change)

    def response_change(self, request, obj, post_url_continue=None):
        import django
        resp = super(BaseEntryAdmin, self).response_change(request, obj)
        if obj.publish_on_facebook:
          url = 'https://www.facebook.com/dialog/oauth?client_id='
          url = url + settings.CMS_BLOG_FACEBOOK['app_id']
          url = url + '&redirect_uri='
          return_uri = django.utils.http.urlquote('http://'+request.get_host()+reverse('admin:cmsplugin_blog_entry_publish_on_facebook', kwargs={ 'entry_id': obj.pk })+'?return_uri='+request.path)
          url = url + return_uri
          url = url + '&scope=publish_stream&response_type=token'
          return redirect(url)
        return resp

    def publish_on_facebook(self, request, entry_id):
        entry = Entry.objects.get(pk=entry_id)
        if request.POST.get('facebook_id'):
            from django.utils import simplejson
            entry.facebook_published = request.POST.get('facebook_id')
            entry.save()
            return HttpResponse(simplejson.dumps({}), mimetype="application/json")
        from django.conf import settings
        from django.shortcuts import render
        return render(request, 'admin/cmsplugin_blog/publish_on_facebook.html', { 'entry': entry, 'site_id': settings.CMS_BLOG_FACEBOOK['site_id'], 'return_uri': request.GET['return_uri'] })

    def get_urls(self):
        from django.conf.urls.defaults import *
        urls = super(BaseEntryAdmin, self).get_urls()
        my_urls = patterns('',
          url(
            r'^(?P<entry_id>\d*)/facebook$',
            self.admin_site.admin_view(self.publish_on_facebook),
            name='cmsplugin_blog_entry_publish_on_facebook',
          ),
        )
        return my_urls + urls

if 'guardian' in settings.INSTALLED_APPS: # pragma: no cover
    from guardian.admin import GuardedModelAdmin
    class EntryAdmin(BaseEntryAdmin, GuardedModelAdmin):
        pass
else:
    EntryAdmin = BaseEntryAdmin
    
admin.site.register(Entry, EntryAdmin)
