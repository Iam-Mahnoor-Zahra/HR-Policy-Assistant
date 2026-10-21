-- Run this whole file in the Supabase SQL Editor.

create table if not exists employees (
  employee_id  text primary key,
  name         text not null,
  annual_total int  not null,
  annual_used  int  not null,
  sick_total   int  not null,
  sick_used    int  not null
);

create table if not exists escalations (
  id          bigint generated always as identity primary key,
  employee_id text references employees(employee_id),
  question    text not null,
  reason      text not null,
  status      text not null default 'open',
  created_at  timestamptz not null default now()
);

-- Fictional employees (same data as data/employees.csv)
insert into employees (employee_id, name, annual_total, annual_used, sick_total, sick_used) values
  ('EMP001', 'Ayesha', 20,  6, 10, 2),
  ('EMP002', 'Bilal',  20, 12, 10, 5),
  ('EMP003', 'Sara',   20,  3, 10, 0),
  ('EMP004', 'Usman',  20,  9, 10, 1),
  ('EMP005', 'Hina',   20, 15, 10, 4),
  ('EMP006', 'Ali',    20,  0, 10, 0),
  ('EMP007', 'Fatima', 20,  8, 10, 3),
  ('EMP008', 'Hamza',  20, 18, 10, 6),
  ('EMP009', 'Zainab', 20,  5, 10, 2),
  ('EMP010', 'Omar',   20, 11, 10, 7)
on conflict (employee_id) do nothing;

-- Keep the tables closed to the public key. The secret/service key used by your
-- server code bypasses this, so the app still works.
alter table employees   enable row level security;
alter table escalations enable row level security;
