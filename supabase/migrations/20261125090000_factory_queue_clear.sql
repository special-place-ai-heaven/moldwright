-- MW-QUEUE-CLEAR: the owner's last Clear queue, sent to the dispatcher in the factory_report answer
-- (factory-controls.service.ts). queue_clear is {id, repo, issues}: the pending issues the owner saw and
-- confirmed in that project's queue. The dispatcher applies each id once, cancels only those still
-- waiting or queued and not yet claimed, and reports what it cleared and kept. Null until the owner
-- first clears. RLS is unchanged: members read, every write is the server's on service_role.
--
-- Rollback:
--   alter table public.factory_controls drop column queue_clear_at, drop column queue_clear_by, drop column queue_clear;
begin;

alter table public.factory_controls
    add column queue_clear jsonb check (queue_clear is null or jsonb_typeof(queue_clear) = 'object'),
    add column queue_clear_by uuid references auth.users (id) on delete set null,
    add column queue_clear_at timestamptz,
    add constraint factory_controls_queue_clear_at check ((queue_clear is null) = (queue_clear_at is null));

commit;
