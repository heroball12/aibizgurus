from django.urls import reverse


def sheet_tools(request):
    match = request.resolver_match
    if not match or not request.path.startswith('/crm/') or not request.user.is_authenticated:
        return {}
    name = match.url_name
    if name.startswith('lead_sheet'):
        return {}
    query = request.GET.copy()
    for key in ('page','advanced','format'):
        query.pop(key,None)
    query['source'] = 'all'
    if name in ('lead_detail','lead_edit'):
        query.update({'source':'lead','record':str(match.kwargs['pk'])})
    elif name == 'lead_import_detail':
        query.update({'source':'import','record':str(match.kwargs['pk'])})
    elif name in ('lead_finder','lead_generation_batch_detail'):
        query.update({'source':'finder','kind':'prospects'})
        if 'pk' in match.kwargs: query['finder_batch'] = str(match.kwargs['pk'])
    elif name == 'sales_pipeline': query['source'] = 'pipeline'
    elif name == 'sales_assessments': query['source'] = 'assessments'
    elif name == 'lead_queue': query.update({'source':'queue','queue':match.kwargs['queue_type']})
    encoded = query.urlencode()
    return {'context_sheet_url':reverse('lead_sheet_new')+'?'+encoded,'context_export_url':reverse('lead_sheet_export')+'?'+encoded}
