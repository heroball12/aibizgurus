from django.contrib import messages
from django.core import signing
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from core.permissions import owner_required
from .history import batch, cutoff
from .utils import log_activity

@owner_required
@never_cache
def historical_activity(request):
    state = request.session.get('sales_history_recovery', {'source':'audit', 'after':0})
    report = None
    if request.method == 'POST':
        if request.POST.get('action') == 'restart':
            request.session.pop('sales_history_recovery', None)
            return redirect('historical_activity')
        try:
            submitted = signing.loads(request.POST.get('cursor',''), salt='sales-history', max_age=3600)
            if submitted != state or state['source'] == 'done':
                raise ValueError()
            report = batch(state['source'], state['after'], apply=True)
        except (signing.BadSignature, ValueError):
            messages.error(request, 'Refresh the preview before recovering the next batch.')
            return redirect('historical_activity')
        state = {'source':report['next_source'], 'after':report['next_after']}
        request.session['sales_history_recovery'] = state
        log_activity(user=request.user, request=request, action='other', message='Recovered historical sales activity', metadata=report | {'cutoff':report['cutoff'].isoformat()})
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'done':state['source']=='done', 'cursor':signing.dumps(state, salt='sales-history'), 'report':{k:report[k] for k in ('scanned','recovered','already_counted','unsupported')}})
        messages.success(request, f"Recovered {report['recovered']} records; {report['already_counted']} already counted; {report['unsupported']} without sufficient evidence.")
        return redirect('historical_activity')
    preview = batch(state['source'], state['after']) if cutoff() and state['source'] != 'done' else None
    return render(request, 'audit/historical_activity.html', {'preview':preview, 'done':state['source']=='done', 'cutoff':cutoff(), 'cursor':signing.dumps(state, salt='sales-history')})
