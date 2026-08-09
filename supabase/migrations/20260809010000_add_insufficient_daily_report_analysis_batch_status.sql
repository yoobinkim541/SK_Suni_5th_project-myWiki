alter table public.daily_report_analysis_batches
    drop constraint if exists daily_report_analysis_batches_status_check;

alter table public.daily_report_analysis_batches
    add constraint daily_report_analysis_batches_status_check
    check (status in ('running', 'completed', 'insufficient'));
