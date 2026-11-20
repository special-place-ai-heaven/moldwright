-- Row level security does not cover TRUNCATE, and baseline schema dumps retain the default
-- privileges granted to anon and authenticated on tables and functions created in public.
revoke truncate, trigger, references on all tables in schema public from anon, authenticated;

revoke delete, insert, update on table
    public.api_keys,
    public.blocked_email_domains,
    public.blog_posts,
    public.connector_requests,
    public.engine_box_metrics,
    public.engine_host_metrics,
    public.engine_hosts,
    public.engine_pool,
    public.expert_email_opt_outs,
    public.expert_hire_requests,
    public.invitation_codes,
    public.invitation_redemptions,
    public.published_files,
    public.rerun_usage_events,
    public.workspace_invitations,
    public.workspace_members,
    public.workspaces
from anon, authenticated;

revoke select on table
    public.api_keys,
    public.engine_box_metrics,
    public.engine_host_metrics,
    public.engine_hosts,
    public.engine_pool
from anon, authenticated;

revoke all on function public.consume_rerun_credit(bigint, bigint) from public, anon, authenticated;
revoke all on function public.grant_rerun_topup(bigint, bigint) from public, anon, authenticated;
grant execute on function public.consume_rerun_credit(bigint, bigint) to service_role;
grant execute on function public.grant_rerun_topup(bigint, bigint) to service_role;

revoke all on function public.current_workspace_ids() from public, anon;
grant execute on function public.current_workspace_ids() to authenticated, service_role;
