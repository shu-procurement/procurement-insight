
from .models import OngoingProject

def filter_ongoing_projects(request, report_id):
    report = get_object_or_404(ReportPage, id=report_id)
    projects = OngoingProject.objects.filter(page=report)

    # 1. Search Query
    q = request.GET.get('q', '').strip()
    if q:
        projects = projects.filter(
            Q(project_name__icontains=q) |
            Q(procurement_unit__icontains=q)
        )

    # 2. Time Filter (bid_opening_time)
    time_filter = request.GET.get('time', 'all')
    now = timezone.now().date()
    if time_filter == '1m':
        start_date = now - timedelta(days=30)
        projects = projects.filter(bid_opening_time__gte=start_date)
    elif time_filter == '3m':
        start_date = now - timedelta(days=90)
        projects = projects.filter(bid_opening_time__gte=start_date)
    elif time_filter == '6m':
        start_date = now - timedelta(days=180)
        projects = projects.filter(bid_opening_time__gte=start_date)
    elif time_filter == '1y':
        start_date = now - timedelta(days=365)
        projects = projects.filter(bid_opening_time__gte=start_date)
    elif time_filter == '3y':
        start_date = now - timedelta(days=365 * 3)
        projects = projects.filter(bid_opening_time__gte=start_date)

    # 3. Amount Filter (budget_amount)
    amount_filter = request.GET.get('amount', 'all')
    if amount_filter != 'all':
        try:
            if '-' in amount_filter:
                min_val, max_val = map(float, amount_filter.split('-'))
                if max_val == float('inf'):
                    projects = projects.filter(budget_amount__gte=min_val)
                else:
                    projects = projects.filter(budget_amount__gte=min_val, budget_amount__lte=max_val)
            elif amount_filter == '5000-inf': # special case handling if split logic fails or explicit check
                 projects = projects.filter(budget_amount__gte=5000)
        except ValueError:
            pass
            
    # Handle the specific project amount ranges from options if they differ slightly
    # Options: 0-10, 10-50, 50-100, 100-500, 500-1000, 1000-5000, 5000-inf
    
    return render(request, 'reports/partials/ongoing_project_table.html', {
        'projects': projects
    })
