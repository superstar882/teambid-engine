-- TeamBid: start the daily scan on time. GitHub's own schedule often starts hours late or skips a day.
-- Needs supabase-instant-docs.sql first (pg_net + the GitHub token in Vault). Run once: SQL Editor > New query > paste
-- > replace OWNER/REPO > Run. Time: 05:00 UTC = 14:00 Japan time (change the '0 5 * * *' below to move it).

create extension if not exists pg_cron;

create or replace function public.teambid_scan_kick() returns void
language plpgsql security definer set search_path = public, extensions
as $$
declare tok text;
begin
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'teambid_github_token';
  perform net.http_post(
    url := 'https://api.github.com/repos/OWNER/REPO/actions/workflows/scan.yml/dispatches',
    body := '{"ref":"main"}'::jsonb,
    headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                  'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'teambid', 'Content-Type', 'application/json'));
end $$;

revoke all on function public.teambid_scan_kick() from public, anon, authenticated;   -- only the schedule runs it

select cron.unschedule('teambid-daily-scan') where exists (select 1 from cron.job where jobname = 'teambid-daily-scan');
select cron.schedule('teambid-daily-scan', '0 5 * * *', 'select public.teambid_scan_kick()');

-- check it:   select jobname, schedule, active from cron.job;
-- last runs:  select status, start_time from cron.job_run_details order by start_time desc limit 5;
