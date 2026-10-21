-- TeamBid: start the "Tailor documents" workflow the moment someone asks for documents on the results page.
-- Run once in Supabase: SQL Editor > New query > paste > replace PASTE_GITHUB_TOKEN_HERE and OWNER/REPO > Run.
-- The token is kept in Supabase Vault (encrypted); the page can only call teambid_kick(), never read the token.
-- Token: GitHub > Settings > Developer settings > Fine-grained tokens > Generate new token
--        Repository access: Only select repositories > teambid-engine
--        Permissions: Actions = Read and write (nothing else)

create extension if not exists pg_net;

-- store the token (run again with a new token later: delete the old secret first, see the last line)
select vault.create_secret('PASTE_GITHUB_TOKEN_HERE', 'teambid_github_token', 'starts the TeamBid documents workflow');

create table if not exists public.teambid_kick_log (id int primary key default 1, at timestamptz);
alter table public.teambid_kick_log enable row level security;          -- no policies: only the function can use it

create or replace function public.teambid_kick() returns text
language plpgsql security definer set search_path = public, extensions
as $$
declare
  last timestamptz;
  tok text;
begin
  select at into last from public.teambid_kick_log where id = 1;
  if last is not null and now() - last < interval '30 seconds' then
    return 'already starting';                                           -- one start per 30 s is plenty
  end if;
  insert into public.teambid_kick_log (id, at) values (1, now()) on conflict (id) do update set at = now();
  select decrypted_secret into tok from vault.decrypted_secrets where name = 'teambid_github_token';
  perform net.http_post(
    url := 'https://api.github.com/repos/OWNER/REPO/actions/workflows/docs.yml/dispatches',
    body := '{"ref":"main"}'::jsonb,
    headers := jsonb_build_object('Authorization', 'Bearer ' || tok, 'Accept', 'application/vnd.github+json',
                                  'X-GitHub-Api-Version', '2022-11-28', 'User-Agent', 'teambid', 'Content-Type', 'application/json'));
  return 'started';
end $$;

revoke all on function public.teambid_kick() from public;
grant execute on function public.teambid_kick() to anon;

-- to replace the token later:  delete from vault.secrets where name = 'teambid_github_token';  then run the create_secret line again
