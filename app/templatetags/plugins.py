from django import template
from app.plugins import get_active_plugins
import itertools

register = template.Library()


@register.simple_tag(takes_context=False)
def get_plugins_js_includes():
    # Flatten all urls for all plugins
    js_urls = list(itertools.chain(*[plugin.get_include_js_urls() for plugin in get_active_plugins()]))
    return "\n".join(map(lambda url: "<script src='{}'></script>".format(url), js_urls))


@register.simple_tag(takes_context=False)
def get_plugins_css_includes():
    # Flatten all urls for all plugins
    css_urls = list(itertools.chain(*[plugin.get_include_css_urls() for plugin in get_active_plugins()]))
    return "\n".join(map(lambda url: "<link href='{}' rel='stylesheet' type='text/css'>".format(url), css_urls))


@register.simple_tag(takes_context=True)
def get_plugins_main_menus(context):
    """
    合并所有插件的 main_menu()，但用每个插件的 user_can_access(request) 过滤。

    takes_context=True 是必须的：菜单可见性需要 request.user。
    settings.py 已注册 'django.template.context_processors.request'，
    所以 context["request"] 在每个模板渲染时都可用。
    模板调用语法不变：{% get_plugins_main_menus as plugin_menus %}。
    """
    request = context.get("request")
    menus = []
    for plugin in get_active_plugins():
        if request is not None and not plugin.user_can_access(request):
            continue  # 未授权：连菜单项都不渲染（URL 直接访问也会被 views.py 拦)
        menus.extend(plugin.main_menu())
    return menus