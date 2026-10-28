
-- It is safe to run twice.

-- 1) Employees get an email address (used for notices and as the reply-to address for HR).
alter table employees add column if not exists email text;
update employees set email = lower(name) || '@examplecorp.com' where email is null;

-- >>> For testing, give ONE employee your own email address, so you can receive the notices.
-- >>> Example (edit the address, then remove the two dashes at the start of the line):
-- update employees set email = 'your.address@gmail.com' where employee_id = 'EMP003';

-- 2) Escalations keep the email text that was sent to HR.
alter table escalations add column if not exists message text;

-- 3) Leave requests (used from Day 2).
create table if not exists leave_requests (
  id            bigint generated always as identity primary key,
  employee_id   text not null references employees(employee_id),
  leave_type    text not null check (leave_type in ('annual', 'sick')),
  start_date    date not null,
  end_date      date not null,
  working_days  int  not null,
  status        text not null default 'pending' check (status in ('pending', 'approved', 'rejected')),
  created_at    timestamptz not null default now(),
  decided_at    timestamptz
);

-- 4) Company holidays (used now; Google Calendar can replace this table on Day 3).
create table if not exists holidays (
  holiday_date date primary key,
  name         text not null
);

insert into holidays (holiday_date, name) values
  ('2026-11-09', 'Company Foundation Day'),
  ('2026-12-25', 'Year-End Holiday'),
  ('2026-12-31', 'Year-End Closure'),
  ('2027-01-01', 'New Year''s Day'),
  ('2027-03-23', 'Spring Holiday'),
  ('2027-05-01', 'Labour Day'),
  ('2027-08-14', 'Independence Day')
on conflict (holiday_date) do nothing;

-- 5) Keep the new tables closed to the public key (your secret key still works).
alter table leave_requests enable row level security;
alter table holidays       enable row level security;
