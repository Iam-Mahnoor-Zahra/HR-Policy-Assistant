-- Saved chat history (run once in the Supabase SQL editor)
create table if not exists chat_sessions (
  id bigint generated always as identity primary key,
  employee_id text not null references employees(employee_id),
  title text not null default 'New chat',
  messages jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists chat_sessions_employee_idx
  on chat_sessions (employee_id, updated_at desc);

-- same as the other tables: the app uses the secret key, nobody else can read it
alter table chat_sessions enable row level security;
