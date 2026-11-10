from django.utils.safestring import mark_safe
from wagtail import hooks

@hooks.register('insert_global_admin_css')
def global_admin_css():
    """
    Add custom CSS to hide the default placeholder text in RichText editors.
    The text 'Write something or type '/' to insert a block' is hidden.
    """
    return mark_safe('<style>.public-DraftEditorPlaceholder-root{display:none !important;}</style>')
